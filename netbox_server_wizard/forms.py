"""Формы двухшагового мастера серверов и физических подключений."""
from django import forms
from dcim.choices import DeviceFaceChoices, DeviceStatusChoices, LinkStatusChoices
from dcim.models import Device, DeviceRole, DeviceType, Rack, Site
from netbox.plugins import get_plugin_config

from .choices import (
    ALL_FC_TYPES, FC_PORT_TYPES, ETHERNET_PORT_TYPES, PORT_TYPE_CHOICES,
    interface_kind, parse_port_names, parse_wwns,
)
from .models import Project
from .endpoints import encode_endpoint, parse_endpoint
from .targets import permitted_targets, permitted_ports, role_termination_kind


class ServerForm(forms.Form):
    equipment_kind = forms.ChoiceField(
        label="Тип оборудования",
        choices=(("server", "Сервер"), ("switch", "Коммутатор / SAN-коммутатор")),
        initial="server",
    )
    mode = forms.ChoiceField(
        label="Что добавить", choices=(
            ("create", "Создать новое устройство в «Устройствах»"),
            ("existing", "Использовать существующее устройство"),
        ), initial="create"
    )
    site = forms.ModelChoiceField(queryset=Site.objects.none(), label="Площадка")
    existing_device = forms.ModelChoiceField(
        queryset=Device.objects.none(), required=False, label="Существующее устройство"
    )
    name = forms.CharField(required=False, max_length=64, label="Имя нового устройства")
    device_type = forms.ModelChoiceField(
        queryset=DeviceType.objects.none(), required=False, label="Модель оборудования"
    )
    role = forms.ModelChoiceField(
        queryset=DeviceRole.objects.none(), required=False, label="Роль устройства"
    )
    rack = forms.ModelChoiceField(
        queryset=Rack.objects.none(), required=False, label="Стойка"
    )
    position = forms.DecimalField(
        required=False, min_value=0.5, max_digits=4, decimal_places=1,
        label="Позиция в стойке (U)"
    )
    face = forms.ChoiceField(
        required=False,
        choices=[("", "Не выбрана"), *((v, {"front": "Передняя", "rear": "Задняя"}.get(v, t))
                 for v, t in DeviceFaceChoices.CHOICES)],
        label="Сторона стойки"
    )
    serial = forms.CharField(
        required=False, max_length=50, label="Серийный номер устройства",
        help_text="Серийный номер корпуса, как на шильдике производителя"
    )
    status = forms.ChoiceField(
        choices=(
            (DeviceStatusChoices.STATUS_PLANNED, "Запланирован"),
            (DeviceStatusChoices.STATUS_STAGED, "Подготовлен"),
            (DeviceStatusChoices.STATUS_ACTIVE, "В эксплуатации"),
            (DeviceStatusChoices.STATUS_OFFLINE, "Выключен"),
            (DeviceStatusChoices.STATUS_FAILED, "Неисправен"),
        ), initial=DeviceStatusChoices.STATUS_PLANNED, label="Статус устройства"
    )
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(), required=False, label="Проект"
    )
    new_project = forms.CharField(
        required=False, max_length=120, label="Создать новый проект",
        help_text="Если проекта ещё нет в списке, укажите его название"
    )
    cable_status = forms.ChoiceField(
        choices=(
            (LinkStatusChoices.STATUS_PLANNED, "Запланировано"),
            (LinkStatusChoices.STATUS_CONNECTED, "Подключено"),
            (LinkStatusChoices.STATUS_DECOMMISSIONING, "Выводится из эксплуатации"),
        ), initial=LinkStatusChoices.STATUS_PLANNED, label="Статус кабелей"
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is None:
            return
        self.fields["site"].queryset = Site.objects.restrict(user, "view").order_by("name")
        self.fields["device_type"].queryset = DeviceType.objects.restrict(user, "view").order_by("model")
        self.fields["role"].queryset = DeviceRole.objects.restrict(user, "view").order_by("name")
        if user.has_perm("netbox_server_wizard.view_project"):
            self.fields["project"].queryset = Project.objects.restrict(user, "view").order_by("name")

        data = self.data if self.is_bound else self.initial
        site_id = str(data.get("site") or "")
        if site_id.isdigit():
            racks = Rack.objects.filter(site_id=site_id).order_by("name")
            self.fields["rack"].queryset = racks.restrict(user, "view")
            devices = Device.objects.filter(site_id=site_id).order_by("name")
            kind = data.get("equipment_kind") or "server"
            role_setting = "switch_role_slugs" if kind == "switch" else "server_role_slugs"
            role_slugs = get_plugin_config("netbox_server_wizard", role_setting) or []
            if role_slugs:
                devices = devices.filter(role__slug__in=role_slugs)
            self.fields["existing_device"].queryset = devices.restrict(user, "view")

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode == "create":
            for field in ("name", "device_type", "role"):
                if not data.get(field):
                    self.add_error(field, "Обязательное поле при создании устройства.")
            if data.get("name"):
                data["name"] = data["name"].strip()
                if Device.objects.filter(name__iexact=data["name"]).exists():
                    self.add_error("name", "Устройство с таким именем уже существует. Выберите режим существующего устройства.")
            if data.get("position") is not None and not data.get("rack"):
                self.add_error("rack", "Для позиции в U необходимо выбрать стойку.")
            if data.get("position") is not None and not data.get("face"):
                self.add_error("face", "Для позиции в U необходимо выбрать сторону стойки.")
            if data.get("rack") and data.get("site") and data["rack"].site_id != data["site"].pk:
                self.add_error("rack", "Стойка не относится к указанной площадке.")
            role = data.get("role")
            if role:
                roles_key = "switch_role_slugs" if data.get("equipment_kind") == "switch" else "server_role_slugs"
                roles = get_plugin_config("netbox_server_wizard", roles_key) or []
                if roles and role.slug not in roles:
                    self.add_error("role", "Роль не соответствует выбранному типу оборудования и настройкам плагина.")
        elif mode == "existing":
            device = data.get("existing_device")
            if not device:
                self.add_error("existing_device", "Выберите существующее устройство.")
            elif data.get("site") and device.site_id != data["site"].pk:
                self.add_error("existing_device", "Устройство находится на другой площадке.")
        if data.get("project") and data.get("new_project"):
            self.add_error("new_project", "Выберите проект из списка или создайте новый, но не оба сразу.")
        if data.get("new_project"):
            data["new_project"] = data["new_project"].strip()
            if not data["new_project"]:
                self.add_error("new_project", "Название проекта не должно состоять из пробелов.")
            elif Project.objects.filter(name__iexact=data["new_project"]).exists():
                self.add_error("new_project", "Такой проект уже есть. Выберите его из списка.")
        return data


class AdapterForm(forms.Form):
    name = forms.CharField(max_length=120, label="Наименование карты", widget=forms.TextInput(attrs={"placeholder": "Intel X710 / QLogic QLE2672"}))
    kind = forms.ChoiceField(label="Тип", choices=(("ethernet", "Ethernet / NIC"), ("fc", "Fibre Channel / HBA")))
    serial = forms.CharField(required=False, max_length=50, label="Серийный номер карты")
    part_number = forms.CharField(required=False, max_length=100, label="Модель / Part Number")
    port_type = forms.ChoiceField(choices=PORT_TYPE_CHOICES, label="Тип портов")
    port_names = forms.CharField(
        max_length=800, label="Имена портов через запятую",
        widget=forms.TextInput(attrs={"placeholder": "ens2f0, ens2f1 / fc0, fc1"}),
    )
    port_wwns = forms.CharField(
        max_length=400, required=False, label="WWPN / WWN портов FC",
        help_text="Для FC: один 64-битный WWPN на каждый порт через запятую. Пустые значения допустимы.",
        widget=forms.TextInput(attrs={"placeholder": "10:00:00:10:9B:12:34:50, 10:00:00:10:9B:12:34:51"}),
    )

    def clean(self):
        data = super().clean()
        kind, port_type = data.get("kind"), data.get("port_type")
        if kind == "fc" and port_type not in dict(FC_PORT_TYPES):
            self.add_error("port_type", "Для FC-карты выберите тип Fibre Channel.")
        if kind == "ethernet" and port_type not in dict(ETHERNET_PORT_TYPES):
            self.add_error("port_type", "Для сетевой карты выберите тип Ethernet.")
        if data.get("port_names"):
            try:
                data["ports_list"] = parse_port_names(data["port_names"])
            except ValueError as exc:
                self.add_error("port_names", str(exc))
        if kind == "ethernet" and data.get("port_wwns", "").strip():
            self.add_error("port_wwns", "WWPN допустим только для FC-карт.")
        elif data.get("ports_list"):
            try:
                data["port_wwns_list"] = parse_wwns(
                    data.get("port_wwns", ""), len(data["ports_list"])
                )
            except ValueError as exc:
                self.add_error("port_wwns", str(exc))
        return data


class ConnectionForm(forms.Form):
    """Первый кабель: Interface источника -> Interface или FrontPort рядом."""

    nic = forms.CharField(widget=forms.HiddenInput())
    kind = forms.CharField(widget=forms.HiddenInput())
    # Имя поля сохранено для совместимости со старой формой и данными POST.
    switch = forms.ModelChoiceField(
        queryset=Device.objects.none(), required=False, label="Ближайшее устройство"
    )
    # ChoiceField позволяет выбирать между двумя моделями окончаний кабеля,
    # не смешивая PK Interface и FrontPort.
    port = forms.ChoiceField(
        choices=(("", "Без подключения"),), required=False,
        label="Свободный Interface / FrontPort",
    )

    def __init__(self, *args, site=None, user=None, exclude_device_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site is None or user is None:
            return
        devices = permitted_targets(site, user, exclude_device_id)
        self.fields["switch"].queryset = devices
        bound_id = self.data.get(self.add_prefix("switch")) if self.is_bound else None
        source_kind = self.data.get(self.add_prefix("kind")) if self.is_bound else self.initial.get("kind")
        if not bound_id or not str(bound_id).isdigit() or source_kind not in ("fc", "ethernet"):
            return
        device = devices.filter(pk=bound_id).first()
        if device is None:
            return
        choices = [("", "Без подключения")]
        for termination in permitted_ports(device, user, source_kind):
            label = f"{termination.name} ({'FrontPort' if termination._meta.model_name == 'frontport' else 'Interface'})"
            choices.append((encode_endpoint(termination), label))
        self.fields["port"].choices = choices

    def clean(self):
        data = super().clean()
        device, raw_port = data.get("switch"), data.get("port")
        if bool(device) != bool(raw_port):
            raise forms.ValidationError("Выберите ближайшее устройство и свободный порт либо оставьте оба поля пустыми.")
        if raw_port:
            try:
                target_kind, _ = parse_endpoint(raw_port)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc
            if role_termination_kind(device) != target_kind:
                raise forms.ValidationError("Порт не соответствует роли выбранного ближайшего устройства.")
        return data
