"""Автономные тесты типов портов и WWPN: без PostgreSQL и NetBox."""
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

    def test_no_false_ethernet(self):
        for type_name in ["infiniband-hdr", "sonet-oc48", "virtual", "lag", "bridge", "unknown"]:
            self.assertIsNone(choices.interface_kind(type_name), type_name)

    def test_duplicate(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names("fc0, fc0")

    def test_max_ports(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names(",".join(f"e{i}" for i in range(9)))

    def test_invalid_name(self):
        with self.assertRaises(ValueError):
            choices.parse_port_names("bad name")

    def test_wwpn_normalization(self):
        self.assertEqual(
            choices.parse_wwns("100000109b123450, 10:00:00:10:9b:12:34:51", 2),
            ["10:00:00:10:9B:12:34:50", "10:00:00:10:9B:12:34:51"],
        )

    def test_wwpn_optional(self):
        self.assertEqual(choices.parse_wwns("", 2), [None, None])
        self.assertEqual(choices.parse_wwns("10:00:00:10:9B:12:34:50,", 2),
                         ["10:00:00:10:9B:12:34:50", None])

    def test_wwpn_invalid_and_duplicates(self):
        for text, count in [("123", 1), ("not-a-wwn", 1), ("abcd,def", 3),
                            ("100000109b123450, 10:00:00:10:9B:12:34:50", 2)]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                choices.parse_wwns(text, count)


if __name__ == "__main__":
    unittest.main()
