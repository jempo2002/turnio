"""Comisiones y liquidacion por profesional (T5, funcion 'comisiones' del Pro).

Cada cobro de cita ya guarda lo que gana quien atendio (movimientos_caja.
pago_profesional, ver caja_service.cobrar_cita). Liquidar es pagarle todo lo
pendiente hasta una fecha: los cobros quedan marcados con la liquidacion (no
se pagan dos veces) y el pago sale de la caja de hoy como una salida.

El desglose del dia por profesional (caja del dia) es de todos los planes;
el acumulado entre fechas y la liquidacion son del Pro.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services import caja_service
from app.services.errores import Conflicto, NoEncontrado
from app.utils.helpers import ahora_local, hoy_local
from app.utils.validation import parse_int
from database import get_db


def pendientes(id_tienda: int, id_profesional: int | None = None) -> list[dict]:
    """Lo que se le debe a cada profesional: cobros aun sin liquidar."""
    sql = (
        "SELECT m.id_profesional, u.nombre_completo, COUNT(*) AS cobros, SUM(m.pago_profesional) AS total, "
        "MIN(DATE(m.fecha)) AS desde FROM movimientos_caja m JOIN usuarios u ON u.id_usuario = m.id_profesional "
        "WHERE m.id_tienda = %s AND m.tipo = 'ingreso' AND m.id_liquidacion IS NULL AND m.pago_profesional > 0"
    )
    params: list = [id_tienda]
    if id_profesional:
        sql += " AND m.id_profesional = %s"
        params.append(id_profesional)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql + " GROUP BY m.id_profesional, u.nombre_completo ORDER BY u.nombre_completo", params)
        filas = cur.fetchall()
    finally:
        conn.close()
    return [{"id_profesional": f["id_profesional"], "nombre": f["nombre_completo"], "cobros": int(f["cobros"]),
             "total": int(f["total"]), "desde": f["desde"].isoformat()} for f in filas]


def periodo(id_tienda: int, desde: date, hasta: date, id_profesional: int | None = None) -> list[dict]:
    """Citas cobradas, facturado y ganado por profesional entre dos fechas
    (todas las sedes)."""
    if desde > hasta:
        raise ValueError("La fecha inicial va antes de la final.")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        return caja_service.desglose_profesionales(cur, id_tienda, None, desde, hasta, id_profesional)
    finally:
        conn.close()


def liquidar(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> dict:
    """Paga al profesional lo pendiente hasta `hasta` (hoy por defecto). La
    plata sale de la caja de hoy de la sede de la sesion."""
    id_profesional = parse_int(data.get("id_profesional"), "Profesional", min_value=1)
    hasta = caja_service.parse_fecha(data.get("hasta"), "La fecha final")
    metodo = caja_service.parse_metodo(data.get("metodo") or "efectivo")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre_completo FROM usuarios WHERE id_usuario = %s AND id_tienda = %s AND rol <> 'Master'",
            (id_profesional, id_tienda),
        )
        profesional = cur.fetchone()
        if not profesional:
            raise NoEncontrado("Profesional no encontrado.")
        caja_service.bloquear_dia(cur, id_tienda, id_sede, hoy_local())
        cur.execute(
            "SELECT id_movimiento, pago_profesional FROM movimientos_caja "
            "WHERE id_tienda = %s AND id_profesional = %s AND tipo = 'ingreso' AND id_liquidacion IS NULL "
            "AND pago_profesional > 0 AND fecha < %s FOR UPDATE",
            (id_tienda, id_profesional, hasta + timedelta(days=1)),
        )
        cobros = cur.fetchall()
        if not cobros:
            raise Conflicto(f"{profesional['nombre_completo']} no tiene comisiones pendientes hasta esa fecha.")
        total = sum(int(c["pago_profesional"]) for c in cobros)
        ahora = ahora_local()
        cur.execute(
            "INSERT INTO liquidaciones (id_tienda, id_profesional, hasta, cobros, total, metodo, id_usuario_registra, "
            "fecha) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, id_profesional, hasta, len(cobros), total, metodo, id_usuario, ahora),
        )
        id_liquidacion = cur.lastrowid
        marcas = ", ".join(["%s"] * len(cobros))
        cur.execute(
            f"UPDATE movimientos_caja SET id_liquidacion = %s WHERE id_tienda = %s AND id_movimiento IN ({marcas})",
            (id_liquidacion, id_tienda, *[c["id_movimiento"] for c in cobros]),
        )
        caja_service.insertar_movimientos(
            cur, id_tienda, id_sede, id_usuario, "salida", f"Pago a {profesional['nombre_completo']}",
            [(metodo, total)], ahora, id_profesional=id_profesional, id_liquidacion=id_liquidacion,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"id_liquidacion": id_liquidacion, "cobros": len(cobros), "total": total, "hasta": hasta.isoformat()}


def historial(id_tienda: int, id_profesional: int | None = None, limite: int = 50) -> list[dict]:
    sql = (
        "SELECT l.id_liquidacion, l.id_profesional, u.nombre_completo, l.hasta, l.cobros, l.total, l.metodo, l.fecha "
        "FROM liquidaciones l LEFT JOIN usuarios u ON u.id_usuario = l.id_profesional WHERE l.id_tienda = %s"
    )
    params: list = [id_tienda]
    if id_profesional:
        sql += " AND l.id_profesional = %s"
        params.append(id_profesional)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql + " ORDER BY l.id_liquidacion DESC LIMIT %s", (*params, limite))
        filas = cur.fetchall()
    finally:
        conn.close()
    return [{"id_liquidacion": f["id_liquidacion"], "id_profesional": f["id_profesional"],
             "nombre": f["nombre_completo"], "hasta": f["hasta"].isoformat(), "cobros": int(f["cobros"]),
             "total": int(f["total"]), "metodo": f["metodo"], "fecha": f["fecha"].strftime("%Y-%m-%d %H:%M")}
            for f in filas]
