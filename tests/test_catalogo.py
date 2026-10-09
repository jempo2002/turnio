"""T4: catalogo de servicios, profesionales, datos del local y horario."""
import io

from conftest import CLAVE, entrar

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _admin(client, crear, sedes=("Principal",)):
    id_tienda, ids = crear.tienda("pro", sedes=sedes)
    id_admin = crear.usuario("admin@turnio.co", "Admin", id_tienda)
    entrar(client, "admin@turnio.co")
    if len(ids) > 1:
        client.post("/seleccionar-sede", data={"id_sede": ids[0]})
    return id_tienda, ids, id_admin


def _servicio(client, nombre="Corte", **extra):
    datos = {"nombre": nombre, "duracion_min": 45, "precio": 20000, "pago_profesional": 13000, **extra}
    return client.post("/api/servicios", json=datos)


def test_crud_de_servicios(client, crear):
    _admin(client, crear)
    r = _servicio(client)
    assert r.status_code == 201
    id_corte = r.get_json()["id_servicio"]
    assert _servicio(client).status_code == 409  # nombre repetido
    assert _servicio(client, "Barba", pago_profesional=30000).status_code == 400  # paga mas que el precio
    assert _servicio(client, "Barba", duracion_min=2).status_code == 400

    r = client.put(f"/api/servicios/{id_corte}", json={
        "nombre": "Corte clásico", "duracion_min": 60, "precio": 25000, "pago_profesional": 15000,
    })
    assert r.status_code == 200
    servicios = client.get("/api/servicios").get_json()["servicios"]
    assert servicios == [{
        "id_servicio": id_corte, "nombre": "Corte clásico", "duracion_min": 60, "precio": 25000,
        "pago_profesional": 15000,
    }]

    assert client.delete(f"/api/servicios/{id_corte}").status_code == 200
    assert client.get("/api/servicios").get_json()["servicios"] == []
    assert crear.fila("SELECT estado_activo FROM servicios WHERE id_servicio = %s", (id_corte,))["estado_activo"] == 0
    assert _servicio(client, "Corte clásico").status_code == 201  # el nombre quedo libre


def test_servicios_de_otro_negocio_no_se_ven_ni_se_tocan(client, crear):
    otra, _ = crear.tienda(nombre="Otro")
    crear.fila(
        "INSERT INTO servicios (id_tienda, nombre, duracion_min, precio) VALUES (%s, 'Ajeno', 30, 10000)", (otra,)
    )
    ajeno = crear.fila("SELECT id_servicio FROM servicios WHERE nombre = 'Ajeno'")["id_servicio"]
    _admin(client, crear)
    assert client.get("/api/servicios").get_json()["servicios"] == []
    datos = {"nombre": "Mio", "duracion_min": 30, "precio": 1}
    assert client.put(f"/api/servicios/{ajeno}", json=datos).status_code == 404
    assert client.delete(f"/api/servicios/{ajeno}").status_code == 404
    r = client.put("/api/profesionales/0", json={"servicios": [ajeno]})
    assert r.status_code == 404


def test_solo_el_admin_cambia_el_catalogo(client, crear):
    id_tienda, (sede,), _ = _admin(client, crear)
    crear.usuario("ana@turnio.co", "Recepcion", id_tienda, sede)
    client.post("/logout")
    entrar(client, "ana@turnio.co")
    assert client.get("/api/servicios").status_code == 200
    assert client.get("/api/horario").status_code == 200
    assert _servicio(client).status_code == 403
    assert client.put("/api/negocio", json={"nombre_negocio": "X"}).status_code == 403


