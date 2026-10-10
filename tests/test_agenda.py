"""T6: agenda robusta. Duracion real, horario, hora de Colombia, bloqueos,
cancelar, reprogramar y horas libres."""
import threading
from datetime import date, timedelta

import pytest

from app.utils.helpers import hoy_local
from conftest import entrar


def _dia(semana: int = 1) -> date:
    """El proximo martes (dia 1), por lo menos manana: siempre futuro y abierto."""
    hoy = hoy_local() + timedelta(days=1)
    return hoy + timedelta(days=(1 - hoy.weekday()) % 7 + 7 * (semana - 1))


DIA = _dia()


def _a(hora: str, dia: date = DIA) -> str:
    return f"{dia.isoformat()}T{hora}"


@pytest.fixture
def negocio(client, crear):
    """Negocio con horario de 8 a 19, almuerzo de 12 a 13, domingo cerrado,
    dos profesionales y un corte de 60 min."""
    id_tienda, (sede,) = crear.tienda("pro")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    carlos = crear.usuario("carlos@turnio.co", "Profesional", id_tienda, sede)
    luisa = crear.usuario("luisa@turnio.co", "Profesional", id_tienda, sede)
    entrar(client, "admin@turnio.co")
    dias = [{"dia": d, "abierto": d < 6, "abre": "08:00", "cierra": "19:00",
             "almuerzo_desde": "12:00", "almuerzo_hasta": "13:00"} for d in range(7)]
    assert client.put("/api/horario", json={"dias": dias}).status_code == 200
    corte = client.post("/api/servicios", json={
        "nombre": "Corte", "duracion_min": 60, "precio": 25000, "pago_profesional": 15000,
    }).get_json()["id_servicio"]
    tinte = client.post("/api/servicios", json={
        "nombre": "Tinte", "duracion_min": 120, "precio": 90000,
    }).get_json()["id_servicio"]
    return {"tienda": id_tienda, "sede": sede, "carlos": carlos, "luisa": luisa, "corte": corte, "tinte": tinte}


def _cita(client, n, hora, quien="carlos", servicio="corte", dia=DIA, **extra):
    return client.post("/api/citas", json={
        "id_profesional": n[quien], "id_servicio": n[servicio], "inicio": _a(hora, dia),
        "cliente_nombre": "Cliente", "cliente_telefono": "300 123 4567", **extra,
    })


def test_la_duracion_bloquea_los_huecos_siguientes(client, negocio):
    n = negocio
    r = _cita(client, n, "10:00")
    assert r.status_code == 201
    cita = r.get_json()["cita"]
    assert (cita["inicio"], cita["fin"], cita["duracion_min"], cita["precio"]) == (_a("10:00"), _a("11:00"), 60, 25000)
    assert cita["cliente_telefono"] == "3001234567"

    r = _cita(client, n, "10:30")  # el corte de las 10 sigue hasta las 11
    assert r.status_code == 409
    assert "10:00 AM a 11:00 AM" in r.get_json()["msg"]
    assert _cita(client, n, "09:30").status_code == 409  # terminaria a las 10:30
    assert _cita(client, n, "09:00").status_code == 201  # termina justo a las 10
    assert _cita(client, n, "11:00").status_code == 201  # empieza justo al terminar
    assert _cita(client, n, "10:30", quien="luisa").status_code == 201  # otra agenda

    # Un tinte de 2 h a las 13:00 ocupa hasta las 15:00.
    assert _cita(client, n, "13:00", servicio="tinte").status_code == 201
    assert _cita(client, n, "14:45").status_code == 409
    # Duracion propia para una cita (cabello largo): 90 min.
    r = _cita(client, n, "15:00", duracion_min=90)
    assert r.get_json()["cita"]["fin"] == _a("16:30")
    assert _cita(client, n, "16:00").status_code == 409


