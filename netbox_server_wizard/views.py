from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from dcim.constants import NONCONNECTABLE_IFACE_TYPES
from dcim.models import Cable, Device, Interface, InterfaceTemplate, Rack, Site
from netbox.plugins import get_plugin_config

from .forms import ConnectionForm, ServerForm

MAX_NICS = 64
REQUIRED_PERMS = (
    "dcim.add_device",
    "dcim.add_cable",
    "dcim.view_device",
    "dcim.view_interface",
)


def guarded(view):
    for perm in REQUIRED_PERMS:
        view = permission_required(perm, raise_exception=True)(view)
    return login_required(view)


def nic_names(device_type):
    """Список физических интерфейсов из шаблона модели устройства в стабильном порядке."""
    return list(
        InterfaceTemplate.objects.filter(device_type=device_type)
        .exclude(type__in=NONCONNECTABLE_IFACE_TYPES)
        .order_by("name")
        .values_list("name", flat=True)
    )


def build_formset(data=None, *, names, site, user):
    factory = forms.formset_factory(ConnectionForm, extra=0, max_num=MAX_NICS, validate_max=True)
    kwargs = dict(prefix="links", form_kwargs={"site": site, "user": user})
    if data is None:
        return factory(initial=[{"nic": name} for name in names], **kwargs)
    return factory(data, **kwargs)


def validate_links(formset, names):
    if len(formset.forms) != len(names):
        raise ValidationError("Список интерфейсов изменился. Начните добавление сервера заново.")
    selected_ports = set()
    links = []
    for row, expected_name in zip(formset.forms, names):
        data = row.cleaned_data
        if data.get("nic") != expected_name:
            raise ValidationError("Список интерфейсов изменился. Начните добавление сервера заново.")
        port = data.get("port")
        if port:
            if port.pk in selected_ports:
                raise ValidationError("Один и тот же порт коммутатора выбран несколько раз.")
            selected_ports.add(port.pk)
            links.append((expected_name, port.pk))
    return links


@guarded
@require_http_methods(["GET", "POST"])
def add_server(request):
    is_post = request.method == "POST"
    preview = request.GET.get("step") == "connections"
    values = request.POST if is_post else (request.GET if preview else None)
    server_form = ServerForm(values, user=request.user)
    show_connections = is_post or preview
    formset = None

    if show_connections and server_form.is_valid():
        data = server_form.cleaned_data
        names = nic_names(data["device_type"])
        if not names:
            server_form.add_error("device_type", "У выбранной модели оборудования нет шаблонов физических сетевых интерфейсов.")
        elif len(names) > MAX_NICS:
            server_form.add_error("device_type", f"У модели более {MAX_NICS} сетевых интерфейсов — превышен лимит мастера.")
        else:
            formset = build_formset(request.POST if is_post else None, names=names, site=data["site"], user=request.user)
            if is_post and formset.is_valid():
                try:
                    link_plan = validate_links(formset, names)
                    with transaction.atomic():
                        ports = {
                            p.pk: p for p in Interface.objects.select_for_update()
                            .filter(pk__in=[pk for _, pk in link_plan])
                            .order_by("pk")
                        }
                        for _, port_id in link_plan:
                            port = ports.get(port_id)
                            if port is None or port.cable_id is not None or port.mark_connected:
                                raise ValidationError("Выбранный порт коммутатора больше не свободен. Обновите форму и выберите другой порт.")
                            if port.device.site_id != data["site"].pk:
                                raise ValidationError("Выбранный порт коммутатора находится на другой площадке.")
                        device = Device(
                            name=data["name"],
                            site=data["site"],
                            device_type=data["device_type"],
                            role=data["role"],
                            rack=data.get("rack"),
                            position=data.get("position"),
                            face=data.get("face") or "",
                            serial=data.get("serial") or "",
                            status=data["status"],
                        )
                        device.full_clean()
                        device.save()
                        new_nics = {n.name: n for n in Interface.objects.filter(device=device)}
                        for nic_name, port_id in link_plan:
                            if nic_name not in new_nics:
                                raise ValidationError(f"Интерфейс {nic_name} не найден на созданном сервере.")
                            cable = Cable(
                                a_terminations=[new_nics[nic_name]],
                                b_terminations=[ports[port_id]],
                                status=data["cable_status"],
                            )
                            cable.full_clean()
                            cable.save()
                except (ValidationError, IntegrityError) as exc:
                    formset._non_form_errors = formset.error_class([str(exc)])
                else:
                    messages.success(request, f"Сервер «{device.name}» создан. Кабельных подключений: {len(link_plan)}.")
                    return redirect(device.get_absolute_url())

    return render(request, "netbox_server_wizard/add.html", {
        "server_form": server_form,
        "formset": formset,
        "step": "connections" if formset is not None else "server",
    })


@login_required
@permission_required("dcim.view_device", raise_exception=True)
@permission_required("dcim.view_interface", raise_exception=True)
@require_GET
def free_ports(request):
    site_id = request.GET.get("site_id", "")
    device_id = request.GET.get("device_id", "")
    if not (site_id.isdigit() and device_id.isdigit()):
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
        device=device, cable__isnull=True, mark_connected=False
    ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
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