def test_profesionales_servicios_y_pago_propio(client, crear):
    id_tienda, (sede,), id_admin = _admin(client, crear)
    corte = _servicio(client).get_json()["id_servicio"]
    barba = _servicio(client, "Barba", precio=15000, pago_profesional=10000).get_json()["id_servicio"]
    r = client.post("/api/usuarios", json={
        "nombre": "Carlos Pérez", "cc": "10000001", "correo": "carlos@turnio.co", "rol": "Profesional",
        "password": CLAVE, "confirm_password": CLAVE, "id_sede": sede,
    })
    carlos = r.get_json()["id_usuario"]

    # Solo Carlos atiende (el Admin sembrado a mano no); hace todo el catalogo.
    (p,) = client.get("/api/profesionales").get_json()["profesionales"]
    assert p["id_usuario"] == carlos and p["atiende_todos"] and p["reserva_online"]
    assert [s["pago_profesional"] for s in p["servicios"]] == [10000, 13000]

    # Solo corte, y gana 16.000 en vez de 13.000.
    r = client.put(f"/api/profesionales/{carlos}", json={
        "servicios": [{"id_servicio": corte, "pago_profesional": 16000}], "reserva_online": False,
    })
    assert r.status_code == 200
    (p,) = client.get("/api/profesionales").get_json()["profesionales"]
    assert [(s["id_servicio"], s["pago_profesional"]) for s in p["servicios"]] == [(corte, 16000)]
    assert not p["atiende_todos"] and not p["reserva_online"]

    # Validaciones: mas que el precio, lista vacia, servicio inexistente.
    assert client.put(f"/api/profesionales/{carlos}", json={
        "servicios": [{"id_servicio": barba, "pago_profesional": 99000}]}).status_code == 400
    assert client.put(f"/api/profesionales/{carlos}", json={"servicios": []}).status_code == 400
    assert client.put(f"/api/profesionales/{carlos}", json={"servicios": [999999]}).status_code == 400
    # Bajar el precio por debajo de su pago propio no se deja.
    assert client.put(f"/api/servicios/{corte}", json={
        "nombre": "Corte", "duracion_min": 45, "precio": 15000, "pago_profesional": 10000}).status_code == 400

    # Un Profesional no puede dejar de atender; el Admin si puede empezar.
    assert client.put(f"/api/profesionales/{carlos}", json={"atiende": False}).status_code == 400
    assert client.put(f"/api/profesionales/{id_admin}", json={"atiende": True}).status_code == 200
    assert len(client.get("/api/profesionales").get_json()["profesionales"]) == 2

    # Volver a todo el catalogo.
    client.put(f"/api/profesionales/{carlos}", json={"servicios": "todos"})
    assert crear.fila("SELECT COUNT(*) AS n FROM profesional_servicios")["n"] == 0


def test_un_profesional_no_ve_el_pago_propio_de_otro(client, crear):
    id_tienda, (sede,), _ = _admin(client, crear)
    corte = _servicio(client).get_json()["id_servicio"]
    for n, correo in enumerate(("carlos@turnio.co", "junior@turnio.co")):
        client.post("/api/usuarios", json={
            "nombre": correo.split("@")[0], "cc": f"1000000{n}", "correo": correo, "rol": "Profesional",
            "password": CLAVE, "confirm_password": CLAVE, "id_sede": sede,
        })
    carlos = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'carlos@turnio.co'")["id_usuario"]
    client.put(f"/api/profesionales/{carlos}", json={"servicios": [{"id_servicio": corte, "pago_profesional": 17000}]})
    client.post("/logout")
    entrar(client, "junior@turnio.co")
    pagos = {p["nombre_completo"]: p["servicios"][0]["pago_profesional"]
             for p in client.get("/api/profesionales").get_json()["profesionales"]}
    assert pagos == {"carlos": 13000, "junior": 13000}


def test_logo_y_sin_fotos_de_profesionales(client, crear):
    id_tienda, (sede,), id_admin = _admin(client, crear)
    r = client.post("/api/negocio/logo", data={"imagen": (io.BytesIO(PNG), "logo.png")})
    url = r.get_json()["logo_url"]
    assert url == client.get("/api/negocio").get_json()["negocio"]["logo_url"]
    img = client.get(url)
    assert img.status_code == 200 and img.mimetype == "image/png" and img.data == PNG
    assert "immutable" in img.headers["Cache-Control"]

    # Cambiarlo borra el anterior.
    client.post("/api/negocio/logo", data={"imagen": (io.BytesIO(PNG), "logo.png")})
    assert client.get(url).status_code == 404
    assert crear.fila("SELECT COUNT(*) AS n FROM imagenes")["n"] == 1

    # Un SVG (o cualquier cosa que no sea PNG, JPG o WebP) no entra.
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    r = client.post("/api/negocio/logo", data={"imagen": (io.BytesIO(svg), "logo.png")})
    assert r.status_code == 400
    grande = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
    assert client.post("/api/negocio/logo", data={"imagen": (io.BytesIO(grande), "l.jpg")}).status_code == 400

    assert client.delete("/api/negocio/logo").status_code == 200
    assert client.get("/api/negocio").get_json()["negocio"]["logo_url"] is None

    # Fotos de profesionales: ya no hay (jempo, 2026-10-09). Una que se subio
    # antes deja de servirse.
    assert client.post(f"/api/usuarios/{id_admin}/foto", data={"imagen": (io.BytesIO(PNG), "yo.png")}).status_code \
        in (404, 405)
    crear.fila("INSERT INTO imagenes (id_tienda, tipo, datos) VALUES (%s, 'image/png', %s)", (id_tienda, PNG))
    vieja = crear.fila("SELECT MAX(id_imagen) AS id FROM imagenes")["id"]
    carlos = crear.usuario("carlos@turnio.co", "Profesional", id_tienda, sede)
    crear.fila("UPDATE usuarios SET id_foto = %s WHERE id_usuario = %s", (vieja, carlos))
    assert client.get(f"/img/{vieja}").status_code == 404
    (profesional,) = client.get("/api/profesionales").get_json()["profesionales"]
    assert "foto_url" not in profesional