def test_respeta_el_horario_y_el_almuerzo(client, negocio):
    n = negocio
    assert "Fuera del horario" in _cita(client, n, "18:30").get_json()["msg"]  # terminaria 19:30
    assert _cita(client, n, "18:00").status_code == 201
    assert _cita(client, n, "07:30").status_code == 400
    assert "almuerzo" in _cita(client, n, "11:30").get_json()["msg"]
    domingo = DIA + timedelta(days=5)
    assert "no abre" in _cita(client, n, "10:00", dia=domingo).get_json()["msg"]
    # Hoy en Colombia, no en el servidor: a las 8 p. m. el servidor en UTC ya va en manana.
    ayer = hoy_local() - timedelta(days=1)
    assert "ya pasó" in _cita(client, n, "10:00", dia=ayer).get_json()["msg"]


def test_hora_de_colombia(client, negocio):
    n = negocio
    # 15:00 UTC = 10:00 en Colombia; 23:30 UTC = 18:30 del mismo dia.
    r = _cita(client, n, "15:00:00Z")
    assert r.get_json()["cita"]["hora"] == "10:00"
    r = client.post("/api/citas", json={
        "id_profesional": n["luisa"], "id_servicio": n["corte"], "inicio": _a("23:00:00+00:00"),
        "cliente_nombre": "Noche",
    })
    assert r.get_json()["cita"]["inicio"] == _a("18:00")
    # La cita de las 6 p. m. sale en su dia, no en el siguiente (antes: UTC).
    citas = client.get(f"/api/citas?fecha={DIA}").get_json()["citas"]
    assert [c["hora"] for c in citas] == ["10:00", "18:00"]
    assert client.get(f"/api/citas?fecha={DIA + timedelta(days=1)}").get_json()["citas"] == []


def test_vista_de_semana_y_por_profesional(client, negocio):
    n = negocio
    _cita(client, n, "10:00")
    _cita(client, n, "10:00", quien="luisa", dia=DIA + timedelta(days=2))
    r = client.get(f"/api/citas?desde={DIA}&hasta={DIA + timedelta(days=6)}").get_json()
    assert [c["fecha"] for c in r["citas"]] == [str(DIA), str(DIA + timedelta(days=2))]
    r = client.get(f"/api/citas?desde={DIA}&hasta={DIA + timedelta(days=6)}&id_profesional={n['luisa']}").get_json()
    assert [c["id_profesional"] for c in r["citas"]] == [n["luisa"]]
    assert client.get(f"/api/citas?desde={DIA}&hasta={DIA + timedelta(days=60)}").status_code == 400


def test_reprogramar(client, negocio):
    n = negocio
    id_a = _cita(client, n, "10:00").get_json()["cita"]["id_cita"]
    _cita(client, n, "14:00")
    assert client.put(f"/api/citas/{id_a}", json={"inicio": _a("13:30")}).status_code == 409
    r = client.put(f"/api/citas/{id_a}", json={"inicio": _a("15:00")})
    assert r.status_code == 200
    assert (r.get_json()["cita"]["inicio"], r.get_json()["cita"]["fin"]) == (_a("15:00"), _a("16:00"))
    assert _cita(client, n, "10:00").status_code == 201  # la hora vieja quedo libre
    # Moverla sobre si misma (10 minutos mas tarde) no choca consigo.
    assert client.put(f"/api/citas/{id_a}", json={"inicio": _a("15:10")}).status_code == 200
    # Otro profesional y otro servicio: recalcula duracion y precio.
    r = client.put(f"/api/citas/{id_a}", json={"id_profesional": n["luisa"], "id_servicio": n["tinte"]})
    cita = r.get_json()["cita"]
    assert (cita["id_profesional"], cita["fin"], cita["precio"]) == (n["luisa"], _a("17:10"), 90000)


def test_cancelar_libera_el_horario(client, negocio, crear):
    n = negocio
    id_a = _cita(client, n, "10:00").get_json()["cita"]["id_cita"]
    r = client.post(f"/api/citas/{id_a}/cancelar", json={"motivo": "Se enfermó"})
    assert r.status_code == 200
    fila = crear.fila("SELECT estado, motivo_cancelacion FROM citas WHERE id_cita = %s", (id_a,))
    assert (fila["estado"], fila["motivo_cancelacion"]) == ("cancelada", "Se enfermó")
    assert client.get(f"/api/citas?fecha={DIA}").get_json()["citas"] == []
    assert _cita(client, n, "10:00").status_code == 201
    assert client.post(f"/api/citas/{id_a}/cancelar").status_code == 409
    assert client.put(f"/api/citas/{id_a}", json={"inicio": _a("15:00")}).status_code == 409


