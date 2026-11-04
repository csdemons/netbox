from netbox.plugins import PluginConfig


class NetBoxServerWizardConfig(PluginConfig):
    name = "netbox_server_wizard"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Мастер подключения серверов"
    description = "Добавление физических серверов, Ethernet/FC карт и кабелей с привязкой к проекту"
    version = "0.3.0"
    author = "csdemons"
    min_version = "4.5.0"
    default_settings = {
        "switch_role_slugs": [],
        "server_role_slugs": [],
    }


config = NetBoxServerWizardConfig
