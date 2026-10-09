"""Sedes de un negocio: alta con tope del plan, edicion y soft delete.
Tomado de jemPOS Chef."""
from __future__ import annotations

from mysql.connector import Error as MySQLError, IntegrityError

from app.services import plan_service
from app.utils.helpers import ahora_local, normalize_phone
from app.utils.validation import sanitize_optional_text, sanitize_text
from database import get_db

_NOMBRE_DUPLICADO = "Ya existe una sede activa con ese nombre."
# SIGNAL de los triggers de migrations/2026-10-08_01_base_negocios.sql.
ERRNO_TRIGGER = 1644
_LIMITE_BASE = "El plan no admite más sedes."


# Horario de fabrica de una sede nueva: lunes a sabado de 8 a. m. a 7 p. m.,
# domingo cerrado (dia 0 = lunes ... 6 = domingo).
ABRE, CIERRA = "08:00", "19:00"


class SedeError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _campos(data: dict) -> tuple[str, str | None, str | None]:
    nombre = sanitize_text(data.get("nombre"), "El nombre de la sede", max_len=120)
    direccion = sanitize_optional_text(data.get("direccion"), "La dirección", max_len=200)
    telefono = normalize_phone(data.get("telefono"), max_len=20)
    return nombre, direccion, telefono


def sembrar_horario(cur, id_sede: int, semana=None) -> None:
    """Horario inicial de una sede nueva (misma transaccion que la crea).
    `semana`: 7 tuplas (abierto, abre, cierra) de lunes a domingo, las de
    vertical_service.horario(); sin ella, el de fabrica."""
    if semana is None:
        semana = [(dia < 6, ABRE, CIERRA) for dia in range(7)]
    cur.executemany(
        "INSERT IGNORE INTO horarios_sede (id_sede, dia, abierto, abre, cierra) VALUES (%s, %s, %s, %s, %s)",
        [(id_sede, dia, int(abierto), abre, cierra) for dia, (abierto, abre, cierra) in enumerate(semana)],
    )


