from netbox.plugins import PluginMenuItem


menu_items = (
    PluginMenuItem(
        link="plugins:netbox_server_wizard:add",
        link_text="Добавить сервер / интерфейсы / кабели",
        permissions=["dcim.view_device", "dcim.view_interface"],
    ),
    PluginMenuItem(
        link="plugins:netbox_server_wizard:projects",
        link_text="Проекты серверов",
        permissions=["netbox_server_wizard.view_project"],
    ),
)
