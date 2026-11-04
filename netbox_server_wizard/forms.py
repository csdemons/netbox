"""Формы двухшагового мастера серверов и физических подключений."""
from django import forms
from dcim.choices import DeviceFaceChoices, DeviceStatusChoices, LinkStatusChoices
from dcim.constants import NONCONNECTABLE_IFACE_TYPES
from dcim.models import Device, DeviceRole, DeviceType, Interface, Rack, Site
from netbox.plugins import get_plugin_config

from .choices import ALL_FC_TYPES, FC_PORT_TYPES, ETHERNET_PORT_TYPES, PORT_TYPE_CHOICES, parse_port_names
from .models import Project


class ServerForm(forms.Form):
    mode = forms.ChoiceField(
        label="Что добавить", choices=(
            ("create", "Создать новый сервер в «Устройствах»"),
            ("existing", "Использовать существующий сервер"),
        ), initial="create"
    )
    site = forms.ModelChoiceField(queryset=Site.objects.none(), label="Площадка")
    existing_device = forms.ModelChoiceField(
        queryset=Device.objects.none(), required=False, label="Существующий сервер"
    )
    name = forms.CharField(required=False, max_length=64, label="Имя нового сервера")
    device_type = forms.ModelChoiceField(
        queryset=DeviceType.objects.none(), required=False, label="Модель сервера"
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
        required=False, max_length=50, label="Серийный номер сервера",
        help_text="Серийный номер корпуса, как на шильдике производителя"
    )
    status = forms.ChoiceField(
        choices=(
            (DeviceStatusChoices.STATUS_PLANNED, "Запланирован"),
            (DeviceStatusChoices.STATUS_STAGED, "Подготовлен"),
            (DeviceStatusChoices.STATUS_ACTIVE, "В эксплуатации"),
            (DeviceStatusChoices.STATUS_OFFLINE, "Выключен"),
            (DeviceStatusChoices.STATUS_FAILED, "Неисправен"),
        ), initial=DeviceStatusChoices.STATUS_PLANNED, label="Статус сервера"
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
            self.fields["project"].queryset = Project.objects.all()

        data = self.data if self.is_bound else self.initial
        site_id = str(data.get("site") or "")
        if site_id.isdigit():
            racks = Rack.objects.filter(site_id=site_id).order_by("name")
            self.fields["rack"].queryset = racks.restrict(user, "view")
            devices = Device.objects.filter(site_id=site_id).order_by("name")
            role_slugs = get_plugin_config("netbox_server_wizard", "server_role_slugs")
            if role_slugs:
                devices = devices.filter(role__slug__in=role_slugs)
            self.fields["existing_device"].queryset = devices.restrict(user, "view")

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode == "create":
            for field in ("name", "device_type", "role"):
                if not data.get(field):
                    self.add_error(field, "Обязательное поле при создании сервера.")
            if data.get("name"):
                data["name"] = data["name"].strip()
                if Device.objects.filter(name__iexact=data["name"]).exists():
                    self.add_error("name", "Устройство с таким именем уже существует. Выберите режим существующего сервера.")
            if data.get("position") is not None and not data.get("rack"):
                self.add_error("rack", "Для позиции в U необходимо выбрать стойку.")
            if data.get("position") is not None and not data.get("face"):
                self.add_error("face", "Для позиции в U необходимо выбрать сторону стойки.")
            if data.get("rack") and data.get("site") and data["rack"].site_id != data["site"].pk:
                self.add_error("rack", "Стойка не относится к указанной площадке.")
        elif mode == "existing":
            device = data.get("existing_device")
            if not device:
                self.add_error("existing_device", "Выберите существующий сервер.")
            elif data.get("site") and device.site_id != data["site"].pk:
                self.add_error("existing_device", "Сервер находится на другой площадке.")
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
        return data


class ConnectionForm(forms.Form):
    nic = forms.CharField(widget=forms.HiddenInput())
    kind = forms.CharField(widget=forms.HiddenInput())
    switch = forms.ModelChoiceField(queryset=Device.objects.none(), required=False, label="Коммутатор")
    port = forms.ModelChoiceField(queryset=Interface.objects.none(), required=False, label="Свободный порт")

    def __init__(self, *args, site=None, user=None, exclude_device_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site is None:
            return
        devices = Device.objects.filter(site=site).order_by("name")
        if exclude_device_id:
            devices = devices.exclude(pk=exclude_device_id)
        role_slugs = get_plugin_config("netbox_server_wizard", "switch_role_slugs")
        if role_slugs:
            devices = devices.filter(role__slug__in=role_slugs)
        if user is not None:
            devices = devices.restrict(user, "view")
        self.fields["switch"].queryset = devices
        bound_id = self.data.get(self.add_prefix("switch")) if self.is_bound else None
        if bound_id and str(bound_id).isdigit():
            ports = Interface.objects.filter(
                device_id=bound_id, device__site=site,
                cable__isnull=True, mark_connected=False,
            ).exclude(type__in=NONCONNECTABLE_IFACE_TYPES).order_by("name")
            if user is not None:
                ports = ports.restrict(user, "view")
            self.fields["port"].queryset = ports

    def clean(self):
        data = super().clean()
        switch, port = data.get("switch"), data.get("port")
        if bool(switch) != bool(port):
            raise forms.ValidationError("Выберите коммутатор вместе с портом или оставьте оба поля пустыми.")
        if port and port.device_id != switch.pk:
            raise forms.ValidationError("Порт не принадлежит выбранному коммутатору.")
        if port and data.get("kind") == "fc" and port.type not in ALL_FC_TYPES:
            raise forms.ValidationError("К FC-интерфейсу необходимо выбрать FC-порт коммутатора.")
        if port and data.get("kind") == "ethernet" and port.type in ALL_FC_TYPES:
            raise forms.ValidationError("К Ethernet-интерфейсу нельзя подключить FC-порт.")
        return data
