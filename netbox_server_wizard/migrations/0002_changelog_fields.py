"""Добавить штатные поля журнала изменений NetBox к плагиновым моделям."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("netbox_server_wizard", "0001_initial")]

    operations = [
        operation
        for model_name in ("project", "deviceproject", "adapter", "adapterport")
        for operation in (
            migrations.AddField(
                model_name=model_name, name="created",
                field=models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name="created"),
            ),
            migrations.AddField(
                model_name=model_name, name="last_updated",
                field=models.DateTimeField(auto_now=True, blank=True, null=True, verbose_name="last updated"),
            ),
        )
    ]
