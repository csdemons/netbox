"""Справочник проектов и учёт установленных дополнительных сетевых карт."""
from django.db import models
from django.core.exceptions import ValidationError
from netbox.models import ChangeLoggedModel


class Project(ChangeLoggedModel):
    """Проект, к которому относится физическое устройство."""

    name = models.CharField("Название", max_length=120, unique=True)
    description = models.TextField("Описание", blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "проект"
        verbose_name_plural = "проекты"
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"), name="netbox_wizard_project_name_ci"
            ),
        ]

    def __str__(self):
        return self.name


class DeviceProject(ChangeLoggedModel):
    """Один основной проект для каждого устройства."""

    device = models.OneToOneField(
        "dcim.Device", on_delete=models.CASCADE, related_name="server_wizard_project",
        verbose_name="Устройство"
    )
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="devices", verbose_name="Проект"
    )

    class Meta:
        verbose_name = "привязка устройства к проекту"
        verbose_name_plural = "привязки устройств к проектам"

    def __str__(self):
        return f"{self.device} — {self.project}"


class Adapter(ChangeLoggedModel):
    """Физическая дополнительная NIC/HBA и её инвентарные данные."""

    KIND_ETHERNET = "ethernet"
    KIND_FC = "fc"
    KIND_CHOICES = ((KIND_ETHERNET, "Ethernet"), (KIND_FC, "Fibre Channel"))

    device = models.ForeignKey(
        "dcim.Device", on_delete=models.CASCADE, related_name="server_wizard_adapters",
        verbose_name="Устройство"
    )
    name = models.CharField("Наименование карты", max_length=120)
    kind = models.CharField("Тип карты", max_length=16, choices=KIND_CHOICES)
    serial = models.CharField("Серийный номер карты", max_length=50, blank=True)
    part_number = models.CharField("Артикул / модель", max_length=100, blank=True)
    created_at = models.DateTimeField("Добавлена", auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "сетевая карта / FC HBA"
        verbose_name_plural = "сетевые карты / FC HBA"
        constraints = [
            models.UniqueConstraint(fields=("device", "name"), name="netbox_wizard_unique_adapter_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.device})"


class AdapterPort(ChangeLoggedModel):
    """Отношение порта адаптера к штатному интерфейсу NetBox."""

    adapter = models.ForeignKey(
        Adapter, on_delete=models.CASCADE, related_name="ports", verbose_name="Карта"
    )
    interface = models.OneToOneField(
        "dcim.Interface", on_delete=models.CASCADE, related_name="server_wizard_adapter_port",
        verbose_name="Интерфейс"
    )

    class Meta:
        verbose_name = "порт дополнительной карты"
        verbose_name_plural = "порты дополнительных карт"

    def clean(self):
        super().clean()
        if self.adapter_id and self.interface_id:
            if self.adapter.device_id != self.interface.device_id:
                raise ValidationError("Порт должен принадлежать тому же устройству, что и карта.")

    def __str__(self):
        return f"{self.adapter.name}: {self.interface.name}"
