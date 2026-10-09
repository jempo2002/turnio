"""T7: el panel servido por Flask, sus permisos por rol, la CSP y la cuenta."""
import os
import re

from conftest import CLAVE, RAIZ, entrar

PAGINAS = ("/citas", "/caja", "/inventario", "/ajustes")


def _negocio(crear):
    id_tienda, ids = crear.tienda("pro", nombre="Barberia Norte")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    crear.usuario("ana@turnio.co", "Recepcion", id_tienda, ids[0])
    crear.usuario("carlos@turnio.co", "Profesional", id_tienda, ids[0])
    return id_tienda


def test_cada_rol_ve_sus_pestanas(app, crear):
    _negocio(crear)
    permitidas = {
        "admin@turnio.co": PAGINAS,
        "ana@turnio.co": PAGINAS,
        "carlos@turnio.co": ("/citas", "/ajustes"),
    }
    for correo, suyas in permitidas.items():
        client = app.test_client()
        assert entrar(client, correo).location.endswith("/citas")
        for pagina in PAGINAS:
            r = client.get(pagina)
            if pagina in suyas:
                assert r.status_code == 200, (correo, pagina)
                html = r.get_data(as_text=True)
                assert "Barberia Norte" in html
                # La barra inferior solo trae lo que el rol puede abrir.
                assert all((f'href="{p}"' in html) == (p in suyas) for p in PAGINAS), (correo, pagina)
            else:
                assert r.status_code == 302 and r.location.endswith("/inicio"), (correo, pagina)


def test_inicio_lleva_a_la_agenda_y_sin_sesion_al_login(client, crear):
    _negocio(crear)
    for pagina in PAGINAS:
        assert client.get(pagina).location.endswith("/login")
    entrar(client, "carlos@turnio.co")
    assert client.get("/inicio").location.endswith("/citas")


def test_paginas_cumplen_la_csp(client, crear):
    """Sin JS ni estilos inline y sin CDN: la CSP de app/security.py los bloquea."""
    _negocio(crear)
    entrar(client, "admin@turnio.co")
    for pagina in (*PAGINAS, "/login"):
        if pagina == "/login":
            client.get("/login")  # cierra la sesion; la pagina igual se revisa
        html = client.get(pagina).get_data(as_text=True)
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), pagina
        assert not re.search(r"\sstyle=", html), pagina
        assert not re.search(r"\son[a-z]+=", html), pagina
        assert "cdn.tailwindcss.com" not in html, pagina
        for recurso in re.findall(r'(?:src|href)="(/static/[^"?]+)', html):
            assert os.path.exists(os.path.join(RAIZ, recurso.lstrip("/"))), recurso
    assert "default-src 'self'" in client.get("/login").headers["Content-Security-Policy"]


def test_el_panel_no_guarda_datos_en_el_navegador():
    # Lo único permitido: la marca de "guía ya vista" (T.guia), que es del
    # dispositivo y no del negocio. Siempre con la llave GUIA + clave.
    carpeta = os.path.join(RAIZ, "static", "js", "panel")
    for nombre in os.listdir(carpeta):
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
            for linea in f:
                if re.search(r"localStorage\s*[.\[)]", linea):
                    assert nombre == "turnio.js" and "GUIA" in linea, (nombre, linea)


def test_cambiar_clave_pide_la_actual(app, client, crear):
    _negocio(crear)
    entrar(client, "carlos@turnio.co")
    r = client.put("/api/cuenta/clave", json={"actual": "otra", "nueva": "Nueva1234"})
    assert r.status_code == 400 and r.get_json()["field"] == "actual"
    r = client.put("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "corta"})
    assert r.status_code == 400 and r.get_json()["field"] == "nueva"
    assert client.put("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "Nueva1234"}).status_code == 200

    otro = app.test_client()
    assert entrar(otro, "carlos@turnio.co").location.endswith("/login")
    assert entrar(otro, "carlos@turnio.co", "Nueva1234").location.endswith("/citas")


def test_cambiar_clave_requiere_sesion(client):
    assert client.put("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "Nueva1234"}).status_code == 401
