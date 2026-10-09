from __future__ import annotations

import hmac

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from app import limiter
from app.security import cerrar_sesion_publica
from app.services import master_service, plan_service, usuario_service
from app.services.auth_service import (
    create_reset_token,
    decode_invite_token,
    decode_reset_token,
    fijar_sede,
    first_password_policy_error,
    huella_clave,
    initialize_user_session,
    is_valid_email,
    resolve_post_login_redirect,
    sede_inicial,
    sedes_activas,
    send_recovery_email,
)
from app.utils.decorators import log_seguridad, login_required
from app.utils.validation import parse_int
from database import get_db

auth = Blueprint("auth", __name__)
LOGIN_RATE_LIMIT = "5 per minute"
# Por cuenta, no por IP: frena la fuerza bruta distribuida contra un correo.
LOGIN_CUENTA_RATE_LIMIT = "10 per 15 minutes"
# Hash valido para comparar cuando el correo no existe: iguala el tiempo de
# respuesta y no delata que cuentas existen.
_HASH_SENUELO = generate_password_hash("turnio-senuelo")
_CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos. Revisa que estén bien escritos o toca «¿Olvidaste tu contraseña?»."
_SEDE_INACTIVA = "Tu sede ya no está activa. Pídele al administrador que te asigne otra."
_USUARIO_LOGIN_SQL = (
    "SELECT id_usuario, id_tienda, id_sede, nombre_completo, clave_hash, rol, estado_activo "
    "FROM usuarios WHERE correo = %s LIMIT 1"
)


def _datos_peticion() -> dict:
    return (request.get_json(silent=True) if request.is_json else request.form) or {}


def _correo_login() -> str:
    return "login:" + str(_datos_peticion().get("correo", "")).strip().lower()[:150]


def _error_login(msg: str, status: int, field: str | None = None):
    if request.is_json:
        cuerpo = {"ok": False, "msg": msg}
        if field:
            cuerpo["field"] = field
        return jsonify(cuerpo), status
    flash(msg, "error")
    return redirect(url_for("auth.login"))


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT, methods=["POST"])
@limiter.limit(LOGIN_CUENTA_RATE_LIMIT, methods=["POST"], key_func=_correo_login)
def login():
    if request.method == "GET":
        # Ruta publica: abrir el login destruye cualquier sesion activa en vez
        # de reenviar adentro. Dejar la sesion anterior viva permitia seguir
        # usandola con el boton "atras". Se usa el helper para no borrar los
        # flashes que trae el redirect.
        cerrar_sesion_publica()
        return render_template("auth/login.html")

    data = _datos_peticion()
    correo = str(data.get("correo", "")).strip().lower()
    contrasena = str(data.get("contrasena", ""))

    if not correo or not contrasena:
        return _error_login("Escribe tu correo y tu contraseña para entrar.", 400)
    if len(correo) > 150 or not is_valid_email(correo):
        return _error_login("Revisa el correo: debe verse así, nombre@gmail.com.", 400)
    if len(contrasena) > 128:
        return _error_login("La contraseña es muy larga: usa máximo 128 caracteres.", 400)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(_USUARIO_LOGIN_SQL, (correo,))
        user = cur.fetchone()
    finally:
        conn.close()

    # Mismo mensaje y mismo coste de hash exista o no el correo.
    clave_ok = check_password_hash(user["clave_hash"] if user else _HASH_SENUELO, contrasena)
    if not user or not clave_ok:
        log_seguridad("login_fallido", correo=correo, existe=bool(user))
        return _error_login(_CREDENCIALES_INVALIDAS, 401, field="contrasena")

    if not user["estado_activo"]:
        return _error_login("Cuenta desactivada. Contacta al administrador.", 403)

    redirect_url = _abrir_sesion(user)
    if not redirect_url:
        return _error_login(_SEDE_INACTIVA, 403)
    if request.is_json:
        return jsonify({"ok": True, "redirect": redirect_url})
    return redirect(redirect_url)


def _abrir_sesion(user: dict) -> str | None:
    """Abre la sesion de `user` (ya autenticado) y devuelve a donde ir, o None
    si su sede ya no esta activa. La usan el login, el registro y la
    invitacion."""
    sede = sede_inicial(user)
    if user["id_sede"] and not sede:
        return None

    initialize_user_session(session, user, sede)
    # ID de sesion nuevo al autenticarse: anula una fijacion de sesion previa.
    # (Solo las interfaces de Flask-Session lo tienen.)
    if hasattr(current_app.session_interface, "regenerate"):
        current_app.session_interface.regenerate(session)

    if user["rol"] != "Master" and not sede:
        return url_for("auth.seleccionar_sede")
    return resolve_post_login_redirect(user["rol"])


