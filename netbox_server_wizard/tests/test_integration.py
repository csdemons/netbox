"""Интеграционные проверки. Запускать с NetBox и PostgreSQL в тестовом Docker-стеке.

    /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_server_wizard.tests

Никакого запуска на рабочей базе: Django создаёт отдельную тестовую БД.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.contenttypes.models import ContentType
from core.models import ObjectChange
from django.db import IntegrityError, close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase

from core.models import ObjectType
from dcim.models import (
    Cable, Device, DeviceRole, DeviceType, Interface, InterfaceTemplate, Manufacturer, Site,
)
from netbox.models import ChangeLoggedModel
from users.models import ObjectPermission, User

from netbox_server_wizard.forms import AdapterForm, ServerForm
from netbox_server_wizard.models import Adapter, AdapterPort, DeviceProject, Project
from netbox_server_wizard.views import save_wizard, validate_switch_target


class WizardFixture:
    def setup_inventory(self):
        self.site = Site.objects.create(name="Тест ЦОД 1", slug="wizard-ci-1")
        self.other_site = Site.objects.create(name="Тест ЦОД 2", slug="wizard-ci-2")
        manufacturer = Manufacturer.objects.create(name="Wizard Test", slug="wizard-test")
        self.server_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="Test Server", slug="wizard-server",
        )
        self.switch_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="Test Switch", slug="wizard-switch",
        )
        self.server_role = DeviceRole.objects.create(name="Server Test", slug="server")
        self.switch_role = DeviceRole.objects.create(name="Switch Test", slug="switch")
        InterfaceTemplate.objects.create(
            device_type=self.server_type, name="eno1", type="1000base-t",
        )
        self.switch = Device.objects.create(
            name="switch-01", site=self.site, device_type=self.switch_type,
            role=self.switch_role,
        )
        self.switch_port = Interface.objects.create(
            device=self.switch, name="Ethernet1/1", type="1000base-t",
        )
        self.fc_port = Interface.objects.create(
            device=self.switch, name="fc1", type="16gfc-sfpp",
        )
        self.user = User.objects.create_superuser(
            username="wizard_admin", email="wizard@example.invalid", password="local-test-password",
        )
        self.factory = RequestFactory()

    def request(self, user=None):
        request = self.factory.post("/plugins/netbox_server_wizard/add/")
        request.user = user or self.user
        return request

    def new_device_data(self, name="server-01", kind="server", role=None, site=None):
        return {
            "mode": "create", "equipment_kind": kind, "site": site or self.site,
            "name": name, "device_type": self.switch_type if kind == "switch" else self.server_type,
            "role": role or (self.switch_role if kind == "switch" else self.server_role),
            "rack": None, "position": None, "face": "", "serial": "SN123456",
            "status": "planned", "project": None, "new_project": "",
            "cable_status": "planned",
        }

    def existing_data(self, device):
        return {
            "mode": "existing", "equipment_kind": "server", "site": self.site,
            "existing_device": device, "serial": "", "project": None,
            "new_project": "", "cable_status": "planned",
        }


class WizardIntegrationTests(WizardFixture, TestCase):
    def setUp(self):
        self.setup_inventory()

    def test_create_server_and_template_interfaces(self):
        device = save_wizard(self.request(), self.new_device_data(), [], [])
        self.assertEqual(device.serial, "SN123456")
        self.assertEqual(device.role, self.server_role)
        self.assertTrue(Interface.objects.filter(device=device, name="eno1").exists())

    def test_create_switch_as_device(self):
        device = save_wizard(self.request(), self.new_device_data("switch-02", "switch"), [], [])
        self.assertEqual(device.role, self.switch_role)
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    def test_create_switch_and_connect_its_uplink_to_other_switch(self):
        InterfaceTemplate.objects.create(
            device_type=self.switch_type, name="uplink1", type="1000base-t",
        )
        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            new_switch = save_wizard(
                self.request(), self.new_device_data("switch-02", "switch"), [],
                [("uplink1", self.switch_port.pk)],
            )
        self.assertEqual(new_switch.role, self.switch_role)
        self.assertTrue(Interface.objects.filter(device=new_switch, name="uplink1", cable__isnull=False).exists())
        self.assertEqual(Cable.objects.count(), 1)

    def test_fc_wwpn_card_and_cables(self):
        cards = [{
            "name": "Dual FC HBA", "kind": "fc", "serial": "HBA-0102",
            "part_number": "QLE2672", "port_type": "16gfc-sfpp",
            "ports_list": ["fc0", "fc1"],
            "port_wwns_list": ["10:00:00:10:9B:12:34:50", "10:00:00:10:9B:12:34:51"],
        }]
        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            device = save_wizard(
                self.request(), self.new_device_data(), cards,
                [("eno1", self.switch_port.pk), ("fc0", self.fc_port.pk)],
            )
        self.assertEqual(Adapter.objects.filter(device=device).count(), 1)
        self.assertEqual(AdapterPort.objects.filter(adapter__device=device).count(), 2)
        fc0 = Interface.objects.get(device=device, name="fc0")
        self.assertEqual(str(fc0.wwn).upper(), "10:00:00:10:9B:12:34:50")
        self.assertEqual(Cable.objects.count(), 2)
        self.switch_port.refresh_from_db()
        self.assertIsNotNone(self.switch_port.cable_id)

    def test_create_project_and_assignment(self):
        data = self.new_device_data()
        data["new_project"] = "Проект ЦОД"
        device = save_wizard(self.request(), data, [], [])
        self.assertEqual(DeviceProject.objects.get(device=device).project.name, "Проект ЦОД")

    def test_existing_device_can_be_extended(self):
        device = Device.objects.create(name="existing-server", site=self.site,
                                       device_type=self.server_type, role=self.server_role)
        card = [{"name": "Extra Ethernet", "kind": "ethernet", "serial": "N-1",
                 "part_number": "X710", "port_type": "10gbase-sr",
                 "ports_list": ["ens2f0"], "port_wwns_list": [None]}]
        data = self.existing_data(device)
        data["serial"] = "NEW-SN"
        result = save_wizard(self.request(), data, card, [])
        self.assertEqual(result.pk, device.pk)
        self.assertEqual(Device.objects.get(pk=device.pk).serial, "NEW-SN")
        self.assertTrue(Interface.objects.filter(device=device, name="ens2f0").exists())

    def test_fail_closed_if_switch_roles_not_set(self):
        with patch("netbox_server_wizard.views.get_plugin_config", return_value=[]):
            with self.assertRaises(ValidationError):
                save_wizard(self.request(), self.new_device_data(), [],
                            [("eno1", self.switch_port.pk)])
        self.assertFalse(Device.objects.filter(name="server-01").exists())
        self.assertFalse(Cable.objects.exists())

    def test_duplicate_cable_port_rolls_back_everything(self):
        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            with self.assertRaises(ValidationError):
                save_wizard(self.request(), self.new_device_data(), [],
                            [("eno1", self.switch_port.pk), ("eno1", self.switch_port.pk)])
        self.assertFalse(Device.objects.filter(name="server-01").exists())

    def test_cannot_cable_port_on_non_switch_role(self):
        fake_target = Device.objects.create(
            name="not-a-switch", site=self.site, device_type=self.server_type, role=self.server_role,
        )
        fake_port = Interface.objects.get(device=fake_target, name="eno1")
        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            with self.assertRaises(ValidationError):
                validate_switch_target(self.user, fake_port, self.site)

    def test_adapters_and_projects_have_native_changelog(self):
        for model in (Project, DeviceProject, Adapter, AdapterPort):
            self.assertTrue(issubclass(model, ChangeLoggedModel), model)
            self.assertIsNotNone(model._meta.get_field("last_updated"))

    def test_changelog_is_recorded_for_project_and_card_in_http_request(self):
        self.client.force_login(self.user)
        payload = {
            "stage": "save", "equipment_kind": "server", "mode": "create",
            "site": str(self.site.pk), "name": "logged-server",
            "device_type": str(self.server_type.pk), "role": str(self.server_role.pk),
            "serial": "LOG-SN", "status": "planned", "cable_status": "planned",
            "new_project": "Новый проект с аудитом",
            "cards-TOTAL_FORMS": "1", "cards-INITIAL_FORMS": "0",
            "cards-MIN_NUM_FORMS": "0", "cards-MAX_NUM_FORMS": "16",
            "cards-0-name": "Recorded NIC", "cards-0-kind": "ethernet",
            "cards-0-port_type": "1000base-t", "cards-0-port_names": "ens2f0",
            "links-TOTAL_FORMS": "2", "links-INITIAL_FORMS": "0",
            "links-MIN_NUM_FORMS": "0", "links-MAX_NUM_FORMS": "64",
            "links-0-nic": "eno1", "links-0-kind": "ethernet",
            "links-1-nic": "ens2f0", "links-1-kind": "ethernet",
        }
        response = self.client.post("/plugins/netbox_server_wizard/add/", payload)
        self.assertEqual(response.status_code, 302, getattr(response, "content", b"")[:1500])
        project = Project.objects.get(name="Новый проект с аудитом")
        adapter = Adapter.objects.get(name="Recorded NIC")
        for obj in (project, adapter):
            self.assertTrue(ObjectChange.objects.filter(
                changed_object_type=ContentType.objects.get_for_model(type(obj)),
                changed_object_id=obj.pk,
            ).exists(), obj)

    def test_fc_form_wwpn_validation(self):
        form = AdapterForm({
            "name": "HBA", "kind": "fc", "port_type": "16gfc-sfpp",
            "port_names": "fc0, fc1", "port_wwns": "100000109b123450, 100000109b123451",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.cleaned_data["port_wwns_list"]), 2)

    def test_switch_role_is_restricted_on_new_device(self):
        form_data = {
            "equipment_kind": "switch", "mode": "create", "site": str(self.site.pk),
            "name": "bad-switch", "device_type": str(self.switch_type.pk),
            "role": str(self.server_role.pk), "status": "planned", "cable_status": "planned",
        }
        with patch("netbox_server_wizard.forms.get_plugin_config", return_value=["switch"]):
            form = ServerForm(form_data, user=self.user)
            self.assertFalse(form.is_valid())
            self.assertIn("role", form.errors)

    def test_cannot_attach_cable_without_change_permission_on_target_port(self):
        source = Device.objects.create(
            name="source-limited", site=self.site,
            device_type=self.server_type, role=self.server_role,
        )
        limited_user = User.objects.create_user(username="wizard_cable_limited", password="test-pass")

        def grant(name, model, actions, constraints=None):
            perm = ObjectPermission.objects.create(
                name=name, actions=actions, constraints=constraints,
            )
            perm.users.add(limited_user)
            perm.object_types.add(ObjectType.objects.get_for_model(model))

        grant("Права на исходное устройство", Device, ["change"], {"pk": source.pk})
        grant("Просмотр всех устройств", Device, ["view"])
        grant("Просмотр интерфейсов", Interface, ["view"])
        grant("Изменение только исходных интерфейсов", Interface, ["change"],
              {"device_id": source.pk})
        grant("Добавление кабелей", Cable, ["add"])

        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            with self.assertRaises(PermissionDenied):
                save_wizard(
                    self.request(User.objects.get(pk=limited_user.pk)),
                    self.existing_data(source), [], [("eno1", self.switch_port.pk)],
                )
        self.assertFalse(Cable.objects.exists())
        self.switch_port.refresh_from_db()
        self.assertIsNone(self.switch_port.cable_id)

    def test_object_permission_constraints_rollback_new_device(self):
        limited_user = User.objects.create_user(username="wizard_limited", password="test-pass")
        perm = ObjectPermission.objects.create(
            name="Может создавать устройства только в ЦОД 1",
            actions=["add"], constraints={"site_id": self.site.pk},
        )
        perm.users.add(limited_user)
        perm.object_types.add(ObjectType.objects.get_for_model(Device))
        # Объект разрешённой площадки создавать можно, другой — нельзя.
        allowed = self.new_device_data(name="allowed-server")
        result = save_wizard(self.request(User.objects.get(pk=limited_user.pk)), allowed, [], [])
        self.assertTrue(Device.objects.filter(pk=result.pk).exists())
        forbidden = self.new_device_data(name="forbidden-server", site=self.other_site)
        with self.assertRaises(PermissionDenied):
            save_wizard(self.request(User.objects.get(pk=limited_user.pk)), forbidden, [], [])
        self.assertFalse(Device.objects.filter(name="forbidden-server").exists())


class ConcurrentCableTests(WizardFixture, TransactionTestCase):
    """На PostgreSQL второй оператор не может занять тот же кабельный порт."""

    def setUp(self):
        self.setup_inventory()
        self.servers = [
            Device.objects.create(name=f"race-server-{i}", site=self.site,
                                  device_type=self.server_type, role=self.server_role)
            for i in (1, 2)
        ]

    def test_only_one_cable_on_same_switch_port(self):
        if connection.vendor != "postgresql":
            self.skipTest("Нужна PostgreSQL для проверки SELECT FOR UPDATE")
        barrier = Barrier(2)

        def worker(device_pk):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                device = Device.objects.get(pk=device_pk)
                site = Site.objects.get(pk=self.site.pk)
                request = self.request(user)
                barrier.wait(timeout=15)
                save_wizard(request, {
                    "mode": "existing", "site": site,
                    "existing_device": device, "serial": "", "project": None,
                    "new_project": "", "cable_status": "planned",
                }, [], [("eno1", self.switch_port.pk)])
                return "ok"
            except (ValidationError, IntegrityError) as exc:
                return f"rejected: {type(exc).__name__}"
            finally:
                close_old_connections()

        with patch("netbox_server_wizard.views.get_plugin_config", return_value=["switch"]):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, [device.pk for device in self.servers]))
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(Cable.objects.count(), 1)
        self.switch_port.refresh_from_db()
        self.assertIsNotNone(self.switch_port.cable_id)
