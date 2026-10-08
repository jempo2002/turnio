"""Panel Master: negocios, planes y suscripciones (tomado de jemPOS Chef)."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.services import master_service, plan_service
from app.utils.decorators import login_required, roles_required
from app.utils.helpers import fmt_money, hoy_local

master = Blueprint("master", __name__)

_ERRORES = (ValueError, master_service.MasterError)


def _error(exc: Exception):
    return jsonify({"ok": False, "msg": str(exc)}), getattr(exc, "status", 400)


@master.get("/panel-master")
@login_required
@roles_required("Master")
def panel():
    negocios = master_service.listar_negocios()
    return render_template(
        "master/panel.html",
        negocios=negocios,
        tipos=master_service.TIPOS_NEGOCIO,
        planes=plan_service.PLANES,
        plan_prueba=plan_service.PLAN_PRUEBA,
        dias_prueba=plan_service.DIAS_PRUEBA,
        periodos=master_service.PERIODOS,
        mrr=sum(n["mensualidad"] for n in negocios if not n["en_prueba"]),
        montajes=sum(n["montaje_pendiente"] for n in negocios),
        hoy=hoy_local(),
    )


@master.post("/api/master/negocios")
@login_required
@roles_required("Master")
def api_crear():
    try:
        id_tienda = master_service.crear_negocio(request.get_json(silent=True) or {})
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "id_tienda": id_tienda, "msg": "Negocio creado con un mes de prueba."}), 201


@master.put("/api/master/negocios/<int:id_tienda>/plan")
@login_required
@roles_required("Master")
def api_plan(id_tienda):
    try:
        plan_id = master_service.cambiar_plan(id_tienda, (request.get_json(silent=True) or {}).get("plan_id"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": f"Plan cambiado a {plan_service.PLANES[plan_id]['nombre']}."})


@master.post("/api/master/negocios/<int:id_tienda>/montaje")
@login_required
@roles_required("Master")
def api_montaje(id_tienda):
    try:
        total = master_service.marcar_montajes_pagados(id_tienda)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": f"Montaje cobrado: {fmt_money(total)}."})


@master.post("/api/master/negocios/<int:id_tienda>/renovar")
@login_required
@roles_required("Master")
def api_renovar(id_tienda):
    try:
        fin = master_service.renovar(id_tienda, (request.get_json(silent=True) or {}).get("meses"))
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": f"Suscripcion activa hasta {fin.strftime('%d/%m/%Y')}."})


@master.delete("/api/master/negocios/<int:id_tienda>")
@login_required
@roles_required("Master")
def api_eliminar(id_tienda):
    try:
        master_service.eliminar_negocio(id_tienda)
    except _ERRORES as exc:
        return _error(exc)
    return jsonify({"ok": True, "msg": "Negocio eliminado."})
