from netbox.plugins import PluginMenuItem


menu_items = (
    PluginMenuItem(
        link="plugins:rrcki_server_wizard:add",
        link_text="Добавить сервер с подключениями",
        permissions=["dcim.add_device", "dcim.add_cable", "dcim.view_interface", "dcim.view_device"],
    ),
)
