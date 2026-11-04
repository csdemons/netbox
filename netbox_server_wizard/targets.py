"""Ближайшие устройства и свободные окончания только ПЕРВОГО кабеля.

Не строим составные трассы. Для патч-панели выбираем её FrontPort,
внутренний FrontPort -> RearPort mapping и следующие кабели остаются в NetBox.
"""
from dcim.constants import NONCONNECTABLE_IFACE_TYPES
from dcim.models import Device, FrontPort, Interface
from netbox.plugins import get_plugin_config

from .choices import interface_kind

MAX_PORT_CHOICES = 512


def role_termination_kind(device):
    """Коммутатор -> Interface; патч-панель -> FrontPort; иначе нет выбора.

    Если одна роль ошибочно указана в двух группах, приоритет отдаём
    интерфейсу коммутатора и не смешиваем модели окончаний.
    """
    switch_roles = get_plugin_config("netbox_server_wizard", "switch_role_slugs") or []
    panel_roles = get_plugin_config("netbox_server_wizard", "patch_panel_role_slugs") or []
    if device.role.slug in switch_roles and device.role.slug in panel_roles:
        return None  # не допускаем неоднозначную роль
    if device.role.slug in switch_roles:
        return "interface"
    if device.role.slug in panel_roles:
        return "frontport"
    return None


def permitted_targets(site, user, exclude_device_id=None):
    switch_roles = get_plugin_config("netbox_server_wizard", "switch_role_slugs") or []
    panel_roles = get_plugin_config("netbox_server_wizard", "patch_panel_role_slugs") or []
    roles = set(switch_roles) | set(panel_roles)
    qs = Device.objects.filter(site=site, role__slug__in=roles).exclude(
        role__slug__in=set(switch_roles) & set(panel_roles)
    ).order_by("name")
    if exclude_device_id:
        qs = qs.exclude(pk=exclude_device_id)
    return qs.restrict(user, "view")


def permitted_ports(device, user, source_kind):
    """Только физически доступные порты и право view + change на окончание.

    FrontPort.type описывает разъём (LC/SC/8P8C), а не Ethernet/FC.
    Для FrontPort НЕ фильтруем по протоколу интерфейса источника.
    Для многопозиционных FrontPort требуется отдельный профиль кабеля,
    поэтому в мастере допускаем лишь positions=1.
    """
    mode = role_termination_kind(device)
    if mode == "interface":
        qs = Interface.objects.filter(
            device=device, cable__isnull=True, mark_connected=False,
        ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
        qs = qs.restrict(user, "view").restrict(user, "change")
        return [p for p in qs[:MAX_PORT_CHOICES] if interface_kind(p.type) == source_kind]
    if mode == "frontport":
        qs = FrontPort.objects.filter(
            device=device, cable__isnull=True, mark_connected=False, positions=1,
        ).order_by("name")
        return list(qs.restrict(user, "view").restrict(user, "change")[:MAX_PORT_CHOICES])
    return []
