"""Caja del dia por sede (T5): cobro de citas, gastos, base y cierre con arqueo.

Tomado de jemPOS Chef (caja_service: arqueo con esperado, contado y
diferencia; pago mixto; gastos que bajan el efectivo esperado) y adaptado a la
caja del prototipo (caja.html), que no se abre: cada sede tiene una caja por
dia (cajas_dia) que nace sola con el primer movimiento. La base se puede
poner en cualquier momento antes del cierre.

Movimientos (movimientos_caja), todos en pesos enteros:
  ingreso + id_cita         cobro de una cita, con lo que gana el profesional
                            (pago_profesional) en la primera parte del pago.
  ingreso + id_venta        venta rapida de productos (venta_service).
  salida                    gasto del local.
  salida + id_liquidacion   pago de comisiones a un profesional (comisiones_service).
Un pago mixto son dos filas, una por metodo: los totales por metodo salen solos.

Toda escritura bloquea primero la fila del dia de la sede (bloquear_dia): un
dia cerrado no recibe movimientos, y el cierre no puede cruzarse con un cobro.
Orden de bloqueo en todo el modulo: dia -> sede (agenda) -> cita -> stock (en
orden de id). La agenda (T6) nunca bloquea el dia: no hay ciclos.
"""
from __future__ import annotations

from datetime import date, timedelta

from mysql.connector import IntegrityError

from app.services import agenda_service
from app.services.errores import Conflicto, ErrorServicio, NoEncontrado
from app.utils.helpers import ahora_local, hoy_local
from app.utils.validation import parse_int, sanitize_optional_text, sanitize_text
from database import get_db

METODOS = ("efectivo", "transferencia")
MONTO_MAX = 100_000_000
MAX_MOVIMIENTOS = 300
_CERRADA = "La caja de ese día ya se cerró. Pide al Admin que la reabra."


# ── Utilidades compartidas con venta_service y comisiones_service ────

def parse_fecha(raw, campo: str = "La fecha") -> date:
    """YYYY-MM-DD; vacio = hoy. No acepta dias futuros."""
    if not raw:
        return hoy_local()
    try:
        fecha = date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"{campo} no es valida (usa AAAA-MM-DD).") from exc
    if fecha > hoy_local():
        raise ValueError(f"{campo} no puede ser futura.")
    return fecha


def parse_metodo(raw) -> str:
    metodo = str(raw or "").strip().lower()
    if metodo not in METODOS:
        raise ValueError("Elige efectivo o transferencia.")
    return metodo


def parse_pagos(data: dict, total: int) -> list[tuple[str, int]]:
    """Como se paga `total`: {"metodo": "efectivo"} o, en pago mixto,
    {"pagos": [{"metodo": "efectivo", "monto": 10000}, {"metodo":
    "transferencia", "monto": 15000}]}. Las partes deben sumar el total."""
    pagos = data.get("pagos")
    if not pagos:
        return [(parse_metodo(data.get("metodo") or "efectivo"), total)]
    if not isinstance(pagos, list) or len(pagos) > len(METODOS):
        raise ValueError("Pago invalido.")
    partes: dict[str, int] = {}
    for p in pagos:
        if not isinstance(p, dict):
            raise ValueError("Pago invalido.")
        metodo = parse_metodo(p.get("metodo"))
        partes[metodo] = partes.get(metodo, 0) + parse_int(
            p.get("monto"), "El monto del pago", min_value=1, max_value=MONTO_MAX)
    if sum(partes.values()) != total:
        raise ValueError(f"Efectivo + transferencia deben sumar ${total:,}.".replace(",", "."))
    return [(m, partes[m]) for m in METODOS if m in partes]


