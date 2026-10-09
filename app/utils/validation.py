from __future__ import annotations

import math

from markupsafe import escape

_ARTICULOS = ("El ", "La ", "Los ", "Las ", "Tu ")
# Campos que se eligen de una lista (llegan como id): "Elige la sede de la lista".
_ELEGIDOS = {"Profesional": "el profesional", "Sede": "la sede", "Servicio": "el servicio", "Producto": "el producto"}


def _campo(field_label: str) -> str:
    """"El precio" -> "el precio"; "Sede" -> "el campo «Sede»". Los mensajes
    salen tal cual en pantalla (docs/ux-avisos.md): dicen qué arreglar."""
    if field_label in _ELEGIDOS:
        return _ELEGIDOS[field_label]
    if field_label.startswith(_ARTICULOS):
        return field_label[0].lower() + field_label[1:]
    return f"el campo «{field_label}»"


def _num(valor) -> str:
    """1000000 -> "1.000.000", como se escribe en Colombia."""
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return str(valor).replace(".", ",")


def sanitize_text(
    raw_value: str | None,
    field_label: str,
    *,
    min_len: int = 1,
    max_len: int = 150,
    allow_empty: bool = False,
) -> str:
    value = str(raw_value or "").strip()
    if not value:
        if allow_empty:
            return ""
        raise ValueError(f"Escribe {_campo(field_label)}.")
    if len(value) < min_len:
        raise ValueError(f"Revisa {_campo(field_label)}: usa al menos {min_len} caracteres.")
    if len(value) > max_len:
        raise ValueError(f"Acorta {_campo(field_label)}: máximo {max_len} caracteres.")
    return str(escape(value))


def sanitize_optional_text(
    raw_value: str | None,
    field_label: str,
    *,
    max_len: int = 255,
) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    if len(value) > max_len:
        raise ValueError(f"Acorta {_campo(field_label)}: máximo {max_len} caracteres.")
    return str(escape(value))


def parse_int(
    raw_value,
    field_label: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    allow_zero: bool = True,
) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        if field_label in _ELEGIDOS:
            raise ValueError(f"Elige {_campo(field_label)} de la lista.") from exc
        raise ValueError(f"Revisa {_campo(field_label)}: escribe solo números.") from exc
    if not allow_zero and value == 0:
        if field_label in _ELEGIDOS:
            raise ValueError(f"Elige {_campo(field_label)} de la lista.")
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser cero.")
    if min_value is not None and value < min_value:
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser menor que {_num(min_value)}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser mayor que {_num(max_value)}.")
    return value


def parse_float(
    raw_value,
    field_label: str,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    allow_zero: bool = True,
) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Revisa {_campo(field_label)}: escribe solo números.") from exc
    # float() acepta "nan" e "inf": NaN pasaba cualquier comparacion de rango.
    if not math.isfinite(value):
        raise ValueError(f"Revisa {_campo(field_label)}: escribe solo números.")
    if not allow_zero and value == 0:
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser cero.")
    if min_value is not None and value < min_value:
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser menor que {_num(min_value)}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"Revisa {_campo(field_label)}: no puede ser mayor que {_num(max_value)}.")
    return value


def parse_bool(raw_value) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return raw_value != 0
    if isinstance(raw_value, str):
        value = raw_value.strip().lower()
        if value in {"true", "1", "si", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError("Ese valor no es válido: elige sí o no.")
