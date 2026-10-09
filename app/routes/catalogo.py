"""API de catalogo y configuracion (T4): servicios, profesionales, datos del
local, horario de cada sede, y las imagenes (logo y fotos).

Leer es para todo el equipo (la agenda y la caja necesitan el catalogo);
cambiar es del Admin, salvo la foto propia, que cada quien puede cambiar.
Todo filtra por el id_tienda de la sesion, nunca por uno que mande el cliente.
"""
from __future__ import annotations

from flask import Blueprint, Response, abort, g, jsonify, request, session

from app.services import catalogo_service, imagen_service, local_service, profesional_service
from app.services.errores import ErrorServicio
from app.services.plan_service import LimitePlanError
from app.services.usuario_service import ROLES_NEGOCIO
from app.utils.decorators import login_required, roles_required

catalogo = Blueprint("catalogo", __name__)

_ERRORES = (ValueError, ErrorServicio, LimitePlanError)


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: Exception):
    if isinstance(exc, LimitePlanError):
        cuerpo, status = exc.respuesta()
        return jsonify(cuerpo), status
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


def _archivo() -> bytes:
    """La imagen del formulario multipart (campo `imagen`)."""
    archivo = request.files.get("imagen")
    # Un byte mas que el tope: basta para saber que se paso sin leerlo entero.
    return archivo.read(imagen_service.MAX_BYTES + 1) if archivo else b""


# ── Servicios ───────────────────────────────────────────────────────

@catalogo.get("/api/servicios")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_servicios():
    return jsonify({"ok": True, "servicios": catalogo_service.listar_servicios(session["id_tienda"])})


@catalogo.post("/api/servicios")
@login_required
@roles_required("Admin")
def api_servicios_crear():
    try:
        id_servicio = catalogo_service.crear_servicio(session["id_tienda"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "id_servicio": id_servicio, "msg": "Servicio creado."}), 201


@catalogo.put("/api/servicios/<int:id_servicio>")
@login_required
@roles_required("Admin")
def api_servicios_actualizar(id_servicio):
    try:
        catalogo_service.actualizar_servicio(session["id_tienda"], id_servicio, _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Servicio actualizado."})


@catalogo.delete("/api/servicios/<int:id_servicio>")
@login_required
@roles_required("Admin")
def api_servicios_desactivar(id_servicio):
    try:
        catalogo_service.desactivar_servicio(session["id_tienda"], id_servicio)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Servicio eliminado."})


# ── Profesionales ───────────────────────────────────────────────────

@catalogo.get("/api/profesionales")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_profesionales():
    """Quienes atienden en la sede de la sesion. Lo que gana cada uno solo lo
    ve el Admin; los demas ven su propio pago y el de fabrica del servicio."""
    profesionales = profesional_service.listar_profesionales(session["id_tienda"], g.id_sede)
    if session.get("rol") != "Admin":
        servicios = {s["id_servicio"]: s for s in catalogo_service.listar_servicios(session["id_tienda"])}
        for p in profesionales:
            if p["id_usuario"] != session["id_usuario"]:
                for s in p["servicios"]:
                    s["pago_profesional"] = servicios[s["id_servicio"]]["pago_profesional"]
    return jsonify({"ok": True, "profesionales": profesionales})


@catalogo.put("/api/profesionales/<int:id_usuario>")
@login_required
@roles_required("Admin")
def api_profesionales_actualizar(id_usuario):
    try:
        profesional_service.actualizar_profesional(session["id_tienda"], id_usuario, _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Profesional actualizado."})


def _puede_cambiar_foto(id_usuario: int) -> bool:
    return session.get("rol") == "Admin" or session.get("id_usuario") == id_usuario


@catalogo.post("/api/usuarios/<int:id_usuario>/foto")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_foto_subir(id_usuario):
    if not _puede_cambiar_foto(id_usuario):
        return jsonify({"ok": False, "msg": "No tienes permisos para esta accion."}), 403
    try:
        foto_url = profesional_service.cambiar_foto(session["id_tienda"], id_usuario, _archivo())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "foto_url": foto_url, "msg": "Foto actualizada."})


@catalogo.delete("/api/usuarios/<int:id_usuario>/foto")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_foto_quitar(id_usuario):
    if not _puede_cambiar_foto(id_usuario):
        return jsonify({"ok": False, "msg": "No tienes permisos para esta accion."}), 403
    try:
        profesional_service.cambiar_foto(session["id_tienda"], id_usuario, None)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Foto eliminada."})


# ── Datos del local ─────────────────────────────────────────────────

@catalogo.get("/api/negocio")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_negocio():
    datos = local_service.datos_negocio(session["id_tienda"])
    # ponytail: la pagina publica /r/<slug> llega con T8.
    datos["enlace_reservas"] = f"{request.host_url}r/{datos['slug']}"
    return jsonify({"ok": True, "negocio": datos})


@catalogo.put("/api/negocio")
@login_required
@roles_required("Admin")
def api_negocio_actualizar():
    try:
        local_service.actualizar_negocio(session["id_tienda"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Datos del negocio actualizados."})


@catalogo.post("/api/negocio/logo")
@login_required
@roles_required("Admin")
def api_logo_subir():
    try:
        logo_url = local_service.cambiar_logo(session["id_tienda"], _archivo())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "logo_url": logo_url, "msg": "Logo actualizado."})


@catalogo.delete("/api/negocio/logo")
@login_required
@roles_required("Admin")
def api_logo_quitar():
    local_service.cambiar_logo(session["id_tienda"], None)
    return jsonify({"ok": True, "msg": "Logo eliminado."})


# ── Horario ─────────────────────────────────────────────────────────

@catalogo.get("/api/horario")
@login_required
@roles_required(*ROLES_NEGOCIO)
def api_horario():
    """Horario de la sede de la sesion, u otra del negocio con ?id_sede=."""
    try:
        dias = local_service.horario(session["id_tienda"], request.args.get("id_sede") or g.id_sede)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "dias": dias})


@catalogo.put("/api/horario")
@login_required
@roles_required("Admin")
def api_horario_guardar():
    data = _json()
    try:
        local_service.guardar_horario(session["id_tienda"], data.get("id_sede") or g.id_sede, data.get("dias"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Horario guardado."})


# ── Imagenes publicas ───────────────────────────────────────────────

@catalogo.get("/img/<int:id_imagen>")
def imagen(id_imagen):
    """Logo y fotos: publicas porque salen en la pagina de reservas. Cada
    cambio crea un id nuevo, asi que se cachean un ano."""
    fila = imagen_service.leer(id_imagen)
    if not fila:
        abort(404)
    respuesta = Response(bytes(fila["datos"]), mimetype=fila["tipo"])
    respuesta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    return respuesta
