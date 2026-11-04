"""Физические интерфейсы и безопасный разбор WWPN/WWN."""
import re

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
ALL_FC_TYPES = frozenset((
    "1gfc-sfp", "2gfc-sfp", "4gfc-sfp", "8gfc-sfpp", "16gfc-sfpp",
    "32gfc-sfp28", "32gfc-sfpp", "64gfc-qsfpp", "64gfc-sfpdd",
    "64gfc-sfpp", "128gfc-qsfp28",
))

# NetBox также поддерживает InfiniBand, SONET, виртуальные интерфейсы и
# беспроводные адаптеры. Их нельзя автоматически считать Ethernet.
_ETHERNET_PREFIXES = (
    "100base-", "1000base-", "2.5gbase-", "5gbase-", "10gbase-",
    "25gbase-", "40gbase-", "50gbase-", "100gbase-", "200gbase-",
    "400gbase-", "800gbase-", "1.6tbase-",
)
PORT_TYPE_CHOICES = (("", "Выберите тип порта"),) + ETHERNET_PORT_TYPES + FC_PORT_TYPES


def interface_kind(type_name):
    """Возвращает fc, ethernet или None для неподдерживаемых типов."""
    if type_name in ALL_FC_TYPES:
        return "fc"
    if type_name and type_name.startswith(_ETHERNET_PREFIXES):
        return "ethernet"
    return None


def parse_port_names(text):
    """Разделённые запятыми имена 1–8 физических портов."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    if not 1 <= len(names) <= 8:
        raise ValueError("Укажите от 1 до 8 портов через запятую.")
    if len(set(names)) != len(names):
        raise ValueError("Имена портов одной карты не должны повторяться.")
    for name in names:
        if len(name) > 64 or not re.fullmatch(r"[\w./:@+-]+", name, re.UNICODE):
            raise ValueError(f"Некорректное имя интерфейса: {name!r}.")
    return names


def parse_wwns(text, port_count):
    """Список из ровно port_count WWPN по порядку портов (пустые допустимы).

    Допустимы 16 hex символов или восемь пар с ':' / '-'. Возвращает
    нормализованные значения AA:BB:... или None для незаполненных портов.
    """
    if not text or not text.strip():
        return [None] * port_count
    values = text.split(",")
    if len(values) != port_count:
        raise ValueError("Количество WWPN должно совпадать с количеством портов карты.")
    result = []
    used = set()
    for value in values:
        value = value.strip()
        if not value:
            result.append(None)
            continue
        normalized = value.replace(":", "").replace("-", "")
        if not re.fullmatch(r"[0-9a-fA-F]{16}", normalized):
            raise ValueError(f"Недопустимый WWPN: {value!r}. Требуется 64-битный шестнадцатеричный идентификатор.")
        normalized = ":".join(normalized[i:i + 2].upper() for i in range(0, 16, 2))
        if normalized in used:
            raise ValueError("WWPN разных портов одной карты не должны повторяться.")
        used.add(normalized)
        result.append(normalized)
    return result
