"""Sedes y equipo del negocio (rol Admin). Tomado de jemPOS Chef."""
from __future__ import annotations

import html

from flask import Blueprint, current_app, jsonify, render_template, request, session, url_for

from app.services import sede_service, usuario_service
from app.services.auth_service import DIAS_INVITACION, create_invite_token
from app.services.plan_service import LimitePlanError
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import enlace_whatsapp
from app.utils.mail import send_invite_email_async

negocio = Blueprint("negocio", __name__)


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: Exception):
    """Traduce las excepciones de los servicios a la respuesta JSON."""
    if isinstance(exc, LimitePlanError):
        cuerpo, status = exc.respuesta()
        return jsonify(cuerpo), status
    status = getattr(exc, "status", 400)
    return jsonify({"ok": False, "msg": str(exc)}), status


_ERRORES = (ValueError, LimitePlanError, sede_service.SedeError, usuario_service.UsuarioError)


@negocio.get("/sedes")
@login_required
@roles_required("Admin")
def sedes_page():
    return render_template("sedes.html", **sede_service.resumen_sedes(session["id_tienda"]))


@negocio.post("/api/sedes")
@login_required
@roles_required("Admin")
def api_sedes_crear():
    try:
        id_sede = sede_service.crear_sede(session["id_tienda"], _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "id_sede": id_sede, "msg": "Sede creada."}), 201


@negocio.put("/api/sedes/<int:id_sede>")
@login_required
@roles_required("Admin")
def api_sedes_actualizar(id_sede):
    try:
        nombre = sede_service.actualizar_sede(session["id_tienda"], id_sede, _json())
    except _ERRORES as exc:
        return _error(exc)
    if session.get("id_sede") == id_sede:
        session["nombre_sede"] = nombre
    return jsonify({"ok": True, "msg": "Sede actualizada."})


@negocio.delete("/api/sedes/<int:id_sede>")
@login_required
@roles_required("Admin")
def api_sedes_eliminar(id_sede):
    try:
        sede_service.eliminar_sede(session["id_tienda"], id_sede)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Sede eliminada."})


@negocio.get("/equipo")
@login_required
@roles_required("Admin")
def equipo_page():
    id_tienda = session["id_tienda"]
    return render_template(
        "equipo.html",
        usuarios=usuario_service.listar_usuarios(id_tienda),
        sedes=sede_service.resumen_sedes(id_tienda)["sedes"],
        roles=usuario_service.ROLES_NEGOCIO,
    )


def _invitacion(id_usuario: int) -> dict:
    """Arma el enlace de invitacion, lo manda por correo (si hay SMTP) y lo
    devuelve para que el Admin lo comparta por WhatsApp."""
    usuario = usuario_service.datos_invitacion(session["id_tienda"], id_usuario)
    token = create_invite_token(current_app.secret_key, usuario["correo"], usuario["clave_hash"])
    enlace = url_for("auth.invitacion", token=token, _external=True)
    send_invite_email_async(usuario["correo"], usuario["nombre_negocio"], enlace)
    nombre = html.unescape(usuario["nombre_completo"]).split()[0]
    negocio = html.unescape(usuario["nombre_negocio"])
    texto = (
        f"Hola {nombre}, te invito a {negocio} en Turnio. "
        f"Elige tu contraseña aquí (vale {DIAS_INVITACION} días): {enlace}"
    )
    return {"enlace": enlace, "whatsapp": enlace_whatsapp(usuario["telefono"], texto)}


@negocio.post("/api/usuarios")
@login_required
@roles_required("Admin")
def api_usuarios_crear():
    data = _json()
    try:
        id_usuario = usuario_service.crear_usuario(session["id_tienda"], data)
    except _ERRORES as exc:
        return _error(exc)
    cuerpo = {"ok": True, "id_usuario": id_usuario, "msg": "Usuario creado."}
    if not data.get("password"):
        cuerpo.update(
            invitacion=_invitacion(id_usuario),
            msg="Usuario creado. Mándale este enlace para que elija su contraseña; sirve por 7 días.",
        )
    return jsonify(cuerpo), 201


@negocio.post("/api/usuarios/<int:id_usuario>/invitacion")
@login_required
@roles_required("Admin")
def api_usuarios_invitacion(id_usuario):
    """Enlace nuevo para quien aun no acepta (el anterior vencio o se perdio)."""
    try:
        invitacion = _invitacion(id_usuario)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "invitacion": invitacion, "msg": "Enlace nuevo listo. Mándaselo para que elija su contraseña; sirve por 7 días."})


@negocio.put("/api/usuarios/<int:id_usuario>")
@login_required
@roles_required("Admin")
def api_usuarios_actualizar(id_usuario):
    try:
        usuario_service.actualizar_usuario(session["id_tienda"], session["id_usuario"], id_usuario, _json())
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Usuario actualizado."})


@negocio.delete("/api/usuarios/<int:id_usuario>")
@login_required
@roles_required("Admin")
def api_usuarios_desactivar(id_usuario):
    try:
        usuario_service.desactivar_usuario(session["id_tienda"], session["id_usuario"], id_usuario)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Usuario desactivado."})
