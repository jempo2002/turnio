"""performance.py — compresion y cache de los archivos estaticos (T9).

Vive aparte, como app/security.py, para no engordar create_app. La
compresion es la de jemPOS (app/performance.py de alla); la version en la URL
de los estaticos es nueva.

1) Flask-Compress: zstd / brotli / gzip segun Accept-Encoding. Sobre HTML,
   CSS, JS y JSON ahorra ~70-80 %, lo que mas pesa en un celular de gama
   media con datos. PNG e .ico quedan fuera (ya vienen comprimidos). Con
   CSRF en el HTML no hay riesgo de BREACH: Flask-WTF vuelve a salar el token
   en cada peticion.

2) Version en la URL: url_for('static', ...) agrega ?v=<huella del archivo>.
   Esa URL cambia solo cuando cambia el archivo, asi que puede guardarse un
   ano en el navegador (immutable) sin quedar vieja despues de un deploy. En
   jemPOS CSS y JS revalidaban en cada pantalla (un 304 por archivo); aqui la
   segunda visita no pide nada. El service worker (templates/pwa/sw.js)
   guarda en su cache solo estas URLs versionadas.
"""
from __future__ import annotations

import hashlib
import os

from flask import request
from flask_compress import Compress

UN_ANIO = 60 * 60 * 24 * 365
# ruta -> (mtime, tamano, huella). La huella se recalcula solo si el archivo
# cambio (en produccion nunca: el disco de Railway es el del deploy).
_huellas: dict[str, tuple[float, int, str]] = {}


def huella(ruta: str) -> str | None:
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    guardada = _huellas.get(ruta)
    if guardada and guardada[:2] == (st.st_mtime, st.st_size):
        return guardada[2]
    with open(ruta, "rb") as f:
        valor = hashlib.sha256(f.read()).hexdigest()[:10]
    _huellas[ruta] = (st.st_mtime, st.st_size, valor)
    return valor


def init_rendimiento(app) -> None:
    # Una instancia por app (misma trampa que Talisman en app/security.py).
    Compress(app)

    @app.url_defaults
    def _version_estaticos(endpoint, values):
        if endpoint != "static" or "v" in values:
            return
        ruta = os.path.join(app.static_folder, values.get("filename", ""))
        v = huella(ruta)
        if v:
            values["v"] = v

    @app.after_request
    def _cachear_estaticos(response):
        if request.path.startswith("/static/") and request.args.get("v") and response.status_code in (200, 304):
            response.headers["Cache-Control"] = f"public, max-age={UN_ANIO}, immutable"
        return response
