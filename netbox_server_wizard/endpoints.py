"""Безопасный идентификатор ближайшего окончания первого кабеля."""
import re

ALLOWED_ENDPOINTS = frozenset(("interface", "frontport"))


def encode_endpoint(obj):
    """Публичный ключ окончания, не смешивающий PK разных моделей."""
    kind = obj._meta.model_name
    if kind not in ALLOWED_ENDPOINTS or not obj.pk:
        raise ValueError("Допускаются только сохранённые Interface и FrontPort.")
    return f"{kind}:{obj.pk}"


def parse_endpoint(value):
    """(модель, PK). Числовой PK поддерживается для совместимости с v0.4."""
    if type(value) is int and value > 0:
        return "interface", value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        kind, pk = value
        if kind in ALLOWED_ENDPOINTS and type(pk) is int and pk > 0:
            return kind, pk
        raise ValueError("Некорректное окончание кабеля.")
    if not isinstance(value, str) or not re.fullmatch(r"(interface|frontport):[1-9][0-9]*", value):
        raise ValueError("Некорректное окончание кабеля.")
    kind, pk = value.split(":", 1)
    return kind, int(pk)
