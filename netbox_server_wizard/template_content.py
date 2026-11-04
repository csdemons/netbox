"""Отображение проекта и доп. карт на стандартной странице Device в NetBox."""
from netbox.plugins import PluginTemplateExtension
from django.db.models import Prefetch
from dcim.models import Interface

from .models import Adapter, AdapterPort, DeviceProject, Project


class ServerProjectDetails(PluginTemplateExtension):
    models = ["dcim.device"]

    def right_page(self):
        request = self.context.get("request")
        device = self.context.get("object")
        if not request or not device:
            return ""
        can_view_project = (
            request.user.has_perm("netbox_server_wizard.view_project")
            and request.user.has_perm("netbox_server_wizard.view_deviceproject")
        )
        can_view_adapters = request.user.has_perm("netbox_server_wizard.view_adapter")
        if not (can_view_project or can_view_adapters):
            return ""
        assignment = None
        if can_view_project:
            assignment = (
                DeviceProject.objects.restrict(request.user, "view")
                .filter(device=device, project__in=Project.objects.restrict(request.user, "view"))
                .select_related("project")
                .first()
            )
        ports_allowed = AdapterPort.objects.restrict(request.user, "view").filter(
            interface__in=Interface.objects.restrict(request.user, "view")
        ).select_related("interface")
        adapters = (
            Adapter.objects.restrict(request.user, "view").filter(device=device)
            .prefetch_related(Prefetch("ports", queryset=ports_allowed))
            if can_view_adapters else []
        )
        return self.render("netbox_server_wizard/device_panel.html", {
            "project_assignment": assignment,
            "server_adapters": adapters,
            "can_view_project": can_view_project,
            "can_view_adapters": can_view_adapters,
        })


template_extensions = [ServerProjectDetails]