def resumen_sedes(id_tienda: int) -> dict:
    """Sedes activas con su numero de usuarios, y lo que cuestan al mes."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT plan_id FROM tiendas WHERE id_tienda = %s", (id_tienda,))
        plan_id = plan_service.normalizar_plan((cur.fetchone() or {}).get("plan_id"))
        cur.execute(
            "SELECT s.id_sede, s.nombre, s.direccion, s.telefono, s.es_principal, "
            "s.costo_montaje, s.montaje_pagado, "
            "(SELECT COUNT(*) FROM usuarios u WHERE u.id_sede = s.id_sede AND u.estado_activo = 1) AS usuarios "
            "FROM sedes s WHERE s.id_tienda = %s AND s.estado = 'Activa' "
            "ORDER BY s.es_principal DESC, s.nombre",
            (id_tienda,),
        )
        sedes = cur.fetchall()
    finally:
        conn.close()
    plan = plan_service.plan_de(plan_id)
    n = len(sedes)
    tope = plan_service.tope_sedes(plan_id)
    return {
        "sedes": sedes,
        "plan_id": plan_id,
        "plan_nombre": plan["nombre"],
        # Lo que suma al mes la proxima sede, si es extra.
        "sede_extra": plan_service.precio_sede_extra(plan_service.sedes_extra(plan_id, n + 1))
        if plan["sede_extra"] else None,
        "precio_volumen": plan_service.PRECIO_SEDE_EXTRA_VOLUMEN,
        "sede_volumen": plan["sedes_incluidas"] + plan_service.SEDES_PRECIO_LLENO + 1,
        "max_sedes": tope,
        "puede_crear": tope is None or n < tope,
        "multisede": plan_service.tiene_funcion(plan_id, "multisede"),
        "costo_montaje": plan_service.costo_montaje_nueva_sede(plan_id, n),
        "montaje_sede_extra": plan_service.COSTO_MONTAJE_SEDE,
        "sede_incluida": not plan_service.sedes_extra(plan_id, n + 1),
        "sedes_incluidas": plan["sedes_incluidas"],
        "sedes_extra": plan_service.sedes_extra(plan_id, n),
        "mensualidad": plan_service.mensualidad(plan_id, n),
    }


def _plan_y_sedes(cur, id_tienda: int) -> tuple[str, int]:
    cur.execute(
        "SELECT t.plan_id, (SELECT COUNT(*) FROM sedes s WHERE s.id_tienda = t.id_tienda "
        "AND s.estado = 'Activa') AS n FROM tiendas t WHERE t.id_tienda = %s",
        (id_tienda,),
    )
    fila = cur.fetchone() or {}
    return plan_service.normalizar_plan(fila.get("plan_id")), int(fila.get("n") or 0)


def crear_sede(id_tienda: int, data: dict) -> int:
    """Lanza ValueError (datos), LimitePlanError (tope) o SedeError.

    Una sede por encima de las incluidas en el plan nace con su montaje
    pendiente (COSTO_MONTAJE_SEDE): el Master lo marca pagado en su panel
    cuando lo recibe. Las incluidas no pagan montaje."""
    nombre, direccion, telefono = _campos(data)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        plan_service.verificar_limite(cur, id_tienda, "sedes")
        montaje = plan_service.costo_montaje_nueva_sede(*_plan_y_sedes(cur, id_tienda))
        cur.execute(
            "INSERT INTO sedes (id_tienda, nombre, direccion, telefono, costo_montaje) "
            "VALUES (%s, %s, %s, %s, %s)",
            (id_tienda, nombre, direccion, telefono, montaje),
        )
        id_sede = cur.lastrowid
        # La sede nueva arranca con el horario de la principal (T9: el de su
        # tipo de negocio o el que el dueno ya ajusto); sin principal, el de
        # fabrica.
        cur.execute(
            "INSERT INTO horarios_sede (id_sede, dia, abierto, abre, cierra, almuerzo_desde, almuerzo_hasta) "
            "SELECT %s, h.dia, h.abierto, h.abre, h.cierra, h.almuerzo_desde, h.almuerzo_hasta "
            "FROM horarios_sede h JOIN sedes s ON s.id_sede = h.id_sede "
            "WHERE s.id_tienda = %s AND s.es_principal = 1 AND s.estado = 'Activa'",
            (id_sede, id_tienda),
        )
        sembrar_horario(cur, id_sede)
        conn.commit()
        return id_sede
    except IntegrityError as exc:
        conn.rollback()
        raise SedeError(_NOMBRE_DUPLICADO, 409) from exc
    except MySQLError as exc:
        conn.rollback()
        if exc.errno == ERRNO_TRIGGER:
            raise SedeError(_LIMITE_BASE, 409) from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def actualizar_sede(id_tienda: int, id_sede: int, data: dict) -> str:
    """Devuelve el nombre ya limpio (la sesion lo muestra si es la sede activa)."""
    nombre, direccion, telefono = _campos(data)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sedes SET nombre = %s, direccion = %s, telefono = %s "
            "WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa'",
            (nombre, direccion, telefono, id_sede, id_tienda),
        )
        # rowcount 0 tambien cuando no cambio nada: confirmar que existe.
        if cur.rowcount == 0:
            cur.execute(
                "SELECT 1 FROM sedes WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa'",
                (id_sede, id_tienda),
            )
            if not cur.fetchone():
                raise SedeError("Sede no encontrada.", 404)
        conn.commit()
        return nombre
    except IntegrityError as exc:
        conn.rollback()
        raise SedeError(_NOMBRE_DUPLICADO, 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def eliminar_sede(id_tienda: int, id_sede: int) -> None:
    """Soft delete. La principal no se elimina, y una sede con usuarios
    activos tampoco: primero se mueven o se desactivan (si no, quedarian
    atados a una sede muerta y sin poder entrar)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT es_principal FROM sedes WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa' FOR UPDATE",
            (id_sede, id_tienda),
        )
        sede = cur.fetchone()
        if not sede:
            raise SedeError("Sede no encontrada.", 404)
        if sede["es_principal"]:
            raise SedeError("La sede principal no se puede eliminar.")
        cur.execute(
            "SELECT COUNT(*) AS n FROM usuarios WHERE id_sede = %s AND estado_activo = 1",
            (id_sede,),
        )
        if cur.fetchone()["n"]:
            raise SedeError("La sede tiene usuarios activos. Muévelos a otra sede o desactívalos primero.", 409)
        cur.execute(
            "UPDATE sedes SET estado = 'Eliminada', fecha_eliminacion = %s WHERE id_sede = %s AND id_tienda = %s",
            (ahora_local(), id_sede, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sede_de_tienda(cur, id_tienda: int, id_sede) -> int:
    """id de una sede activa del negocio, o ValueError."""
    try:
        id_sede = int(id_sede)
    except (TypeError, ValueError) as exc:
        raise ValueError("Elige la sede de la lista.") from exc
    cur.execute(
        "SELECT 1 FROM sedes WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa' LIMIT 1",
        (id_sede, id_tienda),
    )
    if not cur.fetchone():
        raise ValueError("La sede elegida no existe.")
    return id_sede