# Registro abierto: cualquiera puede crear su negocio y arranca con la prueba
# gratis (plan_service.DIAS_PRUEBA dias del Pro). Limite por IP para frenar
# altas en masa; el campo trampa `sitio_web` (oculto) atrapa bots simples.
REGISTRO_RATE_LIMIT = "5 per hour"
_CAMPOS_REGISTRO = ("nombre_negocio", "tipo_negocio", "telefono", "admin_nombre", "admin_cc", "admin_correo")


def _error_registro(msg: str, status: int, datos: dict):
    if request.is_json:
        return jsonify({"ok": False, "msg": msg}), status
    flash(msg, "error")
    return _form_registro(datos), status


def _form_registro(datos: dict | None = None):
    previos = {k: str((datos or {}).get(k, ""))[:150] for k in _CAMPOS_REGISTRO}
    return render_template(
        "auth/registro.html",
        tipos=master_service.TIPOS_NEGOCIO,
        dias_prueba=plan_service.DIAS_PRUEBA,
        plan_prueba=plan_service.PLANES[plan_service.PLAN_PRUEBA]["nombre"],
        previos=previos,
    )


@auth.route("/registro", methods=["GET", "POST"])
@limiter.limit(REGISTRO_RATE_LIMIT, methods=["POST"])
def registro():
    if request.method == "GET":
        cerrar_sesion_publica()
        return _form_registro()

    data = dict(_datos_peticion())
    if data.get("sitio_web"):
        log_seguridad("registro_trampa")
        return _error_registro("No se pudo crear la cuenta.", 400, {})
    if not str(data.get("telefono", "")).strip():
        return _error_registro("El WhatsApp del negocio es requerido.", 400, data)
    if str(data.get("admin_password", "")) != str(data.get("confirm_password", "")):
        return _error_registro("Las contraseñas no coinciden. Escríbela igual en los dos campos.", 400, data)
    try:
        id_tienda = master_service.crear_negocio(data)
    except (ValueError, master_service.MasterError) as exc:
        return _error_registro(str(exc), getattr(exc, "status", 400), data)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        # crear_negocio deja un solo usuario: el Admin dueno.
        cur.execute(
            "SELECT id_usuario, id_tienda, id_sede, nombre_completo, rol FROM usuarios WHERE id_tienda = %s LIMIT 1",
            (id_tienda,),
        )
        user = cur.fetchone()
    finally:
        conn.close()
    current_app.logger.info("Negocio registrado id_tienda=%s", id_tienda)
    destino = _abrir_sesion(user)
    if request.is_json:
        return jsonify({"ok": True, "id_tienda": id_tienda, "redirect": destino}), 201
    flash(
        f"Listo, tu negocio ya está en Turnio. Tienes {plan_service.DIAS_PRUEBA} días gratis del plan "
        f"{plan_service.PLANES[plan_service.PLAN_PRUEBA]['nombre']}.",
        "success",
    )
    return redirect(destino)


@auth.route("/api/auth/register", methods=["POST"])
def api_registro():
    # Sin limite propio: el de registro() ya cuenta esta llamada (con los dos
    # contaba doble).
    return registro()


