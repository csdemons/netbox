# Migration for NetBox Server Wizard 0.3.0 (NetBox 4.5.x)
import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    initial = True

    dependencies = [("dcim", "0225_gfk_indexes")]

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Название")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
            ],
            options={"verbose_name": "проект", "verbose_name_plural": "проекты", "ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(Lower("name"), name="netbox_wizard_project_name_ci"),
        ),
        migrations.CreateModel(
            name="DeviceProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="server_wizard_project", to="dcim.device", verbose_name="Устройство")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="devices", to="netbox_server_wizard.project", verbose_name="Проект")),
            ],
            options={"verbose_name": "привязка устройства к проекту", "verbose_name_plural": "привязки устройств к проектам"},
        ),
        migrations.CreateModel(
            name="Adapter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="Наименование карты")),
                ("kind", models.CharField(choices=[("ethernet", "Ethernet"), ("fc", "Fibre Channel")], max_length=16, verbose_name="Тип карты")),
                ("serial", models.CharField(blank=True, max_length=50, verbose_name="Серийный номер карты")),
                ("part_number", models.CharField(blank=True, max_length=100, verbose_name="Артикул / модель")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Добавлена")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="server_wizard_adapters", to="dcim.device", verbose_name="Устройство")),
            ],
            options={"verbose_name": "сетевая карта / FC HBA", "verbose_name_plural": "сетевые карты / FC HBA", "ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="adapter",
            constraint=models.UniqueConstraint(fields=("device", "name"), name="netbox_wizard_unique_adapter_name"),
        ),
        migrations.CreateModel(
            name="AdapterPort",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("adapter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ports", to="netbox_server_wizard.adapter", verbose_name="Карта")),
                ("interface", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="server_wizard_adapter_port", to="dcim.interface", verbose_name="Интерфейс")),
            ],
            options={"verbose_name": "порт дополнительной карты", "verbose_name_plural": "порты дополнительных карт"},
        ),
    ]
