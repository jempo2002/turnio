"""Panel Master (tomado de jemPOS Chef y ampliado con lo del panel de jemPOS).

Solo el rol Master entra. Tres pantallas:
  /panel-master                    resumen, negocios (filtros y busqueda) y alta
  /panel-master/negocios/<id>      ficha: datos, plan, cobros, sedes y equipo
  /panel-master/usuarios           usuarios de toda la plataforma
"""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app.services import master_service, plan_service, usuario_service
from app.services.auth_service import huella_clave
from app.services.plan_service import LimitePlanError
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import fmt_money, hoy_local

master = Blueprint("master", __name__)

_ERRORES = (ValueError, LimitePlanError, master_service.MasterError, usuario_service.UsuarioError)


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: Exception):
    if isinstance(exc, LimitePlanError):
        cuerpo, status = exc.respuesta()
        return jsonify(cuerpo), status
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


def _ok(msg: str, status: int = 200, **extra):
    return jsonify({"ok": True, "msg": msg, **extra}), status


# ── Pantallas ─────────────────────────────────────────────────────────

@master.get("/panel-master")
@login_required
@roles_required("Master")
def panel():
    todos = master_service.listar_negocios()
    situacion = request.args.get("situacion") or ""
    q = (request.args.get("q") or "").strip()[:100]
    return render_template(
        "master/panel.html",
        negocios=master_service.filtrar(todos, situacion, q),
        resumen=master_service.resumen(todos),
        situaciones=master_service.SITUACIONES,
        situacion=situacion if situacion in master_service.SITUACIONES else "",
        q=q,
        pagos=master_service.ultimos_pagos(),
        tipos=master_service.TIPOS_NEGOCIO,
        planes=plan_service.PLANES,
        plan_prueba=plan_service.PLAN_PRUEBA,
        dias_prueba=plan_service.DIAS_PRUEBA,
    )


@master.get("/panel-master/negocios/<int:id_tienda>")
@login_required
@roles_required("Master")
def negocio_page(id_tienda):
    try:
        ficha = master_service.negocio(id_tienda)
    except master_service.MasterError:
        flash("Ese negocio no existe o fue eliminado.", "error")
        return redirect(url_for("master.panel"))
    return render_template(
        "master/negocio.html",
        n=ficha,
        tipos=master_service.TIPOS_NEGOCIO,
        planes=plan_service.PLANES,
        periodos=master_service.PERIODOS,
        situaciones=master_service.SITUACIONES,
        roles=usuario_service.ROLES_NEGOCIO,
        hoy=hoy_local(),
    )


@master.get("/panel-master/usuarios")
@login_required
@roles_required("Master")
def usuarios_page():
    q = (request.args.get("q") or "").strip()[:100]
    return render_template(
        "master/usuarios.html",
        usuarios=master_service.buscar_usuarios(q),
        q=q,
        roles=usuario_service.ROLES_NEGOCIO,
    )


# ── Negocios ──────────────────────────────────────────────────────────

@master.post("/api/master/negocios")
@login_required
@roles_required("Master")
def api_crear():
    try:
        id_tienda = master_service.crear_negocio(_json())
    except _ERRORES as exc:
        return _error(exc)
    return _ok(
        f"Negocio creado con {plan_service.DIAS_PRUEBA} días de prueba del plan "
        f"{plan_service.PLANES[plan_service.PLAN_PRUEBA]['nombre']}.",
        201, id_tienda=id_tienda,
    )


@master.put("/api/master/negocios/<int:id_tienda>")
@login_required
@roles_required("Master")
def api_editar(id_tienda):
    try:
        master_service.editar_negocio(id_tienda, _json())
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Datos del negocio guardados.")


