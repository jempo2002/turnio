"""Catalogo de servicios del negocio (T4): nombre, duracion, precio y lo que
gana quien lo hace (`pago_profesional`, el pagoBarbero del prototipo).

Desactivar es soft delete: las citas y cobros viejos siguen apuntando al
servicio, y el nombre queda libre para uno nuevo (`nombre_vivo`).
"""
from __future__ import annotations

from mysql.connector import IntegrityError

from app.services.errores import Conflicto, ErrorServicio, NoEncontrado
from app.utils.validation import parse_int, sanitize_text
from database import get_db

PRECIO_MAX = 100_000_000
_DUPLICADO = "Ya existe un servicio con ese nombre."


def _campos(data: dict) -> tuple[str, int, int, int]:
    nombre = sanitize_text(data.get("nombre"), "El nombre del servicio", max_len=120)
    duracion = parse_int(data.get("duracion_min"), "La duración", min_value=5, max_value=720)
    precio = parse_int(data.get("precio"), "El precio", min_value=0, max_value=PRECIO_MAX)
    pago = parse_int(data.get("pago_profesional") or 0, "El pago al profesional", min_value=0)
    if pago > precio:
        raise ValueError("El pago al profesional no puede ser mayor que el precio.")
    return nombre, duracion, precio, pago


def _fila(f: dict) -> dict:
    return {
        "id_servicio": f["id_servicio"],
        "nombre": f["nombre"],
        "duracion_min": int(f["duracion_min"]),
        "precio": int(f["precio"]),
        "pago_profesional": int(f["pago_profesional"]),
    }


def listar_servicios(id_tienda: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_servicio, nombre, duracion_min, precio, pago_profesional FROM servicios "
            "WHERE id_tienda = %s AND estado_activo = 1 ORDER BY nombre",
            (id_tienda,),
        )
        return [_fila(f) for f in cur.fetchall()]
    finally:
        conn.close()


def crear_servicio(id_tienda: int, data: dict) -> int:
    nombre, duracion, precio, pago = _campos(data)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO servicios (id_tienda, nombre, duracion_min, precio, pago_profesional) "
            "VALUES (%s, %s, %s, %s, %s)",
            (id_tienda, nombre, duracion, precio, pago),
        )
        id_servicio = cur.lastrowid
        conn.commit()
        return id_servicio
    except IntegrityError as exc:
        conn.rollback()
        raise Conflicto(_DUPLICADO) from exc
    finally:
        conn.close()


def _servicio_de_tienda(cur, id_tienda: int, id_servicio: int) -> None:
    cur.execute(
        "SELECT 1 FROM servicios WHERE id_servicio = %s AND id_tienda = %s AND estado_activo = 1 FOR UPDATE",
        (id_servicio, id_tienda),
    )
    if not cur.fetchone():
        raise NoEncontrado("Servicio no encontrado.")


def actualizar_servicio(id_tienda: int, id_servicio: int, data: dict) -> None:
    nombre, duracion, precio, pago = _campos(data)
    conn = get_db()
    try:
        cur = conn.cursor()
        _servicio_de_tienda(cur, id_tienda, id_servicio)
        # Un pago propio de algun profesional no puede quedar por encima del
        # precio nuevo (la caja le pagaria mas de lo que cobra el local).
        cur.execute(
            "SELECT 1 FROM profesional_servicios WHERE id_servicio = %s AND pago_profesional > %s LIMIT 1",
            (id_servicio, precio),
        )
        if cur.fetchone():
            raise ErrorServicio("Hay profesionales que ganan más que ese precio por este servicio. Ajusta su pago primero.")
        cur.execute(
            "UPDATE servicios SET nombre = %s, duracion_min = %s, precio = %s, pago_profesional = %s "
            "WHERE id_servicio = %s",
            (nombre, duracion, precio, pago, id_servicio),
        )
        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        raise Conflicto(_DUPLICADO) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desactivar_servicio(id_tienda: int, id_servicio: int) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        _servicio_de_tienda(cur, id_tienda, id_servicio)
        cur.execute("UPDATE servicios SET estado_activo = 0 WHERE id_servicio = %s", (id_servicio,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
