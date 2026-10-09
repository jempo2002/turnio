"""T9: tipos de negocio (vocabulario, servicios y horario de arranque) y el
frontend de produccion (landing en Flask, app instalable, estaticos con
version y cache, sin terceros en la CSP)."""
import json
import os
import re

import pytest

from conftest import CLAVE, entrar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _registrar(client, tipo, nombre="Mi Negocio", correo="duena@negocio.co"):
    return client.post("/registro", data={
        "nombre_negocio": nombre, "tipo_negocio": tipo, "telefono": "300 111 2233",
        "admin_nombre": "Dueña", "admin_cc": "1144000111", "admin_correo": correo,
        "admin_password": CLAVE, "confirm_password": CLAVE,
    })


# ── Tipos de negocio ────────────────────────────────────────────────

def test_cada_tipo_del_enum_tiene_vertical_completa(crear):
    from app.services import vertical_service

    columna = crear.fila(
        "SELECT COLUMN_TYPE AS t FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tiendas' AND COLUMN_NAME = 'tipo_negocio'"
    )["t"]
    assert set(re.findall(r"'([a-z_]+)'", columna)) == set(vertical_service.VERTICALES)
    for clave, v in vertical_service.VERTICALES.items():
        assert len(v["horario"]) == 7, clave
        for nombre, minutos, precio in v["servicios"]:
            assert 5 <= minutos <= 720 and precio > 0 and len(nombre) <= 120, (clave, nombre)
    assert vertical_service.vocabulario("barberia")["Profesional"] == "Barbero"
    assert vertical_service.vocabulario("no-existe")["profesional"] == "profesional"


def test_registro_de_barberia_arranca_con_servicios_y_horario(client, crear):
    assert _registrar(client, "barberia", "Barbería El Cuartel").status_code == 302
    t = crear.fila("SELECT id_tienda FROM tiendas")
    servicios = crear.fila(
        "SELECT COUNT(*) AS n, SUM(pago_profesional) AS pago FROM servicios WHERE id_tienda = %s AND estado_activo = 1",
        (t["id_tienda"],),
    )
    assert servicios["n"] == 4 and servicios["pago"] == 0
    assert crear.fila("SELECT nombre FROM servicios WHERE nombre = 'Corte + barba'")
    # Barberia: hasta las 8 p. m. y el domingo en la manana.
    lunes = crear.fila("SELECT abierto, TIME_FORMAT(cierra, '%H:%i') AS cierra FROM horarios_sede WHERE dia = 0")
    domingo = crear.fila("SELECT abierto, TIME_FORMAT(cierra, '%H:%i') AS cierra FROM horarios_sede WHERE dia = 6")
    assert (lunes["abierto"], lunes["cierra"]) == (1, "20:00")
    assert (domingo["abierto"], domingo["cierra"]) == (1, "14:00")

    # El link de reservas ya ofrece los servicios del primer dia.
    datos = client.get("/api/publico/barberia-el-cuartel").get_json()
    sede = datos["sedes"][0]
    assert {s["nombre"] for s in sede["servicios"]} >= {"Corte de cabello", "Corte + barba"}
    assert len(sede["profesionales"]) == 1  # el dueno atiende desde el primer dia


def test_independiente_arranca_sin_servicios_y_con_horario_de_fabrica(client, crear):
    assert _registrar(client, "independiente").status_code == 302
    assert crear.fila("SELECT tipo_negocio FROM tiendas")["tipo_negocio"] == "independiente"
    assert crear.fila("SELECT COUNT(*) AS n FROM servicios")["n"] == 0
    domingo = crear.fila("SELECT abierto FROM horarios_sede WHERE dia = 6")
    assert domingo["abierto"] == 0