@auth.route("/invitacion/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def invitacion(token):
    """Quien fue invitado al equipo elige su contrasena y entra."""
    try:
        correo, huella = decode_invite_token(current_app.secret_key, token)
    except (SignatureExpired, BadSignature):
        usuario = None
    else:
        usuario = usuario_service.invitacion_vigente(correo, huella)
    if not usuario:
        cerrar_sesion_publica()
        flash("La invitación venció o ya se usó. Pide al administrador un enlace nuevo.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        cerrar_sesion_publica()
        return render_template("auth/invitacion.html", token=token, usuario=usuario)

    try:
        usuario_service.aceptar_invitacion(usuario, request.form.get("password"), request.form.get("confirm_password"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.invitacion", token=token))
    except usuario_service.UsuarioError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.login"))
    destino = _abrir_sesion(usuario)
    if not destino:
        flash(_SEDE_INACTIVA, "error")
        return redirect(url_for("auth.login"))
    return redirect(destino)


@auth.route("/seleccionar-sede", methods=["GET", "POST"])
@login_required
def seleccionar_sede():
    """El Admin de un negocio con varias sedes elige en cual trabaja. Los
    demas roles estan atados a la suya y no pasan por aqui."""
    if session.get("rol") == "Master":
        return redirect(resolve_post_login_redirect("Master"))
    sedes = sedes_activas(session["id_tienda"])
    if request.method == "GET":
        return render_template("auth/seleccionar_sede.html", sedes=sedes, sede_actual=session.get("id_sede"))

    data = _datos_peticion()
    try:
        id_sede = parse_int(data.get("id_sede"), "Sede", min_value=1)
    except ValueError as exc:
        return _respuesta_sede(str(exc), 400)
    sede = next((s for s in sedes if s["id_sede"] == id_sede), None)
    # Quien esta atado a una sede (Recepcion, Profesional) no se cambia solo.
    if not sede or g.sede_fija not in (None, id_sede):
        log_seguridad("sede_ajena", id_sede=id_sede)
        return _respuesta_sede("Sede no encontrada.", 404)
    fijar_sede(session, sede)
    destino = resolve_post_login_redirect(session.get("rol"))
    if request.is_json:
        return jsonify({"ok": True, "redirect": destino, "msg": f"Trabajando en {sede['nombre']}."})
    return redirect(destino)


def _respuesta_sede(msg: str, status: int):
    if request.is_json:
        return jsonify({"ok": False, "msg": msg}), status
    flash(msg, "error")
    return redirect(url_for("auth.seleccionar_sede"))


@auth.route("/logout", methods=["POST"])
def logout():
    # POST + CSRF: un <img src="/logout"> en otra pagina no saca al usuario.
    session.clear()
    return redirect(url_for("auth.login"))


@auth.route("/api/auth/login", methods=["POST"])
@limiter.limit(LOGIN_RATE_LIMIT)
def api_login():
    return login()


@auth.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/login"})


@auth.route("/olvide-password", methods=["GET", "POST"])
@limiter.limit("3 per minute; 10 per hour", methods=["POST"])
def olvide_password():
    if request.method == "POST":
        correo = str(request.form.get("correo", "")).strip().lower()
        if correo:
            if len(correo) > 150 or not is_valid_email(correo):
                flash("Escribe un correo válido, por ejemplo nombre@gmail.com.", "error")
                return redirect(url_for("auth.olvide_password"))
            conn = get_db()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT correo, clave_hash FROM usuarios WHERE correo = %s AND estado_activo = 1 LIMIT 1",
                    (correo,),
                )
                user = cur.fetchone()
            finally:
                conn.close()

            if user:
                token = create_reset_token(current_app.secret_key, correo, user["clave_hash"])
                enlace = url_for("auth.reset_password", token=token, _external=True)
                # En segundo plano: los fallos de SMTP quedan en el log.
                send_recovery_email(correo, enlace)

        flash("Si ese correo tiene cuenta, te llegó un enlace para crear una contraseña nueva. Revisa también la carpeta de spam.", "success")
        return redirect(url_for("auth.olvide_password"))

    return render_template("auth/olvide_password.html")


@auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password(token):
    try:
        correo, huella = decode_reset_token(current_app.secret_key, token)
    except (SignatureExpired, BadSignature):
        flash("Ese enlace ya venció o ya se usó. Pide uno nuevo en «¿Olvidaste tu contraseña?».", "error")
        return redirect(url_for("auth.login"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_usuario, correo, estado_activo, clave_hash FROM usuarios WHERE correo = %s LIMIT 1",
            (correo,),
        )
        user = cur.fetchone()
    finally:
        conn.close()

    if (
        not correo
        or not user
        or not user.get("estado_activo")
        or not hmac.compare_digest(huella, huella_clave(user["clave_hash"]))
    ):
        flash("Ese enlace ya venció o ya se usó. Pide uno nuevo en «¿Olvidaste tu contraseña?».", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = str(request.form.get("password", ""))
        confirm = str(request.form.get("confirm_password", ""))

        if password != confirm:
            flash("Las contraseñas no coinciden. Escríbela igual en los dos campos.", "error")
            return redirect(url_for("auth.reset_password", token=token))
        if len(password) > 128:
            flash("La contraseña es muy larga: usa máximo 128 caracteres.", "error")
            return redirect(url_for("auth.reset_password", token=token))
        pwd_error = first_password_policy_error(password)
        if pwd_error:
            flash(pwd_error, "error")
            return redirect(url_for("auth.reset_password", token=token))

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE usuarios SET clave_hash = %s, invitacion_pendiente = 0 WHERE id_usuario = %s AND correo = %s",
                (generate_password_hash(password), user["id_usuario"], user["correo"]),
            )
            conn.commit()
        finally:
            conn.close()

        flash("Listo, cambiaste tu contraseña. Ya puedes entrar con la nueva.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
