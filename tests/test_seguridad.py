"""T10: lo que tiene que seguir cierto en produccion detras del proxy de Railway.

- ProxyFix: el limite de intentos cuenta por la IP real del cliente (la que
  agrega el proxy al final de X-Forwarded-For), no por la del proxy, y un
  X-Forwarded-For inventado por el cliente no le da intentos nuevos.
- CORS cerrado: la API no responde cabeceras Access-Control-* a otro origen.
- /health publico y sin sesion.
- Nada de HTML sin escapar: ni `|safe`/`Markup` en las plantillas ni
  innerHTML en el JS de la app (el prototipo de la raiz escapa con esc()).
"""
from __future__ import annotations

import os
import re

import pytest

from conftest import RAIZ

PROXY = "10.0.0.1"  # la IP con la que el proxy de Railway llega a gunicorn


@pytest.fixture
def app_produccion(db, monkeypatch):
    """La app como corre en Railway: sin FLASK_ENV de desarrollo, con Redis."""
    if not os.getenv("TEST_REDIS_URL"):
        pytest.skip("sin TEST_REDIS_URL: produccion exige Redis")
    from app import create_app, limiter

    monkeypatch.setenv("FLASK_ENV", "production")
    aplicacion = create_app()
    aplicacion.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    limiter.reset()
    return aplicacion


def _login(cliente, xff, correo):
    return cliente.post(
        "/login",
        json={"correo": correo, "contrasena": "Mala1234"},
        headers={"X-Forwarded-For": xff, "X-Forwarded-Proto": "https"},
        environ_base={"REMOTE_ADDR": PROXY},
    )


def test_limite_de_login_por_ip_real_detras_del_proxy(app_produccion):
    cliente = app_produccion.test_client()
    # Un correo distinto por intento: aqui solo cuenta el limite por IP.
    codigos = [_login(cliente, "200.1.1.1", f"a{i}@turnio.co").status_code for i in range(6)]
    assert 429 not in codigos[:5], codigos
    assert codigos[5] == 429
    # Otro cliente detras del mismo proxy no queda bloqueado por el primero.
    assert _login(cliente, "200.2.2.2", "b@turnio.co").status_code != 429


def test_x_forwarded_for_inventado_no_da_intentos_nuevos(app_produccion):
    cliente = app_produccion.test_client()
    # El cliente manda su propio X-Forwarded-For; el proxy agrega la IP real al final.
    codigos = [
        _login(cliente, f"1.2.3.{i}, 200.1.1.1", f"a{i}@turnio.co").status_code for i in range(6)
    ]
    assert codigos[5] == 429, codigos


def test_produccion_redirige_http_a_https(app_produccion):
    r = app_produccion.test_client().get("/login", environ_base={"REMOTE_ADDR": PROXY})
    assert r.status_code in (301, 302) and r.location.startswith("https://")
    r = app_produccion.test_client().get(
        "/login", headers={"X-Forwarded-Proto": "https"}, environ_base={"REMOTE_ADDR": PROXY}
    )
    assert r.status_code == 200
    assert "max-age=31536000" in r.headers["Strict-Transport-Security"]


def test_health_responde_por_http_interno_en_produccion(app_produccion):
    """El healthcheck de Railway no manda X-Forwarded-Proto: no se redirige."""
    r = app_produccion.test_client().get("/health", environ_base={"REMOTE_ADDR": PROXY})
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_health_sin_base_responde_503(client, monkeypatch):
    import app as paquete

    def sin_base():
        raise RuntimeError("sin MySQL")

    monkeypatch.setattr(paquete, "get_db", sin_base)
    assert client.get("/health").status_code == 503


def test_health_responde_sin_sesion(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["ok"] is True


@pytest.mark.parametrize("ruta", ["/api/citas", "/health", "/login"])
def test_cors_cerrado(client, ruta):
    origen = {"Origin": "https://otro-sitio.com"}
    for r in (client.get(ruta, headers=origen), client.options(ruta, headers=origen)):
        assert not [h for h in r.headers.keys() if h.lower().startswith("access-control-")], ruta


def _archivos(carpeta, extension):
    for raiz, _dirs, nombres in os.walk(os.path.join(RAIZ, carpeta)):
        for nombre in nombres:
            if nombre.endswith(extension):
                ruta = os.path.join(raiz, nombre)
                with open(ruta, encoding="utf-8") as f:
                    yield os.path.relpath(ruta, RAIZ), f.read()


def test_plantillas_no_desactivan_el_escape():
    peligroso = re.compile(r"\|\s*safe\b|autoescape\s+false|Markup\(")
    hallazgos = [
        ruta
        for carpeta, ext in (("templates", ".html"), ("app", ".py"))
        for ruta, texto in _archivos(carpeta, ext)
        if peligroso.search(texto)
    ]
    assert not hallazgos, f"HTML sin escapar en {hallazgos}: usa texto o escapa el dato"


def test_js_de_la_app_no_inyecta_html():
    peligroso = re.compile(r"\.(innerHTML|outerHTML)\s*\+?=|insertAdjacentHTML|document\.write")
    # static/lib/ es codigo de terceros (html5-qrcode, minificado): no se edita.
    # El panel pinta HTML solo con T.h (escapa cada dato) y T.pintar (turnio.js).
    hallazgos = [
        ruta for ruta, texto in _archivos("static", ".js")
        if f"{os.sep}lib{os.sep}" not in ruta and peligroso.search(texto)
    ]
    assert not hallazgos, f"innerHTML en {hallazgos}: usa textContent, createElement o T.h + T.pintar"