def bloquear_dia(cur, id_tienda: int, id_sede: int, fecha: date, abierta: bool = True) -> dict:
    """Fila de la caja de la sede ese dia, bloqueada hasta el commit del
    llamador. La crea si no existe (ON DUPLICATE KEY toma el candado
    exclusivo de una vez: con INSERT IGNORE + FOR UPDATE dos cobros
    simultaneos se trababan). Con `abierta`, lanza Conflicto si ya cerro."""
    cur.execute(
        "INSERT INTO cajas_dia (id_sede, fecha, id_tienda) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE id_sede = id_sede",
        (id_sede, fecha, id_tienda),
    )
    cur.execute(
        "SELECT id_sede, fecha, id_tienda, estado, base FROM cajas_dia WHERE id_sede = %s AND fecha = %s FOR UPDATE",
        (id_sede, fecha),
    )
    dia = cur.fetchone()
    if dia["id_tienda"] != id_tienda:  # no deberia pasar: la sede ya se valido
        raise NoEncontrado("Sede no encontrada.")
    if abierta and dia["estado"] == "cerrada":
        raise Conflicto(_CERRADA)
    return dia


def insertar_movimientos(cur, id_tienda: int, id_sede: int, id_usuario: int, tipo: str, concepto: str,
                         pagos: list[tuple[str, int]], fecha, **enlaces) -> None:
    """Una fila por metodo. `enlaces`: id_cita, id_venta, id_profesional,
    id_liquidacion y pago_profesional (este solo va en la primera fila)."""
    pago_profesional = enlaces.pop("pago_profesional", None)
    for i, (metodo, monto) in enumerate(pagos):
        cur.execute(
            "INSERT INTO movimientos_caja (id_tienda, id_sede, tipo, concepto, monto, metodo, id_profesional, "
            "id_cita, id_venta, pago_profesional, id_liquidacion, id_usuario_registra, fecha) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, id_sede, tipo, concepto[:200], monto, metodo, enlaces.get("id_profesional"),
             enlaces.get("id_cita"), enlaces.get("id_venta"), pago_profesional if i == 0 else None,
             enlaces.get("id_liquidacion"), id_usuario, fecha),
        )


def sede_de_tienda(cur, id_tienda: int, id_sede) -> int:
    id_sede = parse_int(id_sede, "Sede", min_value=1)
    cur.execute("SELECT 1 FROM sedes WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa'", (id_sede, id_tienda))
    if not cur.fetchone():
        raise NoEncontrado("Sede no encontrada.")
    return id_sede


def _rango(desde: date, hasta: date) -> tuple:
    return desde, hasta + timedelta(days=1)


# ── Resumen del dia ────────────────────────────────────────────────

def _totales(cur, id_tienda: int, sedes: list[int], desde: date, hasta: date) -> dict:
    marcas = ", ".join(["%s"] * len(sedes))
    cur.execute(
        "SELECT "
        "COALESCE(SUM(IF(tipo = 'ingreso', monto, 0)), 0) AS ingresos, "
        "COALESCE(SUM(IF(tipo = 'salida', monto, 0)), 0) AS salidas, "
        "COALESCE(SUM(IF(tipo = 'ingreso' AND id_cita IS NOT NULL, monto, 0)), 0) AS servicios, "
        "COALESCE(SUM(IF(tipo = 'ingreso' AND id_venta IS NOT NULL, monto, 0)), 0) AS productos, "
        "COALESCE(SUM(IF(tipo = 'ingreso', COALESCE(pago_profesional, 0), 0)), 0) AS comisiones, "
        "COALESCE(SUM(IF(tipo = 'salida' AND id_liquidacion IS NULL, monto, 0)), 0) AS gastos, "
        "COALESCE(SUM(IF(tipo = 'salida' AND id_liquidacion IS NOT NULL, monto, 0)), 0) AS pagos_profesionales, "
        "COALESCE(SUM(IF(metodo = 'efectivo', IF(tipo = 'ingreso', monto, -monto), 0)), 0) AS efectivo, "
        "COALESCE(SUM(IF(metodo = 'transferencia', IF(tipo = 'ingreso', monto, -monto), 0)), 0) AS transferencias "
        f"FROM movimientos_caja WHERE id_tienda = %s AND id_sede IN ({marcas}) AND fecha >= %s AND fecha < %s",
        (id_tienda, *sedes, *_rango(desde, hasta)),
    )
    return {k: int(v) for k, v in cur.fetchone().items()}


