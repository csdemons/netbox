from netbox.plugins import PluginConfig


class NetBoxServerWizardConfig(PluginConfig):
    name = "netbox_server_wizard"
    verbose_name = "Мастер подключения серверов"
    description = "Создание серверов и кабельных соединений с коммутаторами за одну операцию"
    version = "0.2.0"
    author = "csdemons"
    min_version = "4.5.0"
    default_settings = {"switch_role_slugs": []}


config = NetBoxServerWizardConfig
