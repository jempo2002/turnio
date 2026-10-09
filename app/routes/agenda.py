"""API de la agenda (T6): citas, bloqueos y horas libres de la sede de la
sesion.

Admin y Recepcion manejan la agenda de todos; un Profesional ve la agenda de
la sede pero solo agenda, mueve, cancela o bloquea lo suyo. Bloquear toda la
sede es de Admin y Recepcion. Todo filtra por id_tienda e id_sede de la
sesion, nunca por los que mande el cliente.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request, session

from app.services import agenda_service
from app.services.errores import ErrorServicio
from app.services.usuario_service import ROLES_NEGOCIO
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import hoy_local
from app.utils.validation import parse_int

agenda = Blueprint("agenda", __name__)

_ERRORES = (ValueError, ErrorServicio)
_SOLO_LO_TUYO = "Solo puedes manejar tu propia agenda."


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: Exception):
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


def _es_profesional() -> bool:
    return session.get("rol") == "Profesional"


def _prohibido():
    return jsonify({"ok": False, "msg": _SOLO_LO_TUYO}), 403


def _es_ajena(id_profesional) -> bool:
    """Un Profesional solo toca citas y bloqueos suyos."""
    if not _es_profesional():
        return False
    try:
        return int(id_profesional) != session["id_usuario"]
    except (TypeError, ValueError):
        return True


def _cita_ajena(id_cita: int) -> bool:
    return _es_profesional() and _es_ajena(agenda_service.dueno_de_cita(session["id_tienda"], g.id_sede, id_cita))


# ── Consultar ───────────────────────────────────────────────────────

@agenda.get("/api/citas")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_citas():
    """?fecha=AAAA-MM-DD (un dia, por defecto hoy en Colombia) o
    ?desde=...&hasta=... (la semana). ?id_profesional= filtra una agenda."""
    args = request.args
    try:
        if args.get("desde"):
            desde = agenda_service.parse_fecha(args["desde"], "Desde")
            hasta = agenda_service.parse_fecha(args.get("hasta") or args["desde"], "Hasta")
        else:
            desde = hasta = agenda_service.parse_fecha(args["fecha"]) if args.get("fecha") else hoy_local()
        id_profesional = parse_int(args["id_profesional"], "Profesional") if args.get("id_profesional") else None
        citas = agenda_service.listar(session["id_tienda"], g.id_sede, desde, hasta, id_profesional)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "desde": desde.isoformat(), "hasta": hasta.isoformat(), "citas": citas})


@agenda.get("/api/citas/<int:id_cita>")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_cita(id_cita):
    try:
        cita = agenda_service.obtener(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "cita": cita})


@agenda.get("/api/agenda/disponibilidad")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_disponibilidad():
    """?id_servicio=&fecha= (por defecto hoy) y opcional ?id_profesional=."""
    args = request.args
    try:
        dia = agenda_service.parse_fecha(args["fecha"]) if args.get("fecha") else hoy_local()
        datos = agenda_service.disponibilidad(
            session["id_tienda"], g.id_sede, dia, args.get("id_servicio"), args.get("id_profesional"),
        )
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, **datos})


# ── Citas ───────────────────────────────────────────────────────────

@agenda.post("/api/citas")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_citas_crear():
    data = _json()
    if _es_ajena(data.get("id_profesional")):
        return _prohibido()
    try:
        id_cita = agenda_service.crear_cita(session["id_tienda"], g.id_sede, session["id_usuario"], data)
        cita = agenda_service.obtener(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "cita": cita, "msg": "Cita agendada."}), 201


@agenda.put("/api/citas/<int:id_cita>")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_citas_reprogramar(id_cita):
    data = _json()
    try:
        if _cita_ajena(id_cita) or (data.get("id_profesional") and _es_ajena(data["id_profesional"])):
            return _prohibido()
        agenda_service.reprogramar(session["id_tienda"], g.id_sede, id_cita, data)
        cita = agenda_service.obtener(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "cita": cita, "msg": "Cita reprogramada."})


@agenda.post("/api/citas/<int:id_cita>/cancelar")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_citas_cancelar(id_cita):
    try:
        if _cita_ajena(id_cita):
            return _prohibido()
        agenda_service.cancelar(session["id_tienda"], g.id_sede, id_cita, _json().get("motivo"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Cita cancelada."})


@agenda.post("/api/citas/<int:id_cita>/no-asistio")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_citas_no_asistio(id_cita):
    try:
        if _cita_ajena(id_cita):
            return _prohibido()
        agenda_service.marcar_no_asistio(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Marcada como inasistencia."})


# ── Bloqueos ────────────────────────────────────────────────────────

@agenda.post("/api/bloqueos")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_bloqueos_crear():
    """{desde, hasta, motivo?, id_profesional?}: sin profesional bloquea
    toda la sede."""
    data = _json()
    if _es_profesional() and _es_ajena(data.get("id_profesional")):
        return _prohibido()
    try:
        id_cita = agenda_service.crear_bloqueo(session["id_tienda"], g.id_sede, session["id_usuario"], data)
        bloqueo = agenda_service.obtener(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "bloqueo": bloqueo, "msg": "Horario bloqueado."}), 201


@agenda.delete("/api/bloqueos/<int:id_cita>")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_bloqueos_quitar(id_cita):
    try:
        if _cita_ajena(id_cita):
            return _prohibido()
        agenda_service.quitar_bloqueo(session["id_tienda"], g.id_sede, id_cita)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Bloqueo quitado."})
