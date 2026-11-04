"""Мастер: существующее/новое устройство -> карты -> кабели -> проект."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
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


def get_sources(server_data, cards):
    """Список физических портов, включая добавляемые; пересчитывается на каждом POST."""
    if server_data["mode"] == "existing":
        device = server_data["existing_device"]
        # В список подключений попадают только незанятые порты существующего сервера.
        qs = Interface.objects.filter(
            device=device, cable__isnull=True, mark_connected=False
        ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
        sources = [{"name": it.name, "kind": interface_kind(it.type), "new": False} for it in qs]
        reserved = set(Interface.objects.filter(device=device).values_list("name", flat=True))
        existing_card_names = set(Adapter.objects.filter(device=device).values_list("name", flat=True))
    else:
        qs = InterfaceTemplate.objects.filter(
            device_type=server_data["device_type"]
        ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
        sources = [{"name": it.name, "kind": interface_kind(it.type), "new": False} for it in qs]
        reserved = {row["name"] for row in sources}
        existing_card_names = set()

    new_names = set()
    new_card_names = set()
    for card in cards:
        name = card["name"].strip()
        if name in new_card_names or name in existing_card_names:
            raise ValidationError(f"Карта «{name}» уже существует у этого сервера или указана дважды.")
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
            if (port.type in ALL_FC_TYPES) != (source["kind"] == "fc"):
                raise ValidationError("Тип Ethernet/FC у выбранного порта не соответствует интерфейсу сервера.")
            plan.append((source["name"], port.pk))
    return plan


def require_permission(user, permission):
    if not user.has_perm(permission):
        raise PermissionDenied(f"Недостаточно прав для операции: {permission}.")


def save_wizard(request, server_data, cards, link_plan):
    """Все изменения атомарны; при проблеме с портом не останется неполного устройства."""
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
    if server_data.get("new_project"):
        require_permission(user, "netbox_server_wizard.add_project")
    with transaction.atomic():
        if server_data["mode"] == "existing":
            device = Device.objects.select_for_update().get(pk=server_data["existing_device"].pk)
            if device.site_id != server_data["site"].pk:
                raise ValidationError("Сервер перенесён на другую площадку. Обновите форму.")
            if server_data.get("serial") and server_data["serial"] != device.serial:
                require_permission(user, "dcim.change_device")
                device.serial = server_data["serial"]
                device.full_clean()
                device.save(update_fields=["serial"])
        else:
            device = None

        ports = {
            p.pk: p for p in Interface.objects.select_for_update()
            .filter(pk__in=[pk for _, pk in link_plan]).order_by("pk")
        }
        for _, port_id in link_plan:
            port = ports.get(port_id)
            if port is None or port.cable_id is not None or port.mark_connected:
                raise ValidationError("Порт коммутатора уже занят. Обновите список подключений.")
            if port.device.site_id != server_data["site"].pk:
                raise ValidationError("Порт находится на другой площадке.")
            if device is not None and port.device_id == device.pk:
                raise ValidationError("Нельзя подключить сервер к самому себе через мастер.")

        if device is None:
            if Device.objects.filter(name__iexact=server_data["name"]).exists():
                raise ValidationError("Сервер с таким именем уже создан другим пользователем.")
            device = Device(
                name=server_data["name"], site=server_data["site"],
                device_type=server_data["device_type"], role=server_data["role"],
                rack=server_data.get("rack"), position=server_data.get("position"),
                face=server_data.get("face") or "", serial=server_data.get("serial") or "",
                status=server_data["status"],
            )
            device.full_clean()
            device.save()  # NetBox автоматически создаёт интерфейсы из Device Type.

        project = server_data.get("project")
        if server_data.get("new_project"):
            project = Project(name=server_data["new_project"])
            project.full_clean()
            project.save()
        if project:
            assignment = DeviceProject.objects.select_for_update().filter(device=device).first()
            if assignment is None:
                require_permission(user, "netbox_server_wizard.add_deviceproject")
                assignment = DeviceProject(device=device, project=project)
                assignment.full_clean()
                assignment.save()
            elif assignment.project_id != project.pk:
                require_permission(user, "netbox_server_wizard.change_deviceproject")
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
            for nic_name in card_data["ports_list"]:
                interface = Interface(
                    device=device, name=nic_name, type=card_data["port_type"], enabled=True,
                )
                interface.full_clean()
                interface.save()
                relationship = AdapterPort(adapter=adapter, interface=interface)
                relationship.full_clean()
                relationship.save()

        nics = {n.name: n for n in Interface.objects.filter(device=device)}
        for nic_name, port_id in link_plan:
            nic = nics.get(nic_name)
            if nic is None or nic.cable_id is not None or nic.mark_connected:
                raise ValidationError(f"Интерфейс «{nic_name}» отсутствует или занят.")
            cable = Cable(
                a_terminations=[nic], b_terminations=[ports[port_id]],
                status=server_data["cable_status"],
            )
            cable.full_clean()
            cable.save()

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
                sources = get_sources(data, cards)
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
                    except (ValidationError, IntegrityError) as exc:
                        connections._non_form_errors = connections.error_class([str(exc)])
                    else:
                        messages.success(
                            request,
                            f"Сервер «{device.name}» сохранён. Новых карт: {len(cards)}; кабелей: {len(link_plan)}.",
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
    if role_slugs and device.role.slug not in role_slugs:
        return JsonResponse({"results": []}, status=404)
    ports = Interface.objects.restrict(request.user, "view").filter(
        device=device, cable__isnull=True, mark_connected=False,
    ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
    if kind == "fc":
        ports = ports.filter(type__in=ALL_FC_TYPES)
    else:
        ports = ports.exclude(type__in=ALL_FC_TYPES)
    return JsonResponse({"results": [{"id": p.pk, "name": p.name} for p in ports[:512]]})


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
    qs = Device.objects.restrict(request.user, "view").filter(site_id=site_id).order_by("name")
    role_slugs = get_plugin_config("netbox_server_wizard", "server_role_slugs")
    if role_slugs:
        qs = qs.filter(role__slug__in=role_slugs)
    current = list(qs[:1000])
    assigned_projects = {}
    if request.user.has_perm("netbox_server_wizard.view_project"):
        assigned_projects = dict(
            DeviceProject.objects.filter(device_id__in=[d.pk for d in current])
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
    qs = Project.objects.annotate(device_count=Count("devices")).order_by("name")
    return render(request, "netbox_server_wizard/projects.html", {"projects": qs})