def desglose_profesionales(cur, id_tienda: int, sedes: list[int] | None, desde: date, hasta: date,
                           id_profesional: int | None = None) -> list[dict]:
    """Por profesional: citas cobradas, lo que facturo y lo que gana."""
    sql = (
        "SELECT m.id_profesional, u.nombre_completo, COUNT(DISTINCT m.id_cita) AS citas, "
        "SUM(m.monto) AS total, SUM(COALESCE(m.pago_profesional, 0)) AS pago "
        "FROM movimientos_caja m JOIN usuarios u ON u.id_usuario = m.id_profesional "
        "WHERE m.id_tienda = %s AND m.tipo = 'ingreso' AND m.id_cita IS NOT NULL AND m.fecha >= %s AND m.fecha < %s"
    )
    params: list = [id_tienda, *_rango(desde, hasta)]
    if sedes:
        sql += f" AND m.id_sede IN ({', '.join(['%s'] * len(sedes))})"
        params += sedes
    if id_profesional:
        sql += " AND m.id_profesional = %s"
        params.append(id_profesional)
    cur.execute(sql + " GROUP BY m.id_profesional, u.nombre_completo ORDER BY u.nombre_completo", params)
    return [
        {"id_profesional": f["id_profesional"], "nombre": f["nombre_completo"], "citas": int(f["citas"]),
         "total": int(f["total"]), "pago": int(f["pago"]), "local": int(f["total"]) - int(f["pago"])}
        for f in cur.fetchall()
    ]


def _movimientos(cur, id_tienda: int, sedes: list[int], fecha: date) -> list[dict]:
    marcas = ", ".join(["%s"] * len(sedes))
    cur.execute(
        "SELECT m.id_movimiento, m.id_sede, m.tipo, m.concepto, m.monto, m.metodo, m.id_cita, m.id_venta, "
        "m.id_liquidacion, m.pago_profesional, m.fecha, u.nombre_completo AS profesional "
        "FROM movimientos_caja m LEFT JOIN usuarios u ON u.id_usuario = m.id_profesional "
        f"WHERE m.id_tienda = %s AND m.id_sede IN ({marcas}) AND m.fecha >= %s AND m.fecha < %s "
        "ORDER BY m.fecha DESC, m.id_movimiento DESC LIMIT %s",
        (id_tienda, *sedes, *_rango(fecha, fecha), MAX_MOVIMIENTOS),
    )
    return [
        {
            "id_movimiento": f["id_movimiento"],
            "id_sede": f["id_sede"],
            "tipo": f["tipo"],
            "categoria": ("servicio" if f["id_cita"] else "producto" if f["id_venta"] else
                          "pago_profesional" if f["id_liquidacion"] else
                          "gasto" if f["tipo"] == "salida" else "otro"),
            "concepto": f["concepto"],
            "monto": int(f["monto"]),
            "metodo": f["metodo"],
            "profesional": f["profesional"],
            "pago_profesional": int(f["pago_profesional"]) if f["pago_profesional"] is not None else None,
            "id_cita": f["id_cita"],
            "id_venta": f["id_venta"],
            "hora": f["fecha"].strftime("%H:%M"),
        }
        for f in cur.fetchall()
    ]


