"""Безопасный мастер учёта серверов, коммутаторов и коммутации."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from dcim.exceptions import UnsupportedCablePath
from utilities.exceptions import AbortRequest
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from dcim.constants import NONCONNECTABLE_IFACE_TYPES
from dcim.models import Cable, Device, Interface, InterfaceTemplate, Rack, Site
from netbox.plugins import get_plugin_config

from .choices import ALL_FC_TYPES, interface_kind
from .forms import AdapterForm, ConnectionForm, ServerForm
from .models import Adapter, AdapterPort, DeviceProject, Project

MAX_NICS = 64
MAX_CARDS = 16


def card_formset(data=None):
    factory = forms.formset_factory(
        AdapterForm, extra=0, max_num=MAX_CARDS, validate_max=True,
        can_delete=True,
    )
    return factory(data, prefix="cards")


def link_formset(data=None, *, sources, site, user, exclude_device_id=None):
    factory = forms.formset_factory(
        ConnectionForm, extra=0, max_num=MAX_NICS, validate_max=True,
    )
    kwargs = {
        "prefix": "links",
        "form_kwargs": {"site": site, "user": user, "exclude_device_id": exclude_device_id},
    }
    if data is None:
        return factory(initial=[{"nic": s["name"], "kind": s["kind"]} for s in sources], **kwargs)
    return factory(data, **kwargs)


def get_cards(formset):
    return [row.cleaned_data for row in formset.forms if row.cleaned_data and not row.cleaned_data.get("DELETE")]


def get_sources(server_data, cards, user):
    """Список физических портов, включая добавляемые; пересчитывается на каждом POST."""
    if server_data["mode"] == "existing":
        device = server_data["existing_device"]
        # В список подключений попадают только незанятые порты существующего сервера.
        qs = Interface.objects.restrict(user, "view").restrict(user, "change").filter(
            device=device, cable__isnull=True, mark_connected=False
        ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
        sources = [
            {"name": it.name, "kind": interface_kind(it.type), "new": False}
            for it in qs if interface_kind(it.type) is not None
        ]
        reserved = set(Interface.objects.filter(device=device).values_list("name", flat=True))
        existing_card_names = set(Adapter.objects.filter(device=device).values_list("name", flat=True))
    else:
        qs = InterfaceTemplate.objects.restrict(user, "view").filter(
            device_type=server_data["device_type"]
        ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
        sources = [
            {"name": it.name, "kind": interface_kind(it.type), "new": False}
            for it in qs if interface_kind(it.type) is not None
        ]
        reserved = set(InterfaceTemplate.objects.filter(
            device_type=server_data["device_type"]
        ).values_list("name", flat=True))
        existing_card_names = set()

    new_names = set()
    new_card_names = set()
    for card in cards:
        name = card["name"].strip()
        if name in new_card_names or name in existing_card_names:
            raise ValidationError(f"Карта «{name}» уже существует у устройства или указана дважды.")
        new_card_names.add(name)
        for nic in card["ports_list"]:
            if nic in reserved or nic in new_names:
                raise ValidationError(f"Интерфейс «{nic}» уже существует или повторяется.")
            new_names.add(nic)
            sources.append({"name": nic, "kind": card["kind"], "new": True})

    if len(sources) > MAX_NICS:
        raise ValidationError(f"Всего можно обработать не более {MAX_NICS} интерфейсов за операцию.")
    return sources


def validate_links(formset, sources):
    if len(formset.forms) != len(sources):
        raise ValidationError("Перечень интерфейсов изменился. Повторите выбор подключений.")
    ports = set()
    plan = []
    for row, source in zip(formset.forms, sources):
        data = row.cleaned_data
        if data.get("nic") != source["name"] or data.get("kind") != source["kind"]:
            raise ValidationError("Интерфейсы формы изменены. Повторите выбор подключений.")
        port = data.get("port")
        if port:
            if port.pk in ports:
                raise ValidationError("Один и тот же порт коммутатора выбран несколько раз.")
            ports.add(port.pk)
            if interface_kind(port.type) != source["kind"]:
                raise ValidationError("Тип Ethernet/FC у выбранного порта не соответствует интерфейсу устройства.")
            plan.append((source["name"], port.pk))
    return plan


def require_permission(user, permission):
    if not user.has_perm(permission):
        raise PermissionDenied(f"Недостаточно прав для операции: {permission}.")


def require_object_permission(user, instance, action):
    """Проверить ограничение ObjectPermission на конкретном объекте NetBox.

    Для новых объектов вызывается ПОСЛЕ save(), но ДО commit: таким
    образом применяются ограничения к реальным атрибутам созданного объекта,
    а при отказе все изменения откатываются. Модели должны использовать
    RestrictedQuerySet (штатный ChangeLoggedModel в NetBox).
    """
    permission = f"{instance._meta.app_label}.{action}_{instance._meta.model_name}"
    require_permission(user, permission)
    if not type(instance).objects.restrict(user, action).filter(pk=instance.pk).exists():
        raise PermissionDenied("Нет прав на выполнение операции с выбранным объектом.")


def validate_switch_target(user, port, site, device=None):
    """Повторить проверку прав, роли и площадки при сохранении."""
    slugs = get_plugin_config("netbox_server_wizard", "switch_role_slugs") or []
    if not slugs:
        raise ValidationError("Администратор не указал switch_role_slugs. Подключения к коммутаторам запрещены.")
    if port.device.role.slug not in slugs or port.device.site_id != site.pk:
        raise ValidationError("Выбранный порт не относится к разрешённым коммутаторам площадки.")
    if device is not None and port.device_id == device.pk:
        raise ValidationError("Нельзя подключать интерфейс устройства к самому себе.")
    if interface_kind(port.type) is None:
        raise ValidationError("Тип выбранного порта не поддерживается мастером.")
    require_object_permission(user, port.device, "view")
    require_object_permission(user, port, "view")
    require_object_permission(user, port, "change")


def wizard_error_message(exc):
    if isinstance(exc, AbortRequest):
        return f"Не удалось построить кабельный путь: {exc.message}"
    if isinstance(exc, UnsupportedCablePath):
        return "Не удалось построить поддерживаемую кабельную трассу. Проверьте типы портов."
    return str(exc)


def save_wizard(request, server_data, cards, link_plan):
    """Одна транзакция: запрещённые изменения и конфликты откатываются.

    Для кабелей блокируются строки целевых интерфейсов и повторно проверяется
    их занятость. Объектные ограничения проверяются до фиксации транзакции.
    """
    user = request.user
    if server_data["mode"] == "create":
        require_permission(user, "dcim.add_device")
    if cards:
        for permission in (
            "dcim.add_interface", "netbox_server_wizard.add_adapter",
            "netbox_server_wizard.add_adapterport",
        ):
            require_permission(user, permission)
    if link_plan:
        require_permission(user, "dcim.add_cable")
        require_permission(user, "dcim.change_interface")
    if server_data.get("new_project"):
        require_permission(user, "netbox_server_wizard.add_project")

    with transaction.atomic():
        device = None
        if server_data["mode"] == "existing":
            device = Device.objects.select_for_update().get(pk=server_data["existing_device"].pk)
            if device.site_id != server_data["site"].pk:
                raise ValidationError("Устройство перенесено на другую площадку. Обновите форму.")
            # Добавление интерфейсов / кабелей / проекта к устройству требует
            # не только view, но и change на самом устройстве.
            require_object_permission(user, device, "change")
            if server_data.get("serial") and server_data["serial"] != device.serial:
                device.snapshot()
                device.serial = server_data["serial"]
                device.full_clean()
                device.save(update_fields=["serial"])

        requested_ids = [pk for _, pk in link_plan]
        if len(requested_ids) != len(set(requested_ids)):
            raise ValidationError("Один порт коммутатора выбран несколько раз.")
        ports = {
            port.pk: port for port in Interface.objects.select_for_update()
            .select_related("device__role")
            .filter(pk__in=requested_ids)
            .order_by("pk")
        }
        for _, port_id in link_plan:
            port = ports.get(port_id)
            if port is None or port.cable_id is not None or port.mark_connected:
                raise ValidationError("Порт коммутатора уже занят. Обновите список подключений.")
            validate_switch_target(user, port, server_data["site"], device)

        if device is None:
            if Device.objects.filter(name__iexact=server_data["name"]).exists():
                raise ValidationError("Устройство с таким именем уже создано другим пользователем.")
            device = Device(
                name=server_data["name"], site=server_data["site"],
                device_type=server_data["device_type"], role=server_data["role"],
                rack=server_data.get("rack"), position=server_data.get("position"),
                face=server_data.get("face") or "", serial=server_data.get("serial") or "",
                status=server_data["status"],
            )
            device.full_clean()
            device.save()  # NetBox создаёт интерфейсы из Device Type.
            require_object_permission(user, device, "add")

        project = server_data.get("project")
        if project:
            require_object_permission(user, project, "view")
        if server_data.get("new_project"):
            project = Project(name=server_data["new_project"])
            project.full_clean()
            project.save()
            require_object_permission(user, project, "add")
        if project:
            assignment = DeviceProject.objects.select_for_update().filter(device=device).first()
            if assignment is None:
                assignment = DeviceProject(device=device, project=project)
                assignment.full_clean()
                assignment.save()
                require_object_permission(user, assignment, "add")
            elif assignment.project_id != project.pk:
                require_object_permission(user, assignment, "change")
                assignment.snapshot()
                assignment.project = project
                assignment.full_clean()
                assignment.save(update_fields=["project"])

        for card_data in cards:
            adapter = Adapter(
                device=device, name=card_data["name"].strip(), kind=card_data["kind"],
                serial=card_data.get("serial") or "",
                part_number=card_data.get("part_number") or "",
            )
            adapter.full_clean()
            adapter.save()
            require_object_permission(user, adapter, "add")

            port_names = card_data["ports_list"]
            port_wwns = card_data.get("port_wwns_list") or [None] * len(port_names)
            if len(port_names) != len(port_wwns):
                raise ValidationError("Количество WWPN не соответствует портам карты.")
            for nic_name, wwn in zip(port_names, port_wwns):
                interface = Interface(
                    device=device, name=nic_name, type=card_data["port_type"],
                    wwn=wwn, enabled=True,
                )
                interface.full_clean()
                interface.save()
                require_object_permission(user, interface, "add")
                relationship = AdapterPort(adapter=adapter, interface=interface)
                relationship.full_clean()
                relationship.save()
                require_object_permission(user, relationship, "add")

        nics = {nic.name: nic for nic in Interface.objects.filter(device=device)}
        for nic_name, port_id in link_plan:
            nic = nics.get(nic_name)
            if nic is None or nic.cable_id is not None or nic.mark_connected:
                raise ValidationError(f"Интерфейс «{nic_name}» отсутствует или занят.")
            if interface_kind(nic.type) != interface_kind(ports[port_id].type):
                raise ValidationError(f"Тип порта не соответствует интерфейсу «{nic_name}».")
            require_object_permission(user, nic, "change")
            cable = Cable(
                a_terminations=[nic], b_terminations=[ports[port_id]],
                status=server_data["cable_status"],
            )
            cable.full_clean()
            cable.save()
            require_object_permission(user, cable, "add")

    return device

@login_required
@permission_required("dcim.view_device", raise_exception=True)
@permission_required("dcim.view_interface", raise_exception=True)
@require_http_methods(["GET", "POST"])
def add_server(request):
    posted = request.method == "POST"
    stage = request.POST.get("stage") if posted else None
    server_form = ServerForm(request.POST if posted else None, user=request.user)
    cards_formset = card_formset(request.POST if posted else None)
    connections = None
    sources = []
    display_step = "server"

    if posted:
        valid_server = server_form.is_valid()
        valid_cards = cards_formset.is_valid()
        if valid_server and valid_cards:
            try:
                data = server_form.cleaned_data
                cards = get_cards(cards_formset)
                sources = get_sources(data, cards, request.user)
            except ValidationError as exc:
                server_form.add_error(None, exc)
            else:
                display_step = "connections"
                exclude_id = data["existing_device"].pk if data["mode"] == "existing" else None
                connections = link_formset(
                    request.POST if stage == "save" else None,
                    sources=sources, site=data["site"], user=request.user,
                    exclude_device_id=exclude_id,
                )
                if stage == "save" and connections.is_valid():
                    try:
                        link_plan = validate_links(connections, sources)
                        device = save_wizard(request, data, cards, link_plan)
                    except (ValidationError, IntegrityError, AbortRequest, UnsupportedCablePath) as exc:
                        connections._non_form_errors = connections.error_class([wizard_error_message(exc)])
                    else:
                        messages.success(
                            request,
                            f"Устройство «{device.name}» сохранено. Новых карт: {len(cards)}; кабелей: {len(link_plan)}.",
                        )
                        return redirect(device.get_absolute_url())
        else:
            display_step = "server"

    return render(request, "netbox_server_wizard/add.html", {
        "server_form": server_form,
        "cards_formset": cards_formset,
        "connections": connections,
        "sources": sources,
        "step": display_step,
    })


@login_required
@permission_required("dcim.view_device", raise_exception=True)
@permission_required("dcim.view_interface", raise_exception=True)
@require_GET
def free_ports(request):
    site_id = request.GET.get("site_id", "")
    device_id = request.GET.get("device_id", "")
    kind = request.GET.get("kind", "")
    if not (site_id.isdigit() and device_id.isdigit() and kind in ("fc", "ethernet")):
        return JsonResponse({"results": []}, status=400)
    device = Device.objects.restrict(request.user, "view").filter(
        pk=device_id, site_id=site_id
    ).first()
    if device is None:
        return JsonResponse({"results": []}, status=404)
    role_slugs = get_plugin_config("netbox_server_wizard", "switch_role_slugs")
    if not role_slugs or device.role.slug not in role_slugs:
        return JsonResponse({"results": []}, status=404)
    ports = Interface.objects.restrict(request.user, "view").restrict(request.user, "change").filter(
        device=device, cable__isnull=True, mark_connected=False,
    ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
    if kind == "fc":
        ports = ports.filter(type__in=ALL_FC_TYPES)
    else:
        ports = ports.exclude(type__in=ALL_FC_TYPES)
    return JsonResponse({"results": [
        {"id": p.pk, "name": p.name} for p in ports[:512]
        if interface_kind(p.type) == kind
    ]})


@login_required
@permission_required("dcim.view_site", raise_exception=True)
@permission_required("dcim.view_rack", raise_exception=True)
@require_GET
def racks(request):
    site_id = request.GET.get("site_id", "")
    if not site_id.isdigit():
        return JsonResponse({"results": []}, status=400)
    if not Site.objects.restrict(request.user, "view").filter(pk=site_id).exists():
        return JsonResponse({"results": []}, status=404)
    qs = Rack.objects.restrict(request.user, "view").filter(site_id=site_id).order_by("name")
    return JsonResponse({"results": [{"id": r.pk, "name": r.name} for r in qs[:1000]]})


@login_required
@permission_required("dcim.view_device", raise_exception=True)
@require_GET
def devices(request):
    site_id = request.GET.get("site_id", "")
    if not site_id.isdigit():
        return JsonResponse({"results": []}, status=400)
    if not Site.objects.restrict(request.user, "view").filter(pk=site_id).exists():
        return JsonResponse({"results": []}, status=404)
    qs = Device.objects.restrict(request.user, "view").restrict(request.user, "change").filter(site_id=site_id).order_by("name")
    kind = request.GET.get("kind", "server")
    if kind not in ("server", "switch"):
        return JsonResponse({"results": []}, status=400)
    role_key = "switch_role_slugs" if kind == "switch" else "server_role_slugs"
    role_slugs = get_plugin_config("netbox_server_wizard", role_key) or []
    if role_slugs:
        qs = qs.filter(role__slug__in=role_slugs)
    current = list(qs[:1000])
    assigned_projects = {}
    if request.user.has_perm("netbox_server_wizard.view_project") and request.user.has_perm("netbox_server_wizard.view_deviceproject"):
        assigned_projects = dict(
            DeviceProject.objects.restrict(request.user, "view")
            .filter(device_id__in=[d.pk for d in current],
                    project__in=Project.objects.restrict(request.user, "view"))
            .values_list("device_id", "project_id")
        )
    return JsonResponse({"results": [
        {"id": d.pk, "name": d.name or f"Устройство #{d.pk}",
         "serial": d.serial, "project_id": assigned_projects.get(d.pk)}
        for d in current
    ]})


@login_required
@permission_required("netbox_server_wizard.view_project", raise_exception=True)
@require_GET
def projects(request):
    visible_assignments = DeviceProject.objects.restrict(request.user, "view").filter(
        device__in=Device.objects.restrict(request.user, "view")
    )
    qs = Project.objects.restrict(request.user, "view").annotate(
        device_count=Count("devices", filter=Q(devices__in=visible_assignments), distinct=True)
    ).order_by("name")
    return render(request, "netbox_server_wizard/projects.html", {"projects": qs})
