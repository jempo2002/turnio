"""T8: pagina publica de reservas /r/<slug>. Sin cuenta, solo lo que el
cliente necesita, mismas reglas de la agenda y protegida contra abuso."""
from datetime import timedelta

import pytest

from app.utils.helpers import hoy_local
from conftest import entrar


def _martes(semanas: int = 1):
    """Un martes futuro (abierto en el horario de la prueba)."""
    dia = hoy_local() + timedelta(days=1)
    return dia + timedelta(days=(1 - dia.weekday()) % 7 + 7 * (semanas - 1))


DIA = _martes()


@pytest.fixture
def negocio(app, crear):
    """Barberia con dos profesionales en linea (Carlos hace corte y tinte,
    Luisa solo tinte), uno que no sale en linea (Pedro) y otro negocio al lado."""
    id_tienda, (sede,) = crear.tienda("pro", nombre="Barberia Cuartel")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    carlos = crear.usuario("carlos@turnio.co", "Profesional", id_tienda, sede)
    luisa = crear.usuario("luisa@turnio.co", "Profesional", id_tienda, sede)
    pedro = crear.usuario("pedro@turnio.co", "Profesional", id_tienda, sede)
    admin = app.test_client()
    entrar(admin, "admin@turnio.co")
    dias = [{"dia": d, "abierto": d < 6, "abre": "08:00", "cierra": "19:00",
             "almuerzo_desde": "12:00", "almuerzo_hasta": "13:00"} for d in range(7)]
    assert admin.put("/api/horario", json={"dias": dias}).status_code == 200
    assert admin.put("/api/negocio", json={
        "nombre_negocio": "Barberia Cuartel", "tipo_negocio": "barberia", "telefono": "3001112233",
    }).status_code == 200
    ids = {}
    for nombre, duracion, precio, pago in (("Corte", 60, 25000, 15000), ("Tinte", 120, 90000, 40000),
                                           ("Barba VIP", 30, 20000, 12000)):
        ids[nombre] = admin.post("/api/servicios", json={
            "nombre": nombre, "duracion_min": duracion, "precio": precio, "pago_profesional": pago,
        }).get_json()["id_servicio"]
    assert admin.put(f"/api/profesionales/{carlos}", json={
        "servicios": [{"id_servicio": ids["Corte"]}, {"id_servicio": ids["Tinte"]}],
    }).status_code == 200
    assert admin.put(f"/api/profesionales/{luisa}", json={
        "servicios": [{"id_servicio": ids["Tinte"]}],
    }).status_code == 200
    # Pedro no sale en linea y es el unico que hace Barba VIP.
    assert admin.put(f"/api/profesionales/{pedro}", json={
        "reserva_online": False,
        "servicios": [{"id_servicio": ids["Barba VIP"]}, {"id_servicio": ids["Corte"]}],
    }).status_code == 200

    otra, (otra_sede,) = crear.tienda("pro", nombre="Otro Salon")
    ajeno = crear.usuario("ajeno@otro.co", "Profesional", otra, otra_sede)
    return {"tienda": id_tienda, "sede": sede, "carlos": carlos, "luisa": luisa, "pedro": pedro,
            "corte": ids["Corte"], "tinte": ids["Tinte"], "barba": ids["Barba VIP"], "admin": admin,
            "otra_sede": otra_sede, "ajeno": ajeno}


URL = "/api/publico/barberia-cuartel"


def _reservar(client, n, hora, dia=DIA, telefono="310 555 0101", **extra):
    cuerpo = {"id_sede": n["sede"], "id_servicio": n["corte"], "inicio": f"{dia.isoformat()}T{hora}",
              "cliente_nombre": "Ana Gomez", "cliente_telefono": telefono}
    cuerpo.update(extra)
    return client.post(URL + "/reservas", json=cuerpo)


# ── Pagina y datos publicos ─────────────────────────────────────────

def test_pagina_publica_sin_sesion(client, negocio):
    r = client.get("/r/barberia-cuartel")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Barberia Cuartel" in html and "js/publico/reservar.js" in html
    assert 'name="sitio_web"' in html  # campo trampa
    assert client.get("/r/no-existe").status_code == 404
    assert client.get("/r/../login").status_code == 404


