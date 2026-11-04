from netbox.plugins import PluginConfig


class RRCKIServerWizardConfig(PluginConfig):
    name = "rrcki_server_wizard"
    verbose_name = "Мастер подключения серверов RRCKI"
    description = "Создание серверов и кабельных соединений с коммутаторами за одну операцию"
    version = "0.1.0"
    author = "RRCKI"
    min_version = "4.5.0"
    default_settings = {"switch_role_slugs": []}


config = RRCKIServerWizardConfig