def _armar_resumen(cur, id_tienda: int, sedes: list[int], fecha: date, base: int) -> dict:
    t = _totales(cur, id_tienda, sedes, fecha, fecha)
    return {
        "fecha": fecha.isoformat(),
        "base": base,
        **t,
        # Lo que debe haber en el cajon: base + efectivo que entro - el que salio.
        "efectivo_esperado": base + t["efectivo"],
        # Lo que queda para el local: ingresos - lo que ganan los profesionales
        # por esos cobros - gastos (el pago de una liquidacion no se descuenta
        # otra vez: ya esta en `comisiones` del dia en que se cobro).
        "local": t["ingresos"] - t["comisiones"] - t["gastos"],
        "profesionales": desglose_profesionales(cur, id_tienda, sedes, fecha, fecha),
    }


def resumen_dia(id_tienda: int, sedes: list[int], fecha: date) -> dict:
    """Caja de un dia: totales, desglose por profesional y movimientos. Con
    varias sedes es la caja consolidada (sin cierre: cada sede cierra la suya)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        marcas = ", ".join(["%s"] * len(sedes))
        cur.execute(
            "SELECT id_sede, estado, base, contado, diferencia, observaciones, fecha_cierre FROM cajas_dia "
            f"WHERE id_sede IN ({marcas}) AND fecha = %s AND id_tienda = %s",
            (*sedes, fecha, id_tienda),
        )
        cajas = {f["id_sede"]: f for f in cur.fetchall()}
        base = sum(int(c["base"]) for c in cajas.values())
        resumen = _armar_resumen(cur, id_tienda, sedes, fecha, base)
        resumen["movimientos"] = _movimientos(cur, id_tienda, sedes, fecha)
    finally:
        conn.close()
    if len(sedes) == 1:
        caja = cajas.get(sedes[0]) or {}
        resumen["estado"] = caja.get("estado", "abierta")
        if resumen["estado"] == "cerrada":
            resumen["cierre"] = {
                "contado": int(caja["contado"]),
                "diferencia": int(caja["diferencia"]),
                "observaciones": caja["observaciones"],
                "hora": caja["fecha_cierre"].strftime("%Y-%m-%d %H:%M") if caja["fecha_cierre"] else None,
            }
    else:
        resumen["sedes_cerradas"] = sum(1 for c in cajas.values() if c["estado"] == "cerrada")
    return resumen


def resumen_mes(id_tienda: int, sedes: list[int], anio: int, mes: int) -> dict:
    """Gastos y ganancia real del mes: servicios - comisiones + productos -
    lo que costaron - gastos."""
    desde = date(anio, mes, 1)
    hasta = (date(anio + (mes == 12), mes % 12 + 1, 1)) - timedelta(days=1)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        t = _totales(cur, id_tienda, sedes, desde, hasta)
        marcas = ", ".join(["%s"] * len(sedes))
        cur.execute(
            "SELECT COALESCE(SUM(vp.cantidad * vp.costo), 0) AS costo FROM ventas v "
            "JOIN venta_productos vp ON vp.id_venta = v.id_venta "
            f"WHERE v.id_tienda = %s AND v.id_sede IN ({marcas}) AND v.estado = 'pagada' "
            "AND v.fecha >= %s AND v.fecha < %s",
            (id_tienda, *sedes, *_rango(desde, hasta)),
        )
        costo = int(cur.fetchone()["costo"])
        cur.execute(
            "SELECT concepto, COUNT(*) AS veces, SUM(monto) AS total FROM movimientos_caja "
            f"WHERE id_tienda = %s AND id_sede IN ({marcas}) AND tipo = 'salida' AND id_liquidacion IS NULL "
            "AND fecha >= %s AND fecha < %s GROUP BY concepto ORDER BY total DESC LIMIT 20",
            (id_tienda, *sedes, *_rango(desde, hasta)),
        )
        gastos = [{"concepto": f["concepto"], "veces": int(f["veces"]), "total": int(f["total"])}
                  for f in cur.fetchall()]
        profesionales = desglose_profesionales(cur, id_tienda, sedes, desde, hasta)
    finally:
        conn.close()
    return {
        "mes": f"{anio:04d}-{mes:02d}",
        "servicios": t["servicios"],
        "comisiones": t["comisiones"],
        "productos": t["productos"],
        "costo_productos": costo,
        "gastos": t["gastos"],
        "ganancia": t["servicios"] - t["comisiones"] + t["productos"] - costo - t["gastos"],
        "principales_gastos": gastos,
        "profesionales": profesionales,
    }


# ── Base, gastos y cierre ──────────────────────────────────────────

def poner_base(id_tienda: int, id_sede: int, data: dict) -> int:
    base = parse_int(data.get("base"), "La base", min_value=0, max_value=MONTO_MAX)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        bloquear_dia(cur, id_tienda, id_sede, hoy_local())
        cur.execute("UPDATE cajas_dia SET base = %s WHERE id_sede = %s AND fecha = %s AND id_tienda = %s",
                    (base, id_sede, hoy_local(), id_tienda))
        conn.commit()
        return base
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def registrar_gasto(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> int:
    """Salida de plata del local hoy: insumos, servicios, arriendo..."""
    concepto = sanitize_text(data.get("concepto"), "El concepto", max_len=120)
    monto = parse_int(data.get("monto"), "El monto", min_value=1, max_value=MONTO_MAX)
    metodo = parse_metodo(data.get("metodo") or "efectivo")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        bloquear_dia(cur, id_tienda, id_sede, hoy_local())
        insertar_movimientos(cur, id_tienda, id_sede, id_usuario, "salida", concepto, [(metodo, monto)], ahora_local())
        id_movimiento = cur.lastrowid
        conn.commit()
        return id_movimiento
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def borrar_gasto(id_tienda: int, id_movimiento: int, sedes_permitidas: list[int] | None) -> None:
    """Deshace un gasto mientras su dia siga abierto. Los cobros se deshacen
    desde la cita o la venta; los pagos de comisiones no se borran."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_sede, DATE(fecha) AS dia, tipo, id_liquidacion FROM movimientos_caja "
            "WHERE id_movimiento = %s AND id_tienda = %s",
            (id_movimiento, id_tienda),
        )
        mov = cur.fetchone()
        if not mov or (sedes_permitidas is not None and mov["id_sede"] not in sedes_permitidas):
            raise NoEncontrado("Movimiento no encontrado.")
        if mov["tipo"] != "salida" or mov["id_liquidacion"]:
            raise ErrorServicio("Solo se borran gastos. Un cobro se deshace desde su cita o su venta.")
        bloquear_dia(cur, id_tienda, mov["id_sede"], mov["dia"])
        cur.execute("DELETE FROM movimientos_caja WHERE id_movimiento = %s AND id_tienda = %s", (id_movimiento, id_tienda))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cerrar(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> dict:
    """Cierra la caja del dia con el efectivo contado. Devuelve el resumen y la
    diferencia (positiva = sobra, negativa = falta)."""
    fecha = parse_fecha(data.get("fecha"))
    contado = parse_int(data.get("contado"), "El efectivo contado", min_value=0, max_value=MONTO_MAX)
    observaciones = sanitize_optional_text(data.get("observaciones"), "Las observaciones", max_len=255)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        dia = bloquear_dia(cur, id_tienda, id_sede, fecha)
        resumen = _armar_resumen(cur, id_tienda, [id_sede], fecha, int(dia["base"]))
        diferencia = contado - resumen["efectivo_esperado"]
        cur.execute(
            "UPDATE cajas_dia SET estado = 'cerrada', ingresos = %s, salidas = %s, transferencias = %s, "
            "efectivo_esperado = %s, contado = %s, diferencia = %s, observaciones = %s, id_usuario_cierre = %s, "
            "fecha_cierre = %s WHERE id_sede = %s AND fecha = %s AND id_tienda = %s",
            (resumen["ingresos"], resumen["salidas"], resumen["transferencias"], resumen["efectivo_esperado"],
             contado, diferencia, observaciones, id_usuario, ahora_local(), id_sede, fecha, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    resumen.update(estado="cerrada", contado=contado, diferencia=diferencia)
    return resumen


def reabrir(id_tienda: int, id_sede: int, data: dict) -> None:
    fecha = parse_fecha(data.get("fecha"))
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        dia = bloquear_dia(cur, id_tienda, id_sede, fecha, abierta=False)
        if dia["estado"] != "cerrada":
            raise Conflicto("La caja de ese día no está cerrada.")
        cur.execute(
            "UPDATE cajas_dia SET estado = 'abierta', ingresos = NULL, salidas = NULL, transferencias = NULL, "
            "efectivo_esperado = NULL, contado = NULL, diferencia = NULL, id_usuario_cierre = NULL, "
            "fecha_cierre = NULL WHERE id_sede = %s AND fecha = %s AND id_tienda = %s",
            (id_sede, fecha, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Cobro de citas ─────────────────────────────────────────────────

def _pago_del_profesional(cur, id_servicio: int | None, id_profesional: int, precio: int) -> int:
    """Lo que gana el profesional por el servicio: su pago propio
    (profesional_servicios) o el del servicio, nunca mas que lo cobrado."""
    if not id_servicio:
        return 0
    cur.execute(
        "SELECT COALESCE(ps.pago_profesional, s.pago_profesional) AS pago FROM servicios s "
        "LEFT JOIN profesional_servicios ps ON ps.id_servicio = s.id_servicio AND ps.id_usuario = %s "
        "WHERE s.id_servicio = %s",
        (id_profesional, id_servicio),
    )
    fila = cur.fetchone()
    return min(int(fila["pago"]), precio) if fila else 0


def _sede_de_cita(cur, id_tienda: int, id_cita: int) -> int:
    cur.execute("SELECT id_sede FROM citas WHERE id_cita = %s AND id_tienda = %s", (id_cita, id_tienda))
    fila = cur.fetchone()
    if not fila:
        raise NoEncontrado("Cita no encontrada.")
    return fila["id_sede"]


def cobrar_cita(id_tienda: int, id_cita: int, usuario: dict, data: dict) -> dict:
    """Cobra una cita reservada: el ingreso a caja (con pago mixto), lo que gana
    el profesional y la cita en 'completada', todo o nada (el cobro atomico del
    backend Node, appointments.service.complete).

    `usuario`: id_usuario y rol de quien cobra. Un Profesional solo
    cobra sus citas; una cita sin profesional queda a nombre de quien la cobra
    si atiende. `precio` opcional cambia el valor (descuento o recargo)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        id_sede = _sede_de_cita(cur, id_tienda, id_cita)
        bloquear_dia(cur, id_tienda, id_sede, hoy_local())
        cur.execute(
            "SELECT c.id_sede, c.id_servicio, c.id_profesional, c.estado, c.precio, c.cliente_nombre, "
            "s.nombre AS servicio FROM citas c LEFT JOIN servicios s ON s.id_servicio = c.id_servicio "
            "WHERE c.id_cita = %s AND c.id_tienda = %s FOR UPDATE",
            (id_cita, id_tienda),
        )
        cita = cur.fetchone()
        if not cita or cita["id_sede"] != id_sede:
            raise NoEncontrado("Cita no encontrada.")
        id_profesional = cita["id_profesional"]
        if usuario["rol"] == "Profesional" and id_profesional not in (None, usuario["id_usuario"]):
            raise NoEncontrado("Cita no encontrada.")
        if cita["estado"] != "reservada":
            raise Conflicto("Esa cita ya no está por cobrar.")
        if id_profesional is None:
            cur.execute("SELECT atiende FROM usuarios WHERE id_usuario = %s", (usuario["id_usuario"],))
            if not (cur.fetchone() or {}).get("atiende"):
                raise ErrorServicio("Asigna un profesional a la cita antes de cobrarla.")
            id_profesional = usuario["id_usuario"]
        precio = int(cita["precio"])
        if data.get("precio") not in (None, ""):
            precio = parse_int(data.get("precio"), "El precio", min_value=1, max_value=MONTO_MAX)
        if precio <= 0:
            raise ErrorServicio("Escribe el precio del servicio para cobrarlo.")
        pagos = parse_pagos(data, precio)
        pago = _pago_del_profesional(cur, cita["id_servicio"], id_profesional, precio)
        concepto = f"{cita['servicio'] or 'Servicio'} · {cita['cliente_nombre'] or 'Cliente'}"
        insertar_movimientos(cur, id_tienda, id_sede, usuario["id_usuario"], "ingreso", concepto, pagos,
                             ahora_local(), id_cita=id_cita, id_profesional=id_profesional, pago_profesional=pago)
        cur.execute(
            "UPDATE citas SET estado = 'completada', id_profesional = %s, precio = %s WHERE id_cita = %s AND id_tienda = %s",
            (id_profesional, precio, id_cita, id_tienda),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"id_cita": id_cita, "total": precio, "pago_profesional": pago, "local": precio - pago,
            "id_profesional": id_profesional}


def deshacer_cobro(id_tienda: int, id_cita: int, usuario: dict) -> None:
    """Saca el cobro de la caja y la cita vuelve a 'reservada', mientras el
    dia del cobro siga abierto y la comision no se haya pagado."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_sede, DATE(fecha) AS dia, id_profesional, id_liquidacion FROM movimientos_caja "
            "WHERE id_cita = %s AND id_tienda = %s AND tipo = 'ingreso' ORDER BY id_movimiento LIMIT 1",
            (id_cita, id_tienda),
        )
        mov = cur.fetchone()
        if not mov or (usuario["rol"] == "Profesional" and mov["id_profesional"] != usuario["id_usuario"]):
            raise NoEncontrado("Esa cita no tiene cobro.")
        if mov["id_liquidacion"]:
            raise Conflicto("La comisión de ese cobro ya se pagó: no se puede deshacer.")
        bloquear_dia(cur, id_tienda, mov["id_sede"], mov["dia"])
        # Volver a 'reservada' ocupa otra vez su horario: mismas reglas de
        # cruce que la agenda (T6), con su candado de sede.
        agenda_service._bloquear_sede(cur, id_tienda, mov["id_sede"])
        cur.execute(
            "SELECT estado, id_sede, id_profesional, inicio, fin FROM citas WHERE id_cita = %s AND id_tienda = %s "
            "FOR UPDATE",
            (id_cita, id_tienda),
        )
        cita = cur.fetchone()
        # Otra vez, ya con candado: una liquidacion pudo entrar entre tanto.
        cur.execute(
            "SELECT 1 FROM movimientos_caja WHERE id_cita = %s AND id_tienda = %s AND id_liquidacion IS NOT NULL FOR UPDATE",
            (id_cita, id_tienda),
        )
        if cur.fetchall():
            raise Conflicto("La comisión de ese cobro ya se pagó: no se puede deshacer.")
        cur.execute("DELETE FROM movimientos_caja WHERE id_cita = %s AND id_tienda = %s AND tipo = 'ingreso'",
                    (id_cita, id_tienda))
        if cita and cita["estado"] == "completada":
            agenda_service._sin_cruces(cur, id_tienda, cita["id_sede"], cita["id_profesional"], cita["inicio"],
                                       cita["fin"], excluir=id_cita)
            try:
                cur.execute("UPDATE citas SET estado = 'reservada' WHERE id_cita = %s AND id_tienda = %s", (id_cita, id_tienda))
            except IntegrityError as exc:
                raise Conflicto("Esa hora ya la ocupa otra cita del profesional: no se puede deshacer.") from exc
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
