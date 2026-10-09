"""Inventario de productos (T5): catalogo por negocio, stock por sede y kardex.

Tomado de jemPOS Chef (inventario_service: stock por sede con la fila
bloqueada, kardex que nunca se edita ni se borra, Entrada/Salida/Ajuste) y de
jemPOS (tope de productos por plan, lector de codigo de barras). Turnio vende
por unidades: todo es entero.

El catalogo (nombre, codigo, precios, umbral de stock bajo) es del negocio;
el stock es de cada sede (stock_sedes). El Basico topa en 150 productos
activos (plan_service). Desactivar es soft delete: el codigo queda libre.

Las funciones con `cur` trabajan dentro de la transaccion del llamador y no
hacen commit: una venta descuenta el stock y entra a caja junta, o nada.
"""
from __future__ import annotations

import re

from mysql.connector import IntegrityError

from app.services import plan_service
from app.services.errores import Conflicto, NoEncontrado
from app.utils.validation import parse_int, sanitize_optional_text, sanitize_text
from database import get_db

PRECIO_MAX = 100_000_000
CANTIDAD_MAX = 100_000
TIPOS_MOVIMIENTO = ("Entrada", "Salida", "Ajuste")
MAX_KARDEX = 100
_CODIGO = re.compile(r"^[0-9A-Za-z\-]{3,64}$")
_DUPLICADO = "Ya hay un producto con ese código de barras."


def parse_codigo(raw) -> str | None:
    codigo = str(raw or "").strip()
    if not codigo:
        return None
    if not _CODIGO.match(codigo):
        raise ValueError("El código de barras solo lleva números o letras (de 3 a 64).")
    return codigo


def _campos(data: dict) -> dict:
    costo = parse_int(data.get("costo") or 0, "El costo", min_value=0, max_value=PRECIO_MAX)
    precio = parse_int(data.get("precio"), "El precio de venta", min_value=0, max_value=PRECIO_MAX)
    emoji = str(data.get("emoji") or "").strip()
    if len(emoji) > 16:
        raise ValueError("El ícono es muy largo.")
    return {
        "nombre": sanitize_text(data.get("nombre"), "El nombre del producto", max_len=120),
        "codigo_barras": parse_codigo(data.get("codigo_barras")),
        "emoji": emoji or None,
        "costo": costo,
        "precio": precio,
        "stock_minimo": parse_int(data.get("stock_minimo") or 0, "El stock mínimo", min_value=0,
                                  max_value=CANTIDAD_MAX),
    }


def _fila(f: dict, ver_costo: bool) -> dict:
    stock = int(f["stock"] or 0)
    minimo = int(f["stock_minimo"])
    producto = {
        "id_producto": f["id_producto"],
        "codigo_barras": f["codigo_barras"],
        "emoji": f["emoji"],
        "nombre": f["nombre"],
        "precio": int(f["precio"]),
        "stock": stock,
        "stock_minimo": minimo,
        "stock_bajo": minimo > 0 and stock <= minimo,
        "vendidos": int(f["vendidos"]),
    }
    if ver_costo:
        producto["costo"] = int(f["costo"])
    return producto


_SELECT = (
    "SELECT p.id_producto, p.codigo_barras, p.emoji, p.nombre, p.costo, p.precio, p.stock_minimo, p.vendidos, "
    "ss.stock FROM productos p LEFT JOIN stock_sedes ss ON ss.id_producto = p.id_producto AND ss.id_sede = %s "
    "WHERE p.id_tienda = %s AND p.estado_activo = 1"
)


def listar(id_tienda: int, id_sede: int, q: str | None = None, ver_costo: bool = False,
           solo_bajos: bool = False) -> list[dict]:
    """Productos con el stock de la sede: los mas vendidos primero (la
    vitrina de la venta rapida). `q` busca por nombre o codigo."""
    sql = _SELECT
    params: list = [id_sede, id_tienda]
    q = str(q or "").strip()[:60]
    if q:
        sql += " AND (p.nombre LIKE %s OR p.codigo_barras = %s)"
        params += [f"%{q}%", q]
    if solo_bajos:
        sql += " AND p.stock_minimo > 0 AND COALESCE(ss.stock, 0) <= p.stock_minimo"
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql + " ORDER BY p.vendidos DESC, p.nombre", params)
        return [_fila(f, ver_costo) for f in cur.fetchall()]
    finally:
        conn.close()