@master.put("/api/master/negocios/<int:id_tienda>/plan")
@login_required
@roles_required("Master")
def api_plan(id_tienda):
    try:
        plan_id = master_service.cambiar_plan(id_tienda, _json().get("plan_id"))
    except _ERRORES as exc:
        return _error(exc)
    return _ok(f"Plan cambiado a {plan_service.PLANES[plan_id]['nombre']}.")


@master.post("/api/master/negocios/<int:id_tienda>/montaje")
@login_required
@roles_required("Master")
def api_montaje(id_tienda):
    try:
        total = master_service.marcar_montajes_pagados(id_tienda, session["id_usuario"])
    except _ERRORES as exc:
        return _error(exc)
    return _ok(f"Montaje cobrado: {fmt_money(total)}.")


@master.post("/api/master/negocios/<int:id_tienda>/renovar")
@login_required
@roles_required("Master")
def api_renovar(id_tienda):
    data = _json()
    try:
        fin = master_service.renovar(
            id_tienda, data.get("meses"), data.get("monto"), data.get("nota"), session["id_usuario"]
        )
    except _ERRORES as exc:
        return _error(exc)
    return _ok(f"Pago registrado. Suscripción activa hasta {fin.strftime('%d/%m/%Y')}.")


@master.put("/api/master/negocios/<int:id_tienda>/vencimiento")
@login_required
@roles_required("Master")
def api_vencimiento(id_tienda):
    try:
        fecha = master_service.fijar_vencimiento(id_tienda, _json().get("fecha"))
    except _ERRORES as exc:
        return _error(exc)
    return _ok(f"Ahora vence el {fecha.strftime('%d/%m/%Y')}.")


@master.post("/api/master/negocios/<int:id_tienda>/suspender")
@login_required
@roles_required("Master")
def api_suspender(id_tienda):
    try:
        master_service.cambiar_estado(id_tienda, suspender=True)
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Negocio suspendido. Su equipo ya no puede entrar.")


@master.post("/api/master/negocios/<int:id_tienda>/reactivar")
@login_required
@roles_required("Master")
def api_reactivar(id_tienda):
    try:
        master_service.cambiar_estado(id_tienda, suspender=False)
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Negocio reactivado.")


@master.delete("/api/master/negocios/<int:id_tienda>")
@login_required
@roles_required("Master")
def api_eliminar(id_tienda):
    try:
        master_service.eliminar_negocio(id_tienda)
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Negocio eliminado.", redirect="/panel-master")


# ── Usuarios ──────────────────────────────────────────────────────────

@master.post("/api/master/negocios/<int:id_tienda>/usuarios")
@login_required
@roles_required("Master")
def api_usuario_crear(id_tienda):
    try:
        master_service.crear_usuario(id_tienda, _json())
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Usuario creado. Pásale su correo y su contraseña.", 201)


@master.put("/api/master/usuarios/<int:id_usuario>")
@login_required
@roles_required("Master")
def api_usuario_editar(id_usuario):
    try:
        master_service.editar_usuario(session["id_usuario"], id_usuario, _json())
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Usuario actualizado.")


@master.put("/api/master/usuarios/<int:id_usuario>/clave")
@login_required
@roles_required("Master")
def api_usuario_clave(id_usuario):
    data = _json()
    try:
        nuevo_hash = master_service.cambiar_clave(id_usuario, data.get("password"), data.get("confirm_password"))
    except _ERRORES as exc:
        return _error(exc)
    if id_usuario == session["id_usuario"]:
        # El Master que cambia su propia clave sigue dentro en esta sesion.
        session["huella"] = huella_clave(nuevo_hash)
    return _ok("Contraseña cambiada. Sus sesiones abiertas se cerraron.")


@master.delete("/api/master/usuarios/<int:id_usuario>")
@login_required
@roles_required("Master")
def api_usuario_desactivar(id_usuario):
    try:
        master_service.desactivar_usuario(session["id_usuario"], id_usuario)
    except _ERRORES as exc:
        return _error(exc)
    return _ok("Usuario desactivado. Su historial se conserva.")