def test_no_asistio(client, negocio, crear):
    n = negocio
    id_a = _cita(client, n, "10:00").get_json()["cita"]["id_cita"]
    assert "todavía no empieza" in client.post(f"/api/citas/{id_a}/no-asistio").get_json()["msg"]
    crear.fila(
        "INSERT INTO citas (id_tienda, id_sede, id_profesional, id_servicio, cliente_nombre, inicio, fin) "
        "VALUES (%s, %s, %s, %s, 'Ayer', NOW() - INTERVAL 1 DAY, NOW() - INTERVAL 1 DAY + INTERVAL 1 HOUR)",
        (n["tienda"], n["sede"], n["carlos"], n["corte"]),
    )
    id_b = crear.fila("SELECT id_cita FROM citas WHERE cliente_nombre = 'Ayer'")["id_cita"]
    assert client.post(f"/api/citas/{id_b}/no-asistio").status_code == 200
    assert crear.fila("SELECT estado FROM citas WHERE id_cita = %s", (id_b,))["estado"] == "no_asistio"


def test_bloqueos(client, negocio):
    n = negocio
    r = client.post("/api/bloqueos", json={
        "id_profesional": n["carlos"], "desde": _a("15:00"), "hasta": _a("16:00"), "motivo": "Médico",
    })
    assert r.status_code == 201
    id_bloqueo = r.get_json()["bloqueo"]["id_cita"]
    assert "bloqueo" in _cita(client, n, "15:30").get_json()["msg"]
    assert _cita(client, n, "15:30", quien="luisa").status_code == 201

    # Toda la sede: nadie puede agendar ese rato.
    r = client.post("/api/bloqueos", json={"desde": _a("17:00"), "hasta": _a("19:00"), "motivo": "Capacitación"})
    assert r.get_json()["bloqueo"]["toda_la_sede"] is True
    assert _cita(client, n, "17:30").status_code == 409
    assert _cita(client, n, "17:30", quien="luisa").status_code == 409
    # Sale en la agenda de cada profesional.
    citas = client.get(f"/api/citas?fecha={DIA}&id_profesional={n['luisa']}").get_json()["citas"]
    assert [c["estado"] for c in citas] == ["reservada", "bloqueada"]

    # No bloquea encima de citas reservadas.
    _cita(client, n, "10:00")
    r = client.post("/api/bloqueos", json={"desde": _a("09:00"), "hasta": _a("11:00")})
    assert r.status_code == 409 and "Reprográmalas" in r.get_json()["msg"]
    # Varios dias (vacaciones), pero no mas de un mes.
    semana = DIA + timedelta(days=14)
    assert client.post("/api/bloqueos", json={
        "id_profesional": n["luisa"], "desde": _a("00:00", semana), "hasta": _a("00:00", semana + timedelta(days=5)),
    }).status_code == 201
    assert _cita(client, n, "10:00", quien="luisa", dia=semana + timedelta(days=2)).status_code == 409
    assert client.post("/api/bloqueos", json={"desde": _a("08:00"), "hasta": _a("08:00", DIA + timedelta(days=40))}
                       ).status_code == 400

    assert client.delete(f"/api/bloqueos/{id_bloqueo}").status_code == 200
    assert _cita(client, n, "15:00").status_code == 201
    # Una cita no se borra como bloqueo.
    id_cita = client.get(f"/api/citas?fecha={DIA}").get_json()["citas"][0]["id_cita"]
    assert client.delete(f"/api/bloqueos/{id_cita}").status_code == 409