def por_codigo(id_tienda: int, id_sede: int, codigo: str, ver_costo: bool = False) -> dict:
    """El producto del codigo leido por el lector (camara o pistola)."""
    codigo = parse_codigo(codigo)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(_SELECT + " AND p.codigo_barras = %s", (id_sede, id_tienda, codigo))
        fila = cur.fetchone()
    finally:
        conn.close()
    if not fila:
        raise NoEncontrado(f"El código {codigo} no está en el inventario.")
    return _fila(fila, ver_costo)


# ── Stock y kardex (dentro de la transaccion del llamador) ──────────

def bloquear_stock(cur, id_sede: int, id_producto: int) -> int:
    """Stock de la sede con la fila bloqueada hasta el commit. Si el producto
    nunca tuvo stock en la sede, crea la fila en 0 (ON DUPLICATE KEY toma el
    candado exclusivo de una vez, sin el cruce S -> X de INSERT IGNORE)."""
    cur.execute(
        "INSERT INTO stock_sedes (id_sede, id_producto, stock) VALUES (%s, %s, 0) "
        "ON DUPLICATE KEY UPDATE stock = stock",
        (id_sede, id_producto),
    )
    cur.execute("SELECT stock FROM stock_sedes WHERE id_sede = %s AND id_producto = %s FOR UPDATE",
                (id_sede, id_producto))
    return int(cur.fetchone()["stock"])


def mover(cur, id_tienda: int, id_sede: int, id_producto: int, id_usuario: int, tipo: str, cantidad: int,
          antes: int, despues: int, motivo: str | None, id_venta: int | None = None) -> None:
    cur.execute("UPDATE stock_sedes SET stock = %s WHERE id_sede = %s AND id_producto = %s",
                (despues, id_sede, id_producto))
    cur.execute(
        "INSERT INTO movimientos_inventario (id_tienda, id_sede, id_producto, id_venta, id_usuario, tipo, cantidad, "
        "stock_anterior, stock_posterior, motivo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (id_tienda, id_sede, id_producto, id_venta, id_usuario, tipo, cantidad, antes, despues,
         (motivo or "")[:255] or None),
    )


def descontar(cur, id_tienda: int, id_sede: int, id_usuario: int, consumo: dict[int, int], nombres: dict[int, str],
              id_venta: int) -> None:
    """Saca {id_producto: cantidad} del stock de la sede por una venta. Revisa
    todo antes de tocar nada; bloquea en orden de id (dos ventas con los
    mismos productos no se cruzan en un deadlock)."""
    stock = {pid: bloquear_stock(cur, id_sede, pid) for pid in sorted(consumo)}
    faltan = [pid for pid in sorted(consumo) if stock[pid] < consumo[pid]]
    if faltan:
        detalle = "; ".join(f"{nombres[pid]} (quedan {stock[pid]})" for pid in faltan)
        raise Conflicto(f"No hay suficientes unidades: {detalle}.")
    for pid in sorted(consumo):
        mover(cur, id_tienda, id_sede, pid, id_usuario, "Venta", consumo[pid], stock[pid],
              stock[pid] - consumo[pid], None, id_venta)


# ── Catalogo ───────────────────────────────────────────────────────

def crear(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> int:
    """Producto nuevo con las unidades que entran a la sede (`stock`).
    LimitePlanError si pasa el tope del plan."""
    campos = _campos(data)
    unidades = parse_int(data.get("stock") or 0, "Las unidades", min_value=0, max_value=CANTIDAD_MAX)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        plan_service.verificar_limite(cur, id_tienda, "productos")
        cur.execute(
            "INSERT INTO productos (id_tienda, codigo_barras, emoji, nombre, costo, precio, stock_minimo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, campos["codigo_barras"], campos["emoji"], campos["nombre"], campos["costo"],
             campos["precio"], campos["stock_minimo"]),
        )
        id_producto = cur.lastrowid
        bloquear_stock(cur, id_sede, id_producto)
        if unidades:
            mover(cur, id_tienda, id_sede, id_producto, id_usuario, "Entrada", unidades, 0, unidades, "Producto nuevo")
        conn.commit()
        return id_producto
    except IntegrityError as exc:
        conn.rollback()
        raise Conflicto(_DUPLICADO) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _producto_de_tienda(cur, id_tienda: int, id_producto: int) -> dict:
    cur.execute(
        "SELECT id_producto, nombre FROM productos WHERE id_producto = %s AND id_tienda = %s AND estado_activo = 1",
        (id_producto, id_tienda),
    )
    producto = cur.fetchone()
    if not producto:
        raise NoEncontrado("Producto no encontrado.")
    return producto


