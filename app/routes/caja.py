"""API de caja e inventario (T5): caja del dia, cobro de citas, gastos,
cierre, venta rapida, productos con codigo de barras y comisiones.

Quien puede que:
  - Todo el equipo vende, cobra sus citas y consulta productos.
  - Admin y Recepcion: caja del dia, gastos, base, cierre, entradas y
    ajustes de stock, cobrar cualquier cita, deshacer cobros y anular ventas.
  - Admin: catalogo de productos, reabrir una caja, resumen del mes,
    comisiones de todos y liquidaciones. Un Admin sin sede fija puede ver y
    cerrar otra sede con `id_sede` (y la caja consolidada con id_sede=todas).
  - Profesional: sus propias comisiones (Pro).
Todo filtra por el id_tienda de la sesion, nunca por uno que mande el cliente.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, g, jsonify, request, session

from app.services import caja_service, comisiones_service, inventario_service, venta_service
from app.services.errores import ErrorServicio, NoEncontrado
from app.services.plan_service import LimitePlanError, requiere_funcion
from app.services.usuario_service import ROLES_NEGOCIO
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import hoy_local
from database import get_db

caja = Blueprint("caja", __name__)

_ERRORES = (ValueError, ErrorServicio, LimitePlanError)
_CAJA = ("Admin", "Recepcion")


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: Exception):
    if isinstance(exc, LimitePlanError):
        cuerpo, status = exc.respuesta()
        return jsonify(cuerpo), status
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


def _usuario() -> dict:
    return {"id_usuario": session["id_usuario"], "rol": session.get("rol")}


def _admin_libre() -> bool:
    """Admin sin sede fija: puede trabajar sobre cualquier sede del negocio."""
    return session.get("rol") == "Admin" and g.get("sede_fija") is None


def _sedes_permitidas() -> list[int] | None:
    """None = todas las sedes del negocio."""
    return None if _admin_libre() else [g.id_sede]


def _sede(raw) -> int:
    """La sede pedida (Admin sin sede fija) o la de la sesion."""
    if raw in (None, "") or not _admin_libre():
        return g.id_sede
    conn = get_db()
    try:
        return caja_service.sede_de_tienda(conn.cursor(dictionary=True), session["id_tienda"], raw)
    finally:
        conn.close()


def _sedes_consulta(raw) -> list[int]:
    if raw == "todas" and _admin_libre():
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id_sede FROM sedes WHERE id_tienda = %s AND estado = 'Activa' ORDER BY id_sede",
                        (session["id_tienda"],))
            return [f[0] for f in cur.fetchall()]
        finally:
            conn.close()
    return [_sede(raw)]


# ── Caja del dia ────────────────────────────────────────────────────

@caja.get("/api/caja")
@login_required
@roles_required(*_CAJA)
def api_caja():
    """Caja de hoy (o ?fecha=AAAA-MM-DD) de la sede: totales por metodo,
    efectivo esperado en el cajon, desglose por profesional y movimientos."""
    try:
        sedes = _sedes_consulta(request.args.get("id_sede"))
        fecha = caja_service.parse_fecha(request.args.get("fecha"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "caja": caja_service.resumen_dia(session["id_tienda"], sedes, fecha)})


@caja.put("/api/caja/base")
@login_required
@roles_required(*_CAJA)
def api_caja_base():
    data = _json()
    try:
        base = caja_service.poner_base(session["id_tienda"], _sede(data.get("id_sede")), data)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "base": base, "msg": "Base guardada."})


@caja.post("/api/caja/gastos")
@login_required
@roles_required(*_CAJA)
def api_caja_gasto():
    try:
        id_movimiento = caja_service.registrar_gasto(session["id_tienda"], g.id_sede, session["id_usuario"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "id_movimiento": id_movimiento, "msg": "Salida registrada."}), 201


@caja.delete("/api/caja/movimientos/<int:id_movimiento>")
@login_required
@roles_required(*_CAJA)
def api_caja_borrar_gasto(id_movimiento):
    try:
        caja_service.borrar_gasto(session["id_tienda"], id_movimiento, _sedes_permitidas())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Salida borrada."})


@caja.post("/api/caja/cierre")
@login_required
@roles_required(*_CAJA)
def api_caja_cierre():
    """Cierra el dia (hoy o `fecha`) con el efectivo `contado`."""
    data = _json()
    try:
        resumen = caja_service.cerrar(session["id_tienda"], _sede(data.get("id_sede")), session["id_usuario"], data)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "caja": resumen, "msg": "Caja cerrada."})


@caja.post("/api/caja/reabrir")
@login_required
@roles_required("Admin")
def api_caja_reabrir():
    data = _json()
    try:
        caja_service.reabrir(session["id_tienda"], _sede(data.get("id_sede")), data)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Caja reabierta."})


@caja.get("/api/caja/mes")
@login_required
@roles_required("Admin")
def api_caja_mes():
    """Gastos y ganancia real del mes (?mes=AAAA-MM, por defecto el actual)."""
    raw = request.args.get("mes") or hoy_local().strftime("%Y-%m")
    try:
        anio, mes = (int(x) for x in raw.split("-"))
        date(anio, mes, 1)
    except ValueError:
        return jsonify({"ok": False, "msg": "Elige un mes de la lista."}), 400
    try:
        sedes = _sedes_consulta(request.args.get("id_sede"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "resumen": caja_service.resumen_mes(session["id_tienda"], sedes, anio, mes)})


# ── Cobro de citas ──────────────────────────────────────────────────

@caja.post("/api/citas/<int:id_cita>/cobrar")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_cita_cobrar(id_cita):
    """Body: {"metodo": "efectivo"} o {"pagos": [{metodo, monto}, ...]} y
    `precio` opcional. El Profesional solo cobra sus citas."""
    try:
        cobro = caja_service.cobrar_cita(session["id_tienda"], id_cita, _usuario(), _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "cobro": cobro, "msg": "Cita cobrada."})


@caja.delete("/api/citas/<int:id_cita>/cobro")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_cita_deshacer_cobro(id_cita):
    try:
        caja_service.deshacer_cobro(session["id_tienda"], id_cita, _usuario())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Cobro deshecho: la cita vuelve a estar por cobrar."})


# ── Venta rapida ────────────────────────────────────────────────────

@caja.post("/api/ventas")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_venta():
    """Body: {"items": [{"id_producto" | "codigo_barras", "cantidad"}], "metodo"
    o "pagos"}. Los precios salen del catalogo."""
    try:
        venta = venta_service.vender(session["id_tienda"], g.id_sede, session["id_usuario"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "venta": venta, "msg": "Venta registrada en caja."}), 201


@caja.delete("/api/ventas/<int:id_venta>")
@login_required
@roles_required(*_CAJA)
def api_venta_anular(id_venta):
    try:
        venta_service.anular(session["id_tienda"], id_venta, session["id_usuario"], _sedes_permitidas())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Venta anulada: el stock volvió al inventario."})


# ── Productos e inventario ──────────────────────────────────────────

def _ver_costo() -> bool:
    return session.get("rol") in _CAJA


@caja.get("/api/productos")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_productos():
    """Productos con el stock de la sede (?q= busca por nombre o codigo)."""
    try:
        id_sede = _sede(request.args.get("id_sede"))
    except _ERRORES as exc:
        return _error(exc)
    productos = inventario_service.listar(session["id_tienda"], id_sede, request.args.get("q"), _ver_costo())
    return jsonify({"ok": True, "productos": productos})


@caja.get("/api/productos/codigo/<codigo>")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_producto_codigo(codigo):
    try:
        producto = inventario_service.por_codigo(session["id_tienda"], g.id_sede, codigo, _ver_costo())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "producto": producto})


@caja.post("/api/productos")
@login_required
@roles_required("Admin")
def api_producto_crear():
    try:
        id_producto = inventario_service.crear(session["id_tienda"], g.id_sede, session["id_usuario"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "id_producto": id_producto, "msg": "Producto creado."}), 201


@caja.put("/api/productos/<int:id_producto>")
@login_required
@roles_required("Admin")
def api_producto_actualizar(id_producto):
    try:
        inventario_service.actualizar(session["id_tienda"], id_producto, _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Producto actualizado."})


@caja.delete("/api/productos/<int:id_producto>")
@login_required
@roles_required("Admin")
def api_producto_desactivar(id_producto):
    try:
        inventario_service.desactivar(session["id_tienda"], id_producto)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Producto eliminado."})


@caja.post("/api/productos/<int:id_producto>/movimientos")
@login_required
@roles_required(*_CAJA)
def api_producto_movimiento(id_producto):
    """Entrada, Salida o Ajuste del stock de la sede."""
    try:
        stock = inventario_service.registrar_movimiento(
            session["id_tienda"], g.id_sede, session["id_usuario"], id_producto, _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "stock": stock, "msg": "Inventario actualizado."})


@caja.get("/api/productos/<int:id_producto>/movimientos")
@login_required
@roles_required(*_CAJA)
def api_producto_kardex(id_producto):
    try:
        movimientos = inventario_service.kardex(session["id_tienda"], g.id_sede, id_producto)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "movimientos": movimientos})


@caja.get("/api/inventario/alertas")
@login_required
@roles_required(*_CAJA)
@requiere_funcion("alerta_stock")
def api_inventario_alertas():
    """Productos de la sede en su stock minimo o por debajo (Pro)."""
    productos = inventario_service.listar(session["id_tienda"], g.id_sede, ver_costo=True, solo_bajos=True)
    return jsonify({"ok": True, "productos": productos})


@caja.post("/api/inventario/traslados")
@login_required
@roles_required("Admin")
@requiere_funcion("multisede")
def api_inventario_traslado():
    data = _json()
    try:
        if not _admin_libre():
            raise NoEncontrado("Sede no encontrada.")
        inventario_service.trasladar(
            session["id_tienda"], session["id_usuario"], int(data.get("id_producto") or 0),
            int(data.get("desde") or 0), int(data.get("hacia") or 0), data.get("cantidad"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Traslado registrado."})


# ── Comisiones (Pro) ────────────────────────────────────────────────

def _profesional_consultado() -> int | None:
    """El Profesional solo ve lo suyo; Admin y Recepcion, a todos o a uno."""
    if session.get("rol") == "Profesional":
        return session["id_usuario"]
    raw = request.args.get("id_profesional")
    return int(raw) if raw and raw.isdigit() else None


@caja.get("/api/comisiones")
@login_required
@roles_required(*ROLES_NEGOCIO)
@requiere_funcion("comisiones")
def api_comisiones():
    """Pendiente por pagar y lo ganado entre ?desde= y ?hasta= (por defecto
    el mes en curso)."""
    hoy = hoy_local()
    try:
        desde = caja_service.parse_fecha(request.args.get("desde") or hoy.replace(day=1).isoformat(),
                                         "La fecha inicial")
        hasta = caja_service.parse_fecha(request.args.get("hasta"), "La fecha final")
        id_profesional = _profesional_consultado()
        periodo = comisiones_service.periodo(session["id_tienda"], desde, hasta, id_profesional)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({
        "ok": True,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "periodo": periodo,
        "pendientes": comisiones_service.pendientes(session["id_tienda"], id_profesional),
        "liquidaciones": comisiones_service.historial(session["id_tienda"], id_profesional),
    })


@caja.post("/api/comisiones/liquidar")
@login_required
@roles_required("Admin")
@requiere_funcion("comisiones")
def api_comisiones_liquidar():
    """Body: id_profesional, hasta (opcional, hoy) y metodo. Sale de la caja
    de hoy de la sede de la sesion."""
    try:
        liquidacion = comisiones_service.liquidar(session["id_tienda"], g.id_sede, session["id_usuario"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "liquidacion": liquidacion, "msg": "Pago registrado en caja."}), 201