def test_negocio_suspendido_no_existe(client, negocio, db):
    db.cursor().execute("UPDATE tiendas SET estado = 'Suspendido' WHERE id_tienda = %s", (negocio["tienda"],))
    assert client.get("/r/barberia-cuartel").status_code == 404
    assert client.get(URL).status_code == 404


def test_solo_sale_lo_publico(client, negocio):
    r = client.get(URL)
    assert r.status_code == 200
    d = r.get_json()
    assert d["negocio"]["nombre"] == "Barberia Cuartel" and d["negocio"]["recibe_reservas"] is True
    (sede,) = d["sedes"]
    assert sede["whatsapp"] == "3001112233" and len(sede["horario"]) == 7
    nombres = {p["nombre"] for p in sede["profesionales"]}
    assert nombres == {"Carlos", "Luisa"}  # Pedro no sale en linea
    # Barba VIP solo la hace Pedro: no se ofrece.
    assert [s["nombre"] for s in sede["servicios"]] == ["Corte", "Tinte"]
    texto = r.get_data(as_text=True)
    for prohibido in ("@turnio.co", "pago_profesional", "correo", "rol", "Pedro", "Otro Salon", "ajeno"):
        assert prohibido not in texto


def test_disponibilidad_sin_datos_de_clientes(client, negocio):
    n = negocio
    assert _reservar(client, n, "10:00", id_profesional=n["carlos"]).status_code == 201
    r = client.get(URL + "/disponibilidad", query_string={
        "id_sede": n["sede"], "id_servicio": n["corte"], "fecha": DIA.isoformat()})
    assert r.status_code == 200
    d = r.get_json()
    assert [p["id_profesional"] for p in d["profesionales"]] == [n["carlos"]]  # Luisa no hace corte, Pedro oculto
    horas = d["profesionales"][0]["horas"]
    assert "10:00" not in horas and "10:30" not in horas and "11:00" in horas
    assert "Ana" not in r.get_data(as_text=True)


def test_disponibilidad_valida_fecha_y_sede(client, negocio):
    n = negocio
    base = {"id_sede": n["sede"], "id_servicio": n["corte"]}
    lejos = hoy_local() + timedelta(days=31)
    assert client.get(URL + "/disponibilidad", query_string={**base, "fecha": lejos.isoformat()}).status_code == 400
    ayer = hoy_local() - timedelta(days=1)
    assert client.get(URL + "/disponibilidad", query_string={**base, "fecha": ayer.isoformat()}).status_code == 400
    # Sede de otro negocio: no existe aqui.
    r = client.get(URL + "/disponibilidad", query_string={
        **base, "id_sede": n["otra_sede"], "fecha": DIA.isoformat()})
    assert r.status_code == 404


# ── Reservar ────────────────────────────────────────────────────────

def test_reserva_llega_a_la_agenda_del_negocio(client, negocio, crear):
    n = negocio
    r = _reservar(client, n, "10:00", id_profesional=n["carlos"])
    assert r.status_code == 201
    cita = r.get_json()["cita"]
    assert (cita["hora"], cita["hasta"], cita["profesional"], cita["precio"]) == ("10:00", "11:00", "Carlos", 25000)
    assert cita["whatsapp_url"].startswith("https://wa.me/573001112233?text=")
    assert "Ana%20Gomez" in cita["whatsapp_url"]
    fila = crear.fila("SELECT origen, estado, cliente_telefono, id_usuario_registra FROM citas WHERE id_cita = %s",
                      (cita["id_cita"],))
    assert fila == {"origen": "publica", "estado": "reservada", "cliente_telefono": "3105550101",
                    "id_usuario_registra": None}
    agenda = n["admin"].get("/api/citas", query_string={"fecha": DIA.isoformat()}).get_json()["citas"]
    assert [(c["cliente_nombre"], c["origen"]) for c in agenda] == [("Ana Gomez", "publica")]


