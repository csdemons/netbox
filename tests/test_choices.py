"""Быстрые тесты парсера портов; работают без установленного NetBox."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "netbox_server_wizard" / "choices.py"
spec = importlib.util.spec_from_file_location("wizard_choices", MODULE_PATH)
choices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(choices)


class PortParserTests(unittest.TestCase):
    def test_two_ports(self):
        self.assertEqual(choices.parse_port_names("ens2f0, ens2f1"), ["ens2f0", "ens2f1"])

    def test_fibre_channel(self):
        self.assertEqual(choices.interface_kind("16gfc-sfpp"), "fc")
        self.assertEqual(choices.interface_kind("10gbase-sr"), "ethernet")

    def test_duplicate(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names("fc0, fc0")

    def test_max_ports(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names(",".join(f"e{i}" for i in range(9)))

    def test_invalid_name(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names("bad name")


if __name__ == "__main__":
    unittest.main()
