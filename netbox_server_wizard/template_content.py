"""Отображение проекта и доп. карт на стандартной странице Device в NetBox."""
from netbox.plugins import PluginTemplateExtension

from .models import Adapter, DeviceProject


class ServerProjectDetails(PluginTemplateExtension):
    models = ["dcim.device"]

    def right_page(self):
        request = self.context.get("request")
        device = self.context.get("object")
        if not request or not device:
            return ""
        can_view_project = request.user.has_perm("netbox_server_wizard.view_project")
        can_view_adapters = request.user.has_perm("netbox_server_wizard.view_adapter")
        if not (can_view_project or can_view_adapters):
            return ""
        assignment = DeviceProject.objects.filter(device=device).select_related("project").first() if can_view_project else None
        adapters = (
            Adapter.objects.filter(device=device).prefetch_related("ports__interface")
            if can_view_adapters else []
        )
        return self.render("netbox_server_wizard/device_panel.html", {
            "project_assignment": assignment,
            "server_adapters": adapters,
            "can_view_project": can_view_project,
            "can_view_adapters": can_view_adapters,
        })


template_extensions = [ServerProjectDetails]
