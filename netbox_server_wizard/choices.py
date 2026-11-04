"""Типы физических интерфейсов, поддерживаемые мастером."""

# Все эти значения присутствуют в NetBox 4.5.0 (dcim.choices.InterfaceTypeChoices).
ETHERNET_PORT_TYPES = (
    ("1000base-t", "1 Гбит/с — RJ45"),
    ("10gbase-t", "10 Гбит/с — RJ45"),
    ("10gbase-sr", "10 Гбит/с — SR"),
    ("25gbase-sr", "25 Гбит/с — SR"),
    ("40gbase-sr4", "40 Гбит/с — SR4"),
    ("100gbase-sr4", "100 Гбит/с — SR4"),
)

FC_PORT_TYPES = (
    ("8gfc-sfpp", "8 Гбит/с FC — SFP+"),
    ("16gfc-sfpp", "16 Гбит/с FC — SFP+"),
    ("32gfc-sfp28", "32 Гбит/с FC — SFP28"),
    ("32gfc-sfpp", "32 Гбит/с FC — SFP+"),
    ("64gfc-sfpdd", "64 Гбит/с FC — SFP-DD"),
    ("64gfc-qsfpp", "64 Гбит/с FC — QSFP+"),
)

# В NetBox поддерживается также несколько менее распространённых FC типов.
ALL_FC_TYPES = frozenset((
    "1gfc-sfp", "2gfc-sfp", "4gfc-sfp", "8gfc-sfpp", "16gfc-sfpp",
    "32gfc-sfp28", "32gfc-sfpp", "64gfc-qsfpp", "64gfc-sfpdd",
    "64gfc-sfpp", "128gfc-qsfp28",
))

PORT_TYPE_CHOICES = (("", "Выберите тип порта"),) + ETHERNET_PORT_TYPES + FC_PORT_TYPES


def interface_kind(type_name):
    return "fc" if type_name in ALL_FC_TYPES else "ethernet"


def parse_port_names(text):
    """Разделённый запятыми перечень, не более восьми портов."""
    import re
    names = [name.strip() for name in text.split(",") if name.strip()]
    if not 1 <= len(names) <= 8:
        raise ValueError("Укажите от 1 до 8 портов через запятую.")
    if len(set(names)) != len(names):
        raise ValueError("Имена портов в одной карте не должны повторяться.")
    for name in names:
        if len(name) > 100 or not re.fullmatch(r"[\w./:@+-]+", name, re.UNICODE):
            raise ValueError(f"Некорректное имя интерфейса: {name!r}.")
    return names