def test_datos_del_negocio_y_enlace(client, crear):
    _admin(client, crear)
    otra, _ = crear.tienda(nombre="Ocupado")
    r = client.put("/api/negocio", json={
        "nombre_negocio": "Uñas Divinas", "tipo_negocio": "unas", "telefono": "300 111 2233", "slug": "unas-divinas",
    })
    assert r.status_code == 200
    negocio = client.get("/api/negocio").get_json()["negocio"]
    assert negocio["nombre_negocio"] == "Uñas Divinas" and negocio["telefono"] == "3001112233"
    assert negocio["enlace_reservas"].endswith("/r/unas-divinas")
    base = {"nombre_negocio": "Uñas Divinas", "tipo_negocio": "unas"}
    assert client.put("/api/negocio", json={**base, "slug": "ocupado"}).status_code == 409
    assert client.put("/api/negocio", json={**base, "slug": "Con Espacios"}).status_code == 400
    assert client.put("/api/negocio", json={**base, "tipo_negocio": "taller"}).status_code == 400


def _semana(**cambios_lunes):
    dias = [{"dia": d, "abierto": d < 6, "abre": "09:00", "cierra": "18:00"} for d in range(7)]
    dias[0].update(cambios_lunes)
    return dias


def test_horario_de_la_sede(client, crear):
    _, (centro, norte), _ = _admin(client, crear, sedes=("Centro", "Norte"))
    r = client.put("/api/horario", json={"dias": _semana(almuerzo_desde="13:00", almuerzo_hasta="14:00")})
    assert r.status_code == 200
    dias = client.get("/api/horario").get_json()["dias"]
    assert dias[0] == {
        "dia": 0, "nombre": "Lunes", "abierto": True, "abre": "09:00", "cierra": "18:00",
        "almuerzo_desde": "13:00", "almuerzo_hasta": "14:00",
    }
    assert dias[6]["abierto"] is False
    # La otra sede sigue sin horario (sembrada a mano): todo cerrado.
    assert not any(d["abierto"] for d in client.get(f"/api/horario?id_sede={norte}").get_json()["dias"])

    malos = [
        _semana(cierra="08:00"),
        _semana(almuerzo_desde="13:00"),
        _semana(almuerzo_desde="17:00", almuerzo_hasta="19:00"),
        _semana(abre="25:00"),
        _semana()[:6],
    ]
    for dias in malos:
        assert client.put("/api/horario", json={"dias": dias}).status_code == 400
    _, (ajena,) = crear.tienda(nombre="Otro")
    assert client.put("/api/horario", json={"id_sede": ajena, "dias": _semana()}).status_code == 400


def test_negocio_nuevo_trae_horario_y_el_dueno_atiende(client, db):
    from test_registro import _registrar

    _registrar(client)
    dias = client.get("/api/horario").get_json()["dias"]
    assert [d["abierto"] for d in dias] == [True] * 6 + [False]
    assert dias[0]["abre"] == "08:00" and dias[0]["cierra"] == "19:00"
    (dueno,) = client.get("/api/profesionales").get_json()["profesionales"]
    assert dueno["rol"] == "Admin"

    # Una sede nueva tambien nace con horario.
    db.cursor().execute("UPDATE tiendas SET plan_id = 'multisede'")
    norte = client.post("/api/sedes", json={"nombre": "Norte"}).get_json()["id_sede"]
    dias = client.get(f"/api/horario?id_sede={norte}").get_json()["dias"]
    assert [d["abierto"] for d in dias] == [True] * 6 + [False]


def test_tener_agenda_cuenta_en_el_tope_del_plan(client, crear, db):
    id_tienda, (sede,), id_admin = _admin(client, crear)
    db.cursor().execute("UPDATE tiendas SET plan_id = 'basico' WHERE id_tienda = %s", (id_tienda,))
    for n in range(3):
        crear.usuario(f"p{n}@turnio.co", "Profesional", id_tienda, sede)
    ana = crear.usuario("ana@turnio.co", "Recepcion", id_tienda, sede)
    for quien in (id_admin, ana):
        r = client.put(f"/api/profesionales/{quien}", json={"atiende": True})
        assert r.status_code == 403 and r.get_json()["code"] == "limite_plan"
    # Pasar a Profesional a quien ya atiende no cuenta doble.
    db.cursor().execute("UPDATE usuarios SET atiende = 0 WHERE correo = 'p0@turnio.co'")
    assert client.put(f"/api/profesionales/{ana}", json={"atiende": True}).status_code == 200
    r = client.put(f"/api/usuarios/{ana}", json={"nombre": "Ana", "rol": "Profesional", "id_sede": sede})
    assert r.status_code == 200