def test_misma_hora_no_se_reserva_dos_veces(client, negocio):
    n = negocio
    assert _reservar(client, n, "10:00", id_profesional=n["carlos"]).status_code == 201
    r = _reservar(client, n, "10:30", id_profesional=n["carlos"], telefono="3115550202")
    assert r.status_code == 409
    # Fuera del horario y en el almuerzo: las reglas de la agenda.
    assert _reservar(client, n, "18:30", id_profesional=n["carlos"], telefono="3125550303").status_code == 400
    assert _reservar(client, n, "11:30", id_profesional=n["carlos"], telefono="3135550404").status_code == 400


def test_cualquiera_toma_al_primero_libre(client, negocio):
    n = negocio
    tinte = {"id_servicio": n["tinte"], "id_profesional": "cualquiera"}
    a = _reservar(client, n, "08:00", **tinte).get_json()["cita"]["profesional"]
    b = _reservar(client, n, "08:00", telefono="3115550202", **tinte).get_json()["cita"]["profesional"]
    assert {a, b} == {"Carlos", "Luisa"}
    # Ya no queda nadie en linea libre a las 8 (Pedro no hace tinte ni sale en linea).
    r = _reservar(client, n, "08:00", telefono="3125550303", **tinte)
    assert r.status_code == 409


def test_no_se_reserva_con_quien_no_sale_en_linea_ni_con_otro_negocio(client, negocio):
    n = negocio
    r = _reservar(client, n, "10:00", id_profesional=n["pedro"])
    assert r.status_code == 409  # igual que ocupado: no se delata
    assert _reservar(client, n, "10:00", id_profesional=n["ajeno"]).status_code == 409
    assert _reservar(client, n, "10:00", id_sede=n["otra_sede"]).status_code == 404
    # Luisa no hace corte.
    assert _reservar(client, n, "10:00", id_profesional=n["luisa"]).status_code == 409


def test_hora_pasada_y_datos_invalidos(client, negocio):
    n = negocio
    hoy = hoy_local()
    r = _reservar(client, n, "00:00", dia=hoy, id_profesional=n["carlos"])
    assert r.status_code == 400
    assert _reservar(client, n, "10:00", telefono="123", id_profesional=n["carlos"]).status_code == 400
    assert _reservar(client, n, "10:00", cliente_nombre="", id_profesional=n["carlos"]).status_code == 400


def test_campo_trampa(client, negocio, crear):
    r = _reservar(client, negocio, "10:00", id_profesional=negocio["carlos"], sitio_web="http://spam.example")
    assert r.status_code == 400
    assert crear.fila("SELECT COUNT(*) AS n FROM citas")["n"] == 0


def test_tope_de_citas_por_venir_por_whatsapp(client, negocio):
    n = negocio
    for hora in ("08:00", "09:00", "10:00"):
        assert _reservar(client, n, hora, id_profesional=n["carlos"]).status_code == 201
    r = _reservar(client, n, "14:00", id_profesional=n["carlos"])
    assert r.status_code == 429
    assert "WhatsApp" in r.get_json()["msg"]


def test_limite_de_envios_por_ip(client, negocio):
    n = negocio
    codigos = [
        _reservar(client, n, "10:00", id_profesional=n["carlos"], telefono=f"31055501{i:02d}").status_code
        for i in range(6)
    ]
    assert codigos[-1] == 429


def test_suscripcion_vencida_no_recibe_reservas(client, negocio, db):
    db.cursor().execute(
        "UPDATE tiendas SET trial_ends_at = %s WHERE id_tienda = %s",
        (hoy_local() - timedelta(days=1), negocio["tienda"]),
    )
    assert client.get(URL).get_json()["negocio"]["recibe_reservas"] is False
    r = _reservar(client, negocio, "10:00", id_profesional=negocio["carlos"])
    assert r.status_code == 403


def test_la_sesion_del_admin_no_se_toca(negocio):
    admin = negocio["admin"]
    assert admin.get("/r/barberia-cuartel").status_code == 200
    assert admin.get("/api/citas").status_code == 200
