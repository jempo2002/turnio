from __future__ import annotations

import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

from app.performance import init_rendimiento
from app.security import es_desarrollo, init_security
from app.utils.decorators import _is_api_request, log_seguridad
from database import get_db, init_pool_from_app

# Antes del Limiter: su storage_uri se lee al importar, no en create_app.
load_dotenv()

csrf = CSRFProtect()
server_session = Session()
# Redis se usa solo para dos cosas: las sesiones (Flask-Session) y estos
# contadores de intentos. Sin limites globales: el panel hace muchas peticiones
# legitimas; los limites van en las rutas de login, recuperacion y reservas
# publicas (app/routes/publico.py). memory:// solo sirve en desarrollo: cuenta
# por worker y se pierde al reiniciar.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.getenv("REDIS_URL") or "memory://",
)


def _required_env(name: str, allow_empty: bool = False) -> str:
    value = os.getenv(name)
    if value is None or (not allow_empty and value.strip() == ""):
        raise RuntimeError(f"Falta la variable de entorno: {name}")
    return value


def _required_int_env(name: str) -> int:
    raw = _required_env(name)
    if not raw.strip().isdigit():
        raise RuntimeError(f"Entero invalido en la variable de entorno: {name}")
    return int(raw)


def create_app() -> Flask:
    """Application factory: configura extensiones y registra los blueprints."""
    load_dotenv()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url and not es_desarrollo():
        # En produccion con varios workers, sesiones en disco y contadores en
        # memoria no se comparten: el login fallaria al azar y el limite de
        # intentos se multiplicaria por worker.
        raise RuntimeError("Falta REDIS_URL: en produccion las sesiones y los limites van en Redis.")

    app.config.update(
        SECRET_KEY=_required_env("SECRET_KEY"),
        SESSION_COOKIE_NAME="turnio_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv("SESSION_HORAS") or 12)),
        SESSION_TYPE="redis" if redis_url else "filesystem",
        SESSION_KEY_PREFIX="turnio:sesion:",
        DB_HOST=_required_env("DB_HOST"),
        DB_PORT=_required_int_env("DB_PORT"),
        DB_USER=_required_env("DB_USER"),
        DB_PASSWORD=_required_env("DB_PASSWORD", allow_empty=True),
        DB_NAME=_required_env("DB_NAME"),
        # Lo mas grande que se sube es una imagen de 2 MB (imagen_service).
        MAX_CONTENT_LENGTH=3 * 1024 * 1024,
    )
    if redis_url:
        import redis

        app.config["SESSION_REDIS"] = redis.from_url(redis_url)

    # Los WARNING de seguridad (log_seguridad) salen por stderr: gunicorn los
    # recoge con --error-logfile -.
    app.logger.setLevel(logging.INFO)

    csrf.init_app(app)
    server_session.init_app(app)
    limiter.init_app(app)
    init_security(app)
    init_rendimiento(app)
    init_pool_from_app(app)

    from app.routes.agenda import agenda
    from app.routes.auth import auth
    from app.routes.caja import caja
    from app.routes.catalogo import catalogo
    from app.routes.core import core
    from app.routes.master import master
    from app.routes.negocio import negocio
    from app.routes.panel import panel
    from app.routes.publico import publico
    from app.routes.pwa import pwa

    app.register_blueprint(agenda)
    app.register_blueprint(auth)
    app.register_blueprint(caja)
    app.register_blueprint(catalogo)
    app.register_blueprint(core)
    app.register_blueprint(master)
    app.register_blueprint(negocio)
    app.register_blueprint(panel)
    app.register_blueprint(publico)
    app.register_blueprint(pwa)

    from app.utils.helpers import fmt_money

    app.add_template_filter(fmt_money, "pesos")

    @app.context_processor
    def _contexto_sesion():
        # Lo deja login_required en `g`; paginas publicas: sin aviso ni bloqueo.
        return {
            "tienda_vencida": g.get("tienda_vencida", False),
            "dias_suscripcion": g.get("dias_suscripcion"),
            "usuario": {
                "nombre": session.get("nombre_completo", ""),
                "rol": session.get("rol", ""),
                "sede": session.get("nombre_sede"),
            },
        }

    @app.get("/")
    def index():
        # Landing publica (T9). Con sesion abierta, directo al panel: es lo
        # que abre la app instalada si el navegador la arranca en la raiz.
        if session.get("id_usuario"):
            return redirect(url_for("core.inicio"))
        return render_template("landing.html")

    @app.get("/health")
    # El healthcheck de Railway entra por la red interna en http y sin
    # X-Forwarded-Proto: con force_https recibiria un 301 y el despliegue se
    # marcaria como caido (le paso a jemPOS). Solo esta ruta queda exenta.
    @app.extensions["talisman"](force_https=False)
    def health() -> tuple[dict, int]:
        """Vivo y con base: un despliegue sin MySQL no recibe trafico."""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchall()
            finally:
                conn.close()
        except Exception:
            app.logger.exception("health: sin base de datos")
            return {"ok": False, "app": "Turnio", "db": False}, 503
        return {"ok": True, "app": "Turnio"}, 200

    @app.errorhandler(429)
    def rate_limit_exceeded(_err):
        log_seguridad("rate_limit")
        msg = "Demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo."
        if request.endpoint == "publico.api_reservar":
            msg = ("Demasiados intentos de reserva. Espera un rato; si necesitas otra cita hoy, "
                   "escríbele al negocio por WhatsApp.")
        if not _is_api_request():
            # Formulario de login o recuperacion: volver a la pagina con aviso.
            flash(msg, "warning")
            return redirect(request.path)
        return jsonify({"ok": False, "msg": msg}), 429

    @app.errorhandler(413)
    def archivo_muy_grande(_err):
        return jsonify({"ok": False, "msg": "La imagen pesa demasiado. Usa una de menos de 3 MB."}), 413

    @app.errorhandler(500)
    def error_interno(_err):
        # Flask ya dejo la traza en el log; al usuario, nada interno.
        if _is_api_request():
            return jsonify({"ok": False, "msg": "Algo falló de nuestro lado. No es tu culpa: intenta de nuevo en un momento."}), 500
        return "Algo falló de nuestro lado. No es tu culpa: recarga la página en un momento.", 500

    @app.after_request
    def _log_ids_ajenos(response):
        # 404 autenticado en una API = ID inexistente o de otra tienda (los
        # servicios filtran por id_tienda). Muchos seguidos = enumeracion.
        if response.status_code == 404 and session.get("id_usuario") and _is_api_request():
            log_seguridad("recurso_no_encontrado")
        return response

    return app
