"""Datos del local (T4): nombre, tipo de negocio, WhatsApp, enlace de
reservas y logo, y el horario de atencion de cada sede.

La direccion es de cada sede (PUT /api/sedes/<id>).
"""
from __future__ import annotations

import re
from datetime import time, timedelta

from mysql.connector import IntegrityError

from app.services import imagen_service, vertical_service
from app.services.errores import Conflicto
from app.services.master_service import TIPOS_NEGOCIO, _parse_tipo
from app.services.sede_service import ABRE, CIERRA, sede_de_tienda
from app.utils.helpers import normalize_phone
from app.utils.validation import parse_bool, sanitize_text
from database import get_db

DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ── Datos del negocio ───────────────────────────────────────────────

def datos_negocio(id_tienda: int) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre_negocio, slug, tipo_negocio, telefono, nit, id_logo FROM tiendas WHERE id_tienda = %s",
            (id_tienda,),
        )
        fila = cur.fetchone()
    finally:
        conn.close()
    fila["logo_url"] = imagen_service.url(fila.pop("id_logo"))
    fila["tipos_negocio"] = list(TIPOS_NEGOCIO)
    fila["voc"] = vertical_service.vocabulario(fila["tipo_negocio"])
    return fila


def _parse_slug(raw) -> str:
    slug = str(raw or "").strip().lower()
    if not 3 <= len(slug) <= 60 or not _SLUG.match(slug):
        raise ValueError("El enlace debe tener de 3 a 60 letras sin tildes, números o guiones.")
    return slug


def actualizar_negocio(id_tienda: int, data: dict) -> None:
    nombre = sanitize_text(data.get("nombre_negocio"), "El nombre del negocio", max_len=150)
    tipo = _parse_tipo(data.get("tipo_negocio"))
    telefono = normalize_phone(data.get("telefono"), max_len=20)
    campos = {"nombre_negocio": nombre, "tipo_negocio": tipo, "telefono": telefono}
    if data.get("slug") not in (None, ""):
        campos["slug"] = _parse_slug(data["slug"])
    conn = get_db()
    try:
        cur = conn.cursor()
        asignaciones = ", ".join(f"{campo} = %s" for campo in campos)
        cur.execute(f"UPDATE tiendas SET {asignaciones} WHERE id_tienda = %s", [*campos.values(), id_tienda])
        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        raise Conflicto("Ese enlace ya lo usa otro negocio.") from exc
    finally:
        conn.close()


def cambiar_logo(id_tienda: int, datos: bytes | None) -> str | None:
    """Pone el logo (datos) o lo quita (None). Devuelve su URL."""
    tipo = imagen_service.validar(datos) if datos is not None else None
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_logo FROM tiendas WHERE id_tienda = %s FOR UPDATE", (id_tienda,))
        anterior = cur.fetchone()["id_logo"]
        id_logo = imagen_service.guardar(cur, id_tienda, datos, tipo) if datos is not None else None
        cur.execute("UPDATE tiendas SET id_logo = %s WHERE id_tienda = %s", (id_logo, id_tienda))
        imagen_service.borrar(cur, id_tienda, anterior)
        conn.commit()
        return imagen_service.url(id_logo)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Horario de cada sede ────────────────────────────────────────────

def _hhmm(valor) -> str | None:
    """MySQL devuelve TIME como timedelta."""
    if valor is None:
        return None
    minutos = int(valor.total_seconds() // 60) if isinstance(valor, timedelta) else valor.hour * 60 + valor.minute
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def horario(id_tienda: int, id_sede) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        id_sede = sede_de_tienda(cur, id_tienda, id_sede)
        cur.execute(
            "SELECT dia, abierto, abre, cierra, almuerzo_desde, almuerzo_hasta FROM horarios_sede WHERE id_sede = %s",
            (id_sede,),
        )
        filas = {f["dia"]: f for f in cur.fetchall()}
    finally:
        conn.close()
    # Un dia sin fila esta cerrado (ver la migracion 02).
    return [
        {
            "dia": dia,
            "nombre": DIAS[dia],
            "abierto": bool(f and f["abierto"]),
            "abre": _hhmm(f["abre"]) if f else ABRE,
            "cierra": _hhmm(f["cierra"]) if f else CIERRA,
            "almuerzo_desde": _hhmm(f["almuerzo_desde"]) if f else None,
            "almuerzo_hasta": _hhmm(f["almuerzo_hasta"]) if f else None,
        }
        for dia, f in ((d, filas.get(d)) for d in range(7))
    ]


def _parse_hora(raw, etiqueta: str, opcional: bool = False) -> time | None:
    texto = str(raw or "").strip()
    if not texto and opcional:
        return None
    try:
        hora, minuto = texto.split(":")[:2]
        return time(int(hora), int(minuto))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{etiqueta}: revisa la hora (ej. 09:30).") from exc


def _parse_dia(item) -> tuple:
    if not isinstance(item, dict):
        raise ValueError("Revisa el horario: hay un día sin hora de abrir o de cerrar.")
    try:
        dia = int(item.get("dia"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Revisa el horario: hay un día que no existe.") from exc
    if not 0 <= dia <= 6:
        raise ValueError("Revisa el horario: hay un día que no existe.")
    nombre = DIAS[dia]
    abierto = parse_bool(item.get("abierto", False))
    abre = _parse_hora(item.get("abre") or ABRE, nombre)
    cierra = _parse_hora(item.get("cierra") or CIERRA, nombre)
    desde = _parse_hora(item.get("almuerzo_desde"), nombre, opcional=True)
    hasta = _parse_hora(item.get("almuerzo_hasta"), nombre, opcional=True)
    if cierra <= abre:
        raise ValueError(f"{nombre}: la hora de cierre debe ser después de la de apertura.")
    if (desde is None) != (hasta is None):
        raise ValueError(f"{nombre}: el almuerzo necesita hora de inicio y de fin.")
    if desde is not None and not (abre <= desde < hasta <= cierra):
        raise ValueError(f"{nombre}: el almuerzo debe quedar dentro del horario.")
    return dia, int(abierto), abre, cierra, desde, hasta


def guardar_horario(id_tienda: int, id_sede, dias) -> None:
    """Reemplaza los 7 dias de la sede."""
    if not isinstance(dias, list):
        raise ValueError("Revisa el horario: hay un día sin hora de abrir o de cerrar.")
    filas = [_parse_dia(item) for item in dias]
    if sorted(f[0] for f in filas) != list(range(7)):
        raise ValueError("El horario debe traer los 7 días de la semana.")
    conn = get_db()
    try:
        cur = conn.cursor()
        id_sede = sede_de_tienda(cur, id_tienda, id_sede)
        cur.executemany(
            "INSERT INTO horarios_sede (id_sede, dia, abierto, abre, cierra, almuerzo_desde, almuerzo_hasta) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE abierto = VALUES(abierto), "
            "abre = VALUES(abre), cierra = VALUES(cierra), almuerzo_desde = VALUES(almuerzo_desde), "
            "almuerzo_hasta = VALUES(almuerzo_hasta)",
            [(id_sede, *f) for f in filas],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