def test_el_panel_y_la_reserva_hablan_como_el_negocio(client, crear):
    _registrar(client, "unas", "Uñas Divinas")
    inventario = client.get("/inventario").get_data(as_text=True)
    assert 'placeholder="Ej. Semipermanente en manos"' in inventario
    assert "Pago al manicurista" in inventario
    citas = client.get("/citas").get_data(as_text=True)
    assert 'data-voc-profesional="manicurista"' in citas
    assert "<title>Citas · Uñas Divinas</title>" in citas

    client.post("/logout")
    reserva = client.get("/r/unas-divinas").get_data(as_text=True)
    assert "</span>Manicurista</legend>" in reserva


def test_sede_nueva_copia_el_horario_de_la_principal(client, crear, db):
    _registrar(client, "barberia", "Barbería Dos Sedes")
    db.cursor().execute("UPDATE tiendas SET plan_id = 'multisede'")
    r = client.post("/api/sedes", json={"nombre": "Norte"})
    assert r.status_code in (200, 201), r.get_json()
    norte = crear.fila("SELECT id_sede FROM sedes WHERE nombre = 'Norte'")["id_sede"]
    domingo = crear.fila(
        "SELECT abierto, TIME_FORMAT(cierra, '%H:%i') AS cierra FROM horarios_sede WHERE id_sede = %s AND dia = 6",
        (norte,),
    )
    assert (domingo["abierto"], domingo["cierra"]) == (1, "14:00")
    assert crear.fila("SELECT COUNT(*) AS n FROM horarios_sede WHERE id_sede = %s", (norte,))["n"] == 7


# ── Landing y app instalable ────────────────────────────────────────

def test_landing_en_la_raiz_y_panel_con_sesion(client, crear):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'name="robots"' not in html  # se indexa
    assert "cdn.tailwindcss.com" not in html and "<script>" not in html and "style=" not in html
    assert '/static/css/landing.css?v=' in html
    assert 'href="/registro"' in html and 'rel="manifest"' in html

    _registrar(client, "estetica")
    assert client.get("/").location.endswith("/inicio")


def test_manifiesto_instalable(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.mimetype == "application/manifest+json"
    m = json.loads(r.get_data(as_text=True))
    assert m["display"] == "standalone" and m["start_url"] == "/inicio" and m["lang"] == "es-CO"
    tamanos = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= tamanos
    for icono in m["icons"]:
        assert client.get(icono["src"]).status_code == 200, icono["src"]


def test_service_worker_en_la_raiz_y_sin_cache(client):
    r = client.get("/sw.js")
    js = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/javascript"
    assert r.headers["Cache-Control"] == "no-cache"
    assert "/offline" in js and "/static/css/panel.css?v=" in js
    # Nunca guarda la API ni las paginas con sesion.
    assert "'/static/'" in js and "searchParams.has('v')" in js
    assert client.get("/offline").status_code == 200
    assert client.get("/favicon.ico").mimetype == "image/x-icon"


def test_estaticos_con_version_se_guardan_un_anio(client, app):
    with app.test_request_context():
        from flask import url_for

        url = url_for("static", filename="css/panel.css")
    assert re.search(r"\?v=[0-9a-f]{10}$", url)
    assert "immutable" in client.get(url).headers["Cache-Control"]
    # Sin version: revalida como siempre.
    assert "immutable" not in client.get("/static/css/panel.css").headers.get("Cache-Control", "")


def test_respuestas_comprimidas(client):
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("Content-Encoding") == "gzip"


def test_csp_sin_terceros(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "googleapis" not in csp and "gstatic" not in csp and "unsafe-inline" not in csp


@pytest.mark.parametrize("ruta", ["/login", "/registro", "/"])
def test_paginas_publicas_enlazan_el_manifiesto(client, ruta):
    assert 'rel="manifest"' in client.get(ruta).get_data(as_text=True)


def test_no_quedan_prototipos_con_cdn():
    for archivo in ("index.html", "theme.js"):
        assert not os.path.exists(os.path.join(RAIZ, archivo)), archivo
    for carpeta, _dirs, archivos in os.walk(os.path.join(RAIZ, "templates")):
        for nombre in archivos:
            with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
                assert "cdn." not in f.read(), nombre
