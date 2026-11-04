from django import forms
from dcim.choices import DeviceFaceChoices, DeviceStatusChoices, LinkStatusChoices
from dcim.constants import NONCONNECTABLE_IFACE_TYPES
from dcim.models import Device, DeviceRole, DeviceType, Interface, Rack, Site
from netbox.plugins import get_plugin_config


class ServerForm(forms.Form):
    name = forms.CharField(max_length=64, label="Имя сервера")
    site = forms.ModelChoiceField(queryset=Site.objects.all(), label="Площадка")
    device_type = forms.ModelChoiceField(queryset=DeviceType.objects.all(), label="Модель оборудования")
    role = forms.ModelChoiceField(queryset=DeviceRole.objects.all(), label="Роль устройства")
    rack = forms.ModelChoiceField(queryset=Rack.objects.none(), required=False, label="Стойка")
    position = forms.DecimalField(
        required=False, min_value=0.5, max_digits=4, decimal_places=1, label="Позиция в стойке (U)"
    )
    face = forms.ChoiceField(
        required=False, choices=[
            ("", "Не выбрана"),
            *(
                (value, {"front": "Передняя", "rear": "Задняя"}.get(value, label))
                for value, label in DeviceFaceChoices.CHOICES
            ),
        ], label="Сторона стойки"
    )
    serial = forms.CharField(required=False, max_length=50, label="Серийный номер")
    status = forms.ChoiceField(
        choices=DeviceStatusChoices,
        initial=DeviceStatusChoices.STATUS_PLANNED,
        label="Статус сервера",
    )
    cable_status = forms.ChoiceField(
        choices=LinkStatusChoices,
        initial=LinkStatusChoices.STATUS_PLANNED,
        label="Статус кабеля",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["site"].queryset = Site.objects.restrict(user, "view").order_by("name")
            self.fields["device_type"].queryset = DeviceType.objects.restrict(user, "view").order_by("model")
            self.fields["role"].queryset = DeviceRole.objects.restrict(user, "view").order_by("name")

        data = self.data if self.is_bound else self.initial
        site_id = data.get("site")
        if site_id and str(site_id).isdigit():
            racks = Rack.objects.filter(site_id=site_id).order_by("name")
            self.fields["rack"].queryset = racks.restrict(user, "view") if user is not None else racks

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Device.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Устройство с таким именем уже существует.")
        return name

    def clean(self):
        data = super().clean()
        if data.get("position") and not data.get("rack"):
            self.add_error("rack", "Для указания позиции необходимо выбрать стойку.")
        if data.get("position") and not data.get("face"):
            self.add_error("face", "Для указания позиции необходимо выбрать сторону стойки.")
        return data


class ConnectionForm(forms.Form):
    nic = forms.CharField(widget=forms.HiddenInput())
    switch = forms.ModelChoiceField(queryset=Device.objects.none(), required=False, label="Коммутатор")
    port = forms.ModelChoiceField(queryset=Interface.objects.none(), required=False, label="Порт коммутатора")

    def __init__(self, *args, site=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if site is None:
            return
        devices = Device.objects.filter(site=site).order_by("name")
        role_slugs = get_plugin_config("rrcki_server_wizard", "switch_role_slugs")
        if role_slugs:
            devices = devices.filter(role__slug__in=role_slugs)
        if user is not None:
            devices = devices.restrict(user, "view")
        self.fields["switch"].queryset = devices
        bound_id = None
        if self.is_bound:
            bound_id = self.data.get(self.add_prefix("switch"))
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
        switch = data.get("switch")
        port = data.get("port")
        if bool(switch) != bool(port):
            raise forms.ValidationError("Выберите коммутатор и свободный порт или оставьте оба поля пустыми.")
        if port and port.device_id != switch.pk:
            raise forms.ValidationError("Выбранный порт не принадлежит указанному коммутатору.")
        return data
