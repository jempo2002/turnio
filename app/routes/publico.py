"""Pagina publica de reservas de cada negocio (T8): /r/<slug>.

Sin cuenta ni sesion para el cliente. Lo que protege la agenda del negocio:
  - limites por IP (y por WhatsApp al reservar) en Redis, como el login;
  - campo trampa `sitio_web` (honeypot), igual que /registro;
  - CSRF: la reserva lleva el token de la pagina, asi un bot tiene que
    cargarla antes de cada envio;
  - todo se busca por el slug: un id de sede, servicio o profesional de otro
    negocio no existe aqui (404).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app import limiter
from app.services import reserva_service
from app.services.errores import ErrorServicio, NoEncontrado
from app.utils.decorators import log_seguridad
from app.utils.helpers import only_digits

publico = Blueprint("publico", __name__)

LECTURA_RATE_LIMIT = "60 per minute"
RESERVA_RATE_LIMIT = "5 per minute; 20 per hour"
# Por WhatsApp, no por IP: frena al que cambia de IP para llenar la agenda.
RESERVA_TELEFONO_RATE_LIMIT = "5 per day"
_ERRORES = (ValueError, ErrorServicio)


def _error(exc: Exception):
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


def _telefono_reserva() -> str:
    datos = request.get_json(silent=True) or {}
    return "reserva:" + only_digits(datos.get("cliente_telefono"), max_len=15)


@publico.get("/r/<slug>")
def reservar(slug):
    try:
        tienda = reserva_service.tienda(slug)
    except NoEncontrado:
        return render_template("publico/no_encontrado.html"), 404
    return render_template("publico/reservar.html", tienda=tienda)


@publico.get("/api/publico/<slug>")
@limiter.limit(LECTURA_RATE_LIMIT)
def api_negocio(slug):
    try:
        datos = reserva_service.datos_publicos(reserva_service.tienda(slug))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, **datos})


@publico.get("/api/publico/<slug>/disponibilidad")
@limiter.limit(LECTURA_RATE_LIMIT)
def api_disponibilidad(slug):
    """?id_sede=&id_servicio=&fecha=AAAA-MM-DD"""
    args = request.args
    try:
        tienda = reserva_service.tienda(slug)
        datos = reserva_service.disponibilidad(tienda, args.get("id_sede"), args.get("id_servicio"), args.get("fecha"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, **datos})


@publico.post("/api/publico/<slug>/reservas")
@limiter.limit(RESERVA_RATE_LIMIT)
@limiter.limit(RESERVA_TELEFONO_RATE_LIMIT, key_func=_telefono_reserva)
def api_reservar(slug):
    data = request.get_json(silent=True) or {}
    if data.get("sitio_web"):
        log_seguridad("reserva_trampa", slug=slug)
        return jsonify({"ok": False, "msg": "No se pudo reservar."}), 400
    try:
        tienda = reserva_service.tienda(slug)
        cita = reserva_service.reservar(tienda, data)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "cita": cita, "msg": "¡Cita reservada!"}), 201
