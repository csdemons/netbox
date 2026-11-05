from netbox.plugins import PluginConfig


class NetBoxServerWizardConfig(PluginConfig):
    name = "netbox_server_wizard"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "NetBox Plan"
    description = "Планирование устройств и первого кабеля до коммутатора или патч-панели"
    version = "0.5.1"
    author = "csdemons"
    min_version = "4.5.0"
    default_settings = {
        "switch_role_slugs": [],
        "server_role_slugs": [],
        "patch_panel_role_slugs": [],
    }


config = NetBoxServerWizardConfig