def actualizar(id_tienda: int, id_producto: int, data: dict) -> None:
    """Datos del producto. El stock no se cambia aqui: va por movimiento."""
    campos = _campos(data)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        _producto_de_tienda(cur, id_tienda, id_producto)
        cur.execute(
            "UPDATE productos SET codigo_barras = %s, emoji = %s, nombre = %s, costo = %s, precio = %s, "
            "stock_minimo = %s WHERE id_producto = %s AND id_tienda = %s",
            (campos["codigo_barras"], campos["emoji"], campos["nombre"], campos["costo"], campos["precio"],
             campos["stock_minimo"], id_producto, id_tienda),
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


def desactivar(id_tienda: int, id_producto: int) -> None:
    """Sale del inventario y de la venta rapida. Las ventas ya hechas no cambian."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        _producto_de_tienda(cur, id_tienda, id_producto)
        cur.execute("UPDATE productos SET estado_activo = 0 WHERE id_producto = %s AND id_tienda = %s",
                    (id_producto, id_tienda))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def registrar_movimiento(id_tienda: int, id_sede: int, id_usuario: int, id_producto: int, data: dict) -> int:
    """Entrada (compra), Salida (uso interno, dano) o Ajuste (conteo fisico:
    `cantidad` es el stock contado). Devuelve el stock nuevo."""
    tipo = str(data.get("tipo") or "")
    if tipo not in TIPOS_MOVIMIENTO:
        raise ValueError("Tipo de movimiento invalido.")
    cantidad = parse_int(data.get("cantidad"), "La cantidad", min_value=0, max_value=CANTIDAD_MAX)
    if tipo != "Ajuste" and cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero.")
    motivo = sanitize_optional_text(data.get("motivo"), "El motivo", max_len=200)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        _producto_de_tienda(cur, id_tienda, id_producto)
        antes = bloquear_stock(cur, id_sede, id_producto)
        if tipo == "Entrada":
            despues = antes + cantidad
        elif tipo == "Salida":
            if cantidad > antes:
                raise Conflicto(f"Solo hay {antes} en esta sede.")
            despues = antes - cantidad
        else:
            despues = cantidad
            cantidad = abs(despues - antes)
        mover(cur, id_tienda, id_sede, id_producto, id_usuario, tipo, cantidad, antes, despues, motivo or tipo)
        conn.commit()
        return despues
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def trasladar(id_tienda: int, id_usuario: int, id_producto: int, desde: int, hacia: int, cantidad) -> None:
    """Pasa unidades de una sede a otra (Multisede): una Salida y una Entrada
    de tipo Traslado en el kardex, juntas o ninguna."""
    cantidad = parse_int(cantidad, "La cantidad", min_value=1, max_value=CANTIDAD_MAX)
    if desde == hacia:
        raise ValueError("Elige dos sedes distintas.")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        producto = _producto_de_tienda(cur, id_tienda, id_producto)
        cur.execute(
            "SELECT id_sede, nombre FROM sedes WHERE id_tienda = %s AND estado = 'Activa' AND id_sede IN (%s, %s)",
            (id_tienda, desde, hacia),
        )
        nombres = {f["id_sede"]: f["nombre"] for f in cur.fetchall()}
        if len(nombres) != 2:
            raise NoEncontrado("Sede no encontrada.")
        stock = {s: bloquear_stock(cur, s, id_producto) for s in sorted((desde, hacia))}
        if stock[desde] < cantidad:
            raise Conflicto(f"En {nombres[desde]} solo hay {stock[desde]} de {producto['nombre']}.")
        mover(cur, id_tienda, desde, id_producto, id_usuario, "Traslado", cantidad, stock[desde],
              stock[desde] - cantidad, f"Hacia {nombres[hacia]}")
        mover(cur, id_tienda, hacia, id_producto, id_usuario, "Traslado", cantidad, stock[hacia],
              stock[hacia] + cantidad, f"Desde {nombres[desde]}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def kardex(id_tienda: int, id_sede: int, id_producto: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        _producto_de_tienda(cur, id_tienda, id_producto)
        cur.execute(
            "SELECT k.tipo, k.cantidad, k.stock_anterior, k.stock_posterior, k.motivo, k.fecha, k.id_venta, "
            "u.nombre_completo AS usuario FROM movimientos_inventario k "
            "LEFT JOIN usuarios u ON u.id_usuario = k.id_usuario "
            "WHERE k.id_producto = %s AND k.id_sede = %s ORDER BY k.id_movimiento DESC LIMIT %s",
            (id_producto, id_sede, MAX_KARDEX),
        )
        filas = cur.fetchall()
    finally:
        conn.close()
    for f in filas:
        f["fecha"] = f["fecha"].strftime("%Y-%m-%d %H:%M")
    return filas
