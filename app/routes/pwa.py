"""App instalable (T9): manifiesto, service worker, pagina sin conexion e
icono de la raiz.

Turnio se instala desde el navegador del celular ("Agregar a pantalla de
inicio") y abre como app, sin barra del navegador, en /inicio. No hay tienda
de apps ni modo offline de datos: la agenda y la caja necesitan red (las
reservas online llegan al servidor). El service worker solo guarda los
estaticos versionados y una pagina "Sin conexion" para cuando no hay senal.
"""
from __future__ import annotations

import json
import os

from flask import Blueprint, Response, current_app, render_template, send_from_directory, url_for

from app.performance import huella

pwa = Blueprint("pwa", __name__)

NOMBRE = "Turnio"
FONDO = "#F1F5F9"   # bg-slate-100 del panel: la pantalla de bienvenida no parpadea
# Lo que el service worker guarda al instalarse. Todo lo demas (paginas,
# /api, logos) va siempre a la red.
PRECARGA = ("css/panel.css", "js/panel/turnio.js", "js/pwa.js", "img/icono-192.png")


@pwa.get("/manifest.webmanifest")
def manifest():
    icono = lambda archivo: url_for("static", filename=f"img/{archivo}")  # noqa: E731
    datos = {
        "id": "/inicio",
        "name": NOMBRE,
        "short_name": NOMBRE,
        "description": "Agenda, reservas y caja de tu negocio de belleza.",
        "lang": "es-CO",
        "dir": "ltr",
        "start_url": "/inicio",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": FONDO,
        "theme_color": FONDO,
        "categories": ["business", "productivity"],
        "icons": [
            {"src": icono("icono-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icono("icono-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icono("icono-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": icono("icono.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
        # Mantener presionado el icono: atajos a las pantallas de todos los dias.
        "shortcuts": [
            {"name": "Citas de hoy", "url": "/citas", "icons": [{"src": icono("icono-192.png"), "sizes": "192x192"}]},
            {"name": "Caja", "url": "/caja", "icons": [{"src": icono("icono-192.png"), "sizes": "192x192"}]},
        ],
    }
    resp = Response(json.dumps(datos, ensure_ascii=False), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@pwa.get("/sw.js")
def service_worker():
    """En la raiz para que su alcance sea todo el sitio. Se arma con las URLs
    versionadas: un deploy que cambia un estatico cambia este archivo, y el
    navegador instala el nuevo y borra la cache vieja."""
    precarga = [url_for("pwa.offline")] + [url_for("static", filename=f) for f in PRECARGA]
    version = huella(os.path.join(current_app.root_path, "..", "templates", "pwa", "sw.js")) or ""
    version += "-" + "-".join(
        huella(os.path.join(current_app.static_folder, f)) or "" for f in PRECARGA
    )
    js = render_template("pwa/sw.js", version=version, precarga=precarga)
    resp = Response(js, mimetype="text/javascript")
    # Siempre fresco: es lo que avisa al navegador que hay version nueva.
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@pwa.get("/offline")
def offline():
    return render_template("pwa/offline.html")


@pwa.get("/favicon.ico")
def favicon():
    """El navegador lo pide por su cuenta, sin mirar los <link> del HTML."""
    return send_from_directory(
        os.path.join(current_app.static_folder, "img"), "favicon.ico",
        mimetype="image/x-icon", max_age=60 * 60 * 24 * 30,
    )
