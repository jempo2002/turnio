"""Venta rapida de productos (T5), la de citas.html: carrito por codigo de
barras o tocando la vitrina, cobro en efectivo, transferencia o mixto.

Una venta descuenta el stock de la sede (kardex 'Venta'), suma `vendidos`
(ordena la vitrina) y entra a caja, todo en una transaccion. Los precios
salen del catalogo, nunca del cliente. Anular devuelve todo mientras la caja
de ese dia siga abierta.
"""
from __future__ import annotations

from app.services import caja_service, inventario_service
from app.services.errores import Conflicto, ErrorServicio, NoEncontrado
from app.utils.helpers import ahora_local, hoy_local
from app.utils.validation import parse_int
from database import get_db

MAX_LINEAS = 50


def _carrito(cur, id_tienda: int, items) -> tuple[dict[int, int], dict[int, dict]]:
    """[{id_producto | codigo_barras, cantidad}] -> ({id: cantidad}, {id: producto})."""
    if not isinstance(items, list) or not items:
        raise ValueError("El carrito está vacío.")
    if len(items) > MAX_LINEAS:
        raise ValueError("Demasiados productos en una venta.")
    por_id: dict[int, int] = {}
    por_codigo: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Producto invalido.")
        cantidad = parse_int(item.get("cantidad") or 1, "La cantidad", min_value=1,
                             max_value=inventario_service.CANTIDAD_MAX)
        if item.get("id_producto") not in (None, ""):
            pid = parse_int(item.get("id_producto"), "Producto", min_value=1)
            por_id[pid] = por_id.get(pid, 0) + cantidad
        else:
            codigo = inventario_service.parse_codigo(item.get("codigo_barras"))
            if not codigo:
                raise ValueError("Producto invalido.")
            por_codigo[codigo] = por_codigo.get(codigo, 0) + cantidad

    condiciones, params = [], []
    if por_id:
        condiciones.append(f"id_producto IN ({', '.join(['%s'] * len(por_id))})")
        params += list(por_id)
    if por_codigo:
        condiciones.append(f"codigo_barras IN ({', '.join(['%s'] * len(por_codigo))})")
        params += list(por_codigo)
    cur.execute(
        "SELECT id_producto, codigo_barras, nombre, precio, costo FROM productos "
        f"WHERE id_tienda = %s AND estado_activo = 1 AND ({' OR '.join(condiciones)})",
        (id_tienda, *params),
    )
    productos = {f["id_producto"]: f for f in cur.fetchall()}
    codigos = {f["codigo_barras"]: pid for pid, f in productos.items() if f["codigo_barras"]}
    faltan = [str(pid) for pid in por_id if pid not in productos] + [c for c in por_codigo if c not in codigos]
    if faltan:
        raise NoEncontrado(f"No está en el inventario: {', '.join(faltan)}.")
    consumo = dict(por_id)
    for codigo, cantidad in por_codigo.items():
        consumo[codigos[codigo]] = consumo.get(codigos[codigo], 0) + cantidad
    return consumo, productos


def vender(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        consumo, productos = _carrito(cur, id_tienda, data.get("items"))
        total = sum(int(productos[pid]["precio"]) * n for pid, n in consumo.items())
        if total <= 0:
            raise ErrorServicio("La venta no tiene valor: revisa los precios de los productos.")
        pagos = caja_service.parse_pagos(data, total)
        caja_service.bloquear_dia(cur, id_tienda, id_sede, hoy_local())
        ahora = ahora_local()
        cur.execute(
            "INSERT INTO ventas (id_tienda, id_sede, total, id_usuario_registra, fecha) VALUES (%s, %s, %s, %s, %s)",
            (id_tienda, id_sede, total, id_usuario, ahora),
        )
        id_venta = cur.lastrowid
        inventario_service.descontar(cur, id_tienda, id_sede, id_usuario, consumo,
                                     {pid: p["nombre"] for pid, p in productos.items()}, id_venta)
        for pid in sorted(consumo):
            cur.execute(
                "INSERT INTO venta_productos (id_venta, id_producto, cantidad, precio, costo) "
                "VALUES (%s, %s, %s, %s, %s)",
                (id_venta, pid, consumo[pid], productos[pid]["precio"], productos[pid]["costo"]),
            )
            cur.execute("UPDATE productos SET vendidos = vendidos + %s WHERE id_producto = %s AND id_tienda = %s",
                        (consumo[pid], pid, id_tienda))
        concepto = " + ".join(
            productos[pid]["nombre"] + (f" x{consumo[pid]}" if consumo[pid] > 1 else "") for pid in sorted(consumo)
        )
        caja_service.insertar_movimientos(cur, id_tienda, id_sede, id_usuario, "ingreso", concepto, pagos, ahora,
                                          id_venta=id_venta)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"id_venta": id_venta, "total": total}


def anular(id_tienda: int, id_venta: int, id_usuario: int, sedes_permitidas: list[int] | None) -> None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_sede, DATE(fecha) AS dia FROM ventas WHERE id_venta = %s AND id_tienda = %s",
                    (id_venta, id_tienda))
        venta = cur.fetchone()
        if not venta or (sedes_permitidas is not None and venta["id_sede"] not in sedes_permitidas):
            raise NoEncontrado("Venta no encontrada.")
        caja_service.bloquear_dia(cur, id_tienda, venta["id_sede"], venta["dia"])
        cur.execute("SELECT estado FROM ventas WHERE id_venta = %s AND id_tienda = %s FOR UPDATE", (id_venta, id_tienda))
        if cur.fetchone()["estado"] != "pagada":
            raise Conflicto("Esa venta ya está anulada.")
        cur.execute("SELECT id_producto, cantidad FROM venta_productos WHERE id_venta = %s ORDER BY id_producto",
                    (id_venta,))
        for linea in cur.fetchall():
            antes = inventario_service.bloquear_stock(cur, venta["id_sede"], linea["id_producto"])
            inventario_service.mover(cur, id_tienda, venta["id_sede"], linea["id_producto"], id_usuario, "Anulacion",
                                     linea["cantidad"], antes, antes + linea["cantidad"], "Venta anulada", id_venta)
            cur.execute("UPDATE productos SET vendidos = GREATEST(vendidos - %s, 0) WHERE id_producto = %s "
                        "AND id_tienda = %s", (linea["cantidad"], linea["id_producto"], id_tienda))
        cur.execute("DELETE FROM movimientos_caja WHERE id_venta = %s AND id_tienda = %s", (id_venta, id_tienda))
        cur.execute(
            "UPDATE ventas SET estado = 'anulada', id_usuario_anula = %s, fecha_anulacion = %s "
            "WHERE id_venta = %s AND id_tienda = %s",
            (id_usuario, ahora_local(), id_venta, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