def test_horas_libres(client, negocio):
    n = negocio
    _cita(client, n, "10:00")
    client.post("/api/bloqueos", json={"id_profesional": n["carlos"], "desde": _a("16:00"), "hasta": _a("19:00")})
    r = client.get(f"/api/agenda/disponibilidad?fecha={DIA}&id_servicio={n['corte']}").get_json()
    horas = {p["id_profesional"]: p["horas"] for p in r["profesionales"]}
    carlos = horas[n["carlos"]]
    assert carlos[:5] == ["08:00", "08:15", "08:30", "08:45", "09:00"]
    assert "09:15" not in carlos and "10:45" not in carlos  # se cruzan con el corte de las 10
    assert "11:00" in carlos and "11:15" not in carlos  # 11:15 + 60 min se mete al almuerzo
    assert "13:00" in carlos and carlos[-1] == "15:00"  # despues, el bloqueo
    assert horas[n["luisa"]][-1] == "18:00"
    domingo = DIA + timedelta(days=5)
    r = client.get(f"/api/agenda/disponibilidad?fecha={domingo}&id_servicio={n['corte']}").get_json()
    assert r["abierto"] is False and all(p["horas"] == [] for p in r["profesionales"])


def test_solo_hace_sus_servicios(client, negocio):
    n = negocio
    client.put(f"/api/profesionales/{n['luisa']}", json={"servicios": [n["corte"]]})
    r = _cita(client, n, "10:00", quien="luisa", servicio="tinte")
    assert r.status_code == 400 and "no hace Tinte" in r.get_json()["msg"]
    r = client.get(f"/api/agenda/disponibilidad?fecha={DIA}&id_servicio={n['tinte']}").get_json()
    assert [p["id_profesional"] for p in r["profesionales"]] == [n["carlos"]]


def test_un_profesional_solo_maneja_lo_suyo(client, negocio):
    n = negocio
    id_luisa = _cita(client, n, "10:00", quien="luisa").get_json()["cita"]["id_cita"]
    client.post("/logout")
    entrar(client, "carlos@turnio.co")
    assert _cita(client, n, "10:00").status_code == 201
    assert _cita(client, n, "11:00", quien="luisa").status_code == 403
    assert len(client.get(f"/api/citas?fecha={DIA}").get_json()["citas"]) == 2  # ve la agenda de la sede
    assert client.post(f"/api/citas/{id_luisa}/cancelar").status_code == 403
    assert client.put(f"/api/citas/{id_luisa}", json={"inicio": _a("15:00")}).status_code == 403
    assert client.post("/api/bloqueos", json={"desde": _a("15:00"), "hasta": _a("16:00")}).status_code == 403
    assert client.post("/api/bloqueos", json={
        "id_profesional": n["carlos"], "desde": _a("15:00"), "hasta": _a("16:00"),
    }).status_code == 201


def test_otro_negocio_no_ve_ni_toca(client, negocio, crear):
    n = negocio
    id_cita = _cita(client, n, "10:00").get_json()["cita"]["id_cita"]
    client.post("/logout")
    otra, _ = crear.tienda(nombre="Otro")
    crear.usuario("otro@turnio.co", "Admin", otra)
    entrar(client, "otro@turnio.co")
    assert client.get(f"/api/citas?fecha={DIA}").get_json()["citas"] == []
    assert client.get(f"/api/citas/{id_cita}").status_code == 404
    assert client.post(f"/api/citas/{id_cita}/cancelar").status_code == 404
    assert client.put(f"/api/citas/{id_cita}", json={"inicio": _a("15:00")}).status_code == 404
    assert _cita(client, n, "15:00").status_code == 404  # su profesional no es de este negocio


def test_dos_reservas_a_la_vez_solo_entra_una(app, negocio):
    """Dos recepcionistas agendan a Carlos casi a la misma hora: 10:00 y 10:30."""
    from app.services import agenda_service
    from app.services.errores import Conflicto

    n = negocio
    resultados = []
    barrera = threading.Barrier(2)

    def reservar(hora):
        barrera.wait()
        try:
            agenda_service.crear_cita(n["tienda"], n["sede"], None, {
                "id_profesional": n["carlos"], "id_servicio": n["corte"], "inicio": _a(hora), "cliente_nombre": hora,
            })
            resultados.append("ok")
        except Conflicto:
            resultados.append("ocupado")

    hilos = [threading.Thread(target=reservar, args=(h,)) for h in ("10:00", "10:30")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(resultados) == ["ocupado", "ok"]
