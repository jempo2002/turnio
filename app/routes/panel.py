"""Panel del negocio (T7): las pantallas del prototipo servidas por Flask.

Las paginas solo traen el esqueleto; los datos llegan por fetch a las APIs de
T4 a T6 (static/js/panel/). La sesion es la cookie de Flask de jemPOS Chef
(HttpOnly, revalidada en cada peticion, CSRF en las escrituras), no un JWT
en el navegador: un XSS no puede robarla y un usuario desactivado pierde el
acceso al instante.

Quien ve que:
  - Citas y Ajustes: todo el equipo. Ajustes del negocio y horario: Admin.
  - Caja e Inventario: Admin y Recepcion (las mismas reglas de sus APIs).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app import limiter
from app.services import local_service, plan_service, vertical_service
from app.services.auth_service import first_password_policy_error, huella_clave
from app.services.usuario_service import ROLES_NEGOCIO
from app.utils.decorators import log_seguridad, login_required, roles_required
from database import get_db

panel = Blueprint("panel", __name__)

_CAJA = ("Admin", "Recepcion")
# Cada pestana de la barra inferior y quien la ve (nav.js la pinta).
PESTANAS = (
    ("citas", "Citas", ROLES_NEGOCIO),
    ("caja", "Caja", _CAJA),
    ("inventario", "Inventario", _CAJA),
    ("ajustes", "Ajustes", ROLES_NEGOCIO),
)


def _yo() -> dict:
    """Lo que el JS necesita saber de la sesion (va en data-* del <body>)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT nombre_completo, correo, atiende FROM usuarios WHERE id_usuario = %s",
            (session["id_usuario"],),
        )
        u = cur.fetchone() or {}
    finally:
        conn.close()
    rol = session.get("rol")
    return {
        "id": session["id_usuario"],
        "nombre": u.get("nombre_completo") or session.get("nombre_completo", ""),
        "correo": u.get("correo", ""),
        "rol": rol,
        "atiende": bool(u.get("atiende")),
        "sede": session.get("nombre_sede") or "",
        "plan": plan_service.plan_de(g.plan_id)["nombre"],
        "funciones": " ".join(sorted(f for f in plan_service.NOMBRE_FUNCION if plan_service.tiene_funcion(g.plan_id, f))),
        "pestanas": " ".join(clave for clave, _t, roles in PESTANAS if rol in roles),
        # Admin sin sede fija: puede cambiar de sede.
        "cambia_sede": rol == "Admin" and g.get("sede_fija") is None,
    }


def _pagina(plantilla: str, activa: str, **extra):
    yo = _yo()
    negocio = local_service.datos_negocio(session["id_tienda"])
    return render_template(plantilla, yo=yo, negocio=negocio, activa=activa, **extra)


@panel.get("/citas")
@login_required
@roles_required(*ROLES_NEGOCIO)
def citas():
    return _pagina("panel/citas.html", "citas")


@panel.get("/caja")
@login_required
@roles_required(*_CAJA)
def caja():
    return _pagina("panel/caja.html", "caja")


@panel.get("/inventario")
@login_required
@roles_required(*_CAJA)
def inventario():
    return _pagina("panel/inventario.html", "inventario")


@panel.get("/ajustes")
@login_required
@roles_required(*ROLES_NEGOCIO)
def ajustes():
    plan = plan_service.plan_de(g.plan_id)
    funciones = [
        (texto, plan_service.tiene_funcion(g.plan_id, clave))
        for clave, texto in plan_service.NOMBRE_FUNCION.items()
    ]
    return _pagina("panel/ajustes.html", "ajustes", plan=plan, funciones=funciones, tipos=vertical_service.TIPOS_NEGOCIO)


# ── Cuenta propia ───────────────────────────────────────────────────

@panel.put("/api/cuenta/clave")
@login_required
@roles_required(*ROLES_NEGOCIO)
@limiter.limit("5 per minute; 20 per hour")
def api_cambiar_clave():
    """Body: {actual, nueva}. Pide la actual: una sesion abierta en un
    celular prestado no basta para quedarse con la cuenta."""
    data = request.get_json(silent=True) or {}
    actual = str(data.get("actual") or "")
    nueva = str(data.get("nueva") or "")
    if len(actual) > 128 or len(nueva) > 128:
        return jsonify({"ok": False, "msg": "La contraseña supera el máximo permitido."}), 400
    error = first_password_policy_error(nueva)
    if error:
        return jsonify({"ok": False, "msg": error, "field": "nueva"}), 400
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT clave_hash FROM usuarios WHERE id_usuario = %s", (session["id_usuario"],))
        fila = cur.fetchone()
        if not fila or not check_password_hash(fila["clave_hash"], actual):
            log_seguridad("cambio_clave_fallido")
            return jsonify({"ok": False, "msg": "La contraseña actual no es correcta.", "field": "actual"}), 400
        nuevo_hash = generate_password_hash(nueva)
        cur.execute(
            "UPDATE usuarios SET clave_hash = %s WHERE id_usuario = %s AND id_tienda = %s",
            (nuevo_hash, session["id_usuario"], session["id_tienda"]),
        )
        conn.commit()
    finally:
        conn.close()
    # Las otras sesiones de esta cuenta se cierran; esta sigue abierta.
    session["huella"] = huella_clave(nuevo_hash)
    return jsonify({"ok": True, "msg": "Contraseña actualizada."})
