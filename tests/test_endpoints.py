"""Автономные тесты типизированных окончаний первого кабеля."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "netbox_server_wizard" / "endpoints.py"
spec = importlib.util.spec_from_file_location("wizard_endpoints", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EndpointTest(unittest.TestCase):
    def test_interface_and_front_port_have_distinct_namespaces(self):
        self.assertEqual(module.parse_endpoint("interface:25"), ("interface", 25))
        self.assertEqual(module.parse_endpoint("frontport:25"), ("frontport", 25))
        self.assertNotEqual(module.parse_endpoint("interface:25"), module.parse_endpoint("frontport:25"))

    def test_backwards_compatible_integer_interface(self):
        self.assertEqual(module.parse_endpoint(25), ("interface", 25))

    def test_invalid_values_rejected(self):
        for value in ("25", "frontport:0", "frontport:-1", "rearport:1", "interface:1;drop", "frontport:001", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.parse_endpoint(value)

    def test_only_known_saved_models_can_be_encoded(self):
        class Meta:
            model_name = "frontport"
        class Obj:
            pk = 21
            _meta = Meta()
        self.assertEqual(module.encode_endpoint(Obj()), "frontport:21")
        Obj._meta.model_name = "rearport"
        with self.assertRaises(ValueError):
            module.encode_endpoint(Obj())


if __name__ == "__main__":
    unittest.main()
