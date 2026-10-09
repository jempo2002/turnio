"""T3: registro abierto de negocios, invitaciones al equipo y aislamiento
entre negocios."""
from datetime import timedelta
from urllib.parse import urlparse

from conftest import CLAVE, entrar


def _registro(**cambios):
    datos = {
        "nombre_negocio": "Uñas Divinas",
        "tipo_negocio": "unas",
        "telefono": "300 111 2233",
        "admin_nombre": "Laura Gómez",
        "admin_cc": "1144000111",
        "admin_correo": "laura@unas.co",
        "admin_password": CLAVE,
        "confirm_password": CLAVE,
    }
    datos.update(cambios)
    return datos


def _registrar(client, **cambios):
    return client.post("/registro", data=_registro(**cambios))


def test_registro_crea_negocio_con_prueba_pro_y_entra(client, crear):
    from app.services import plan_service
    from app.utils.helpers import hoy_local

    assert client.get("/registro").status_code == 200
    r = _registrar(client)
    assert r.status_code == 302 and r.location.endswith("/inicio")
    assert "días gratis" in client.get("/inicio").get_data(as_text=True)

    tienda = crear.fila("SELECT * FROM tiendas")
    assert tienda["slug"] == "unas-divinas"
    assert tienda["tipo_negocio"] == "unas"
    assert tienda["telefono"] == "3001112233"
    assert tienda["plan_id"] == plan_service.PLAN_PRUEBA == "pro"
    assert tienda["trial_ends_at"] == hoy_local() + timedelta(days=plan_service.DIAS_PRUEBA)
    assert tienda["fecha_fin_suscripcion"] is None
    assert crear.fila("SELECT COUNT(*) AS n FROM sedes WHERE es_principal = 1")["n"] == 1
    admin = crear.fila("SELECT rol, id_sede, clave_hash FROM usuarios")
    assert admin["rol"] == "Admin" and admin["id_sede"] is None
    assert admin["clave_hash"] != CLAVE  # hash, nunca la clave

    # Sale y vuelve a entrar con lo que registro.
    client.post("/logout")
    assert entrar(client, "laura@unas.co").location.endswith("/inicio")


def test_registro_por_api_json(client, crear):
    r = client.post("/api/auth/register", json=_registro())
    assert r.status_code == 201
    assert r.get_json()["redirect"] == "/inicio"
    assert client.get("/equipo").status_code == 200  # ya con sesion de Admin


def test_registro_rechaza_datos_malos_sin_crear_nada(client, crear):
    casos = [
        ({"admin_password": "Corta1", "confirm_password": "Corta1"}, "8 caracteres"),
        ({"confirm_password": "Otra1234"}, "no coinciden"),
        ({"admin_correo": "no-es-correo"}, "correo"),
        ({"telefono": ""}, "WhatsApp"),
        ({"admin_cc": "12"}, "cedula"),
        ({"nombre_negocio": ""}, "nombre del negocio"),
    ]
    from app import limiter

    for cambio, texto in casos:
        limiter.reset()  # aqui se prueban los mensajes, no el limite
        r = client.post("/api/auth/register", json=_registro(**cambio))
        assert r.status_code == 400, cambio
        assert texto in r.get_json()["msg"], (cambio, r.get_json())
    assert crear.fila("SELECT COUNT(*) AS n FROM tiendas")["n"] == 0
    # El formulario conserva lo escrito, menos las contrasenas.
    html = _registrar(client, admin_password="corta").get_data(as_text=True)
    assert 'value="laura@unas.co"' in html and CLAVE not in html


def test_registro_correo_repetido_y_slug_unico(client, crear):
    assert _registrar(client).status_code == 302
    r = client.post("/api/auth/register", json=_registro(admin_cc="99887766"))
    assert r.status_code == 409
    r = client.post(
        "/api/auth/register", json=_registro(admin_correo="otra@unas.co", admin_cc="99887766")
    )
    assert r.status_code == 201
    slugs = crear.fila("SELECT GROUP_CONCAT(slug ORDER BY id_tienda) AS s FROM tiendas")["s"]
    assert slugs == "unas-divinas,unas-divinas-2"


def test_registro_campo_trampa_y_limite(client, crear):
    r = client.post("/api/auth/register", json=_registro(sitio_web="http://spam"))
    assert r.status_code == 400
    assert crear.fila("SELECT COUNT(*) AS n FROM tiendas")["n"] == 0
    for i in range(4):
        client.post("/api/auth/register", json=_registro(admin_password="x"))
    assert client.post("/api/auth/register", json=_registro()).status_code == 429


# ---------- Invitaciones ----------

def _admin_con_negocio(client):
    assert _registrar(client).status_code == 302


def _invitar(client, **cambios):
    datos = {"nombre": "Carlos Ruiz", "cc": "1144222333", "correo": "carlos@unas.co", "rol": "Profesional",
             "telefono": "3015556677"}
    datos.update(cambios)
    return client.post("/api/usuarios", json=datos)


def test_invitar_profesional_y_aceptar(client, app, crear):
    _admin_con_negocio(client)
    r = _invitar(client)
    assert r.status_code == 201
    inv = r.get_json()["invitacion"]
    assert inv["whatsapp"].startswith("https://wa.me/573015556677?text=")
    ruta = urlparse(inv["enlace"]).path
    assert "Invitación pendiente" in client.get("/equipo").get_data(as_text=True)

    usuario = crear.fila("SELECT invitacion_pendiente, id_sede FROM usuarios WHERE correo = 'carlos@unas.co'")
    assert usuario["invitacion_pendiente"] == 1 and usuario["id_sede"]  # su sede: la unica

    invitado = app.test_client()
    # Aun sin clave propia no puede entrar con ninguna.
    assert entrar(invitado, "carlos@unas.co").location.endswith("/login")
    assert "Hola, Carlos Ruiz" in invitado.get(ruta).get_data(as_text=True)
    r = invitado.post(ruta, data={"password": "Corta1", "confirm_password": "Corta1"})
    assert r.location.endswith(ruta)  # politica de clave
    r = invitado.post(ruta, data={"password": "Nueva1234", "confirm_password": "Nueva1234"})
    assert r.location.endswith("/inicio")
    with invitado.session_transaction() as s:
        assert s["rol"] == "Profesional"
    assert invitado.get("/inicio").status_code == 200
    assert invitado.get("/equipo").status_code == 302  # Profesional no administra el equipo

    # El enlace sirve una sola vez y ya no hay invitacion para reenviar.
    otro = app.test_client()
    assert otro.get(ruta).location.endswith("/login")
    id_carlos = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'carlos@unas.co'")["id_usuario"]
    assert client.post(f"/api/usuarios/{id_carlos}/invitacion").status_code == 400
    assert entrar(otro, "carlos@unas.co", "Nueva1234").location.endswith("/inicio")


def test_enlace_nuevo_y_enlace_falso(client, app, crear):
    _admin_con_negocio(client)
    id_usuario = _invitar(client, telefono="").get_json()["id_usuario"]
    r = client.post(f"/api/usuarios/{id_usuario}/invitacion")
    assert r.status_code == 200
    assert r.get_json()["invitacion"]["whatsapp"].startswith("https://wa.me/?text=")
    falso = app.test_client()
    assert falso.get("/invitacion/no-es-un-token").location.endswith("/login")
    # Un token de recuperacion no sirve como invitacion (otra sal).
    from app.services.auth_service import create_reset_token

    fila = crear.fila("SELECT correo, clave_hash FROM usuarios WHERE id_usuario = %s", (id_usuario,))
    with app.app_context():
        token = create_reset_token(app.secret_key, fila["correo"], fila["clave_hash"])
    assert falso.get(f"/invitacion/{token}").location.endswith("/login")


def test_crear_con_contrasena_sigue_funcionando(client, crear):
    _admin_con_negocio(client)
    r = _invitar(client, password="Clave5678", confirm_password="Clave5678")
    assert r.status_code == 201 and "invitacion" not in r.get_json()
    assert crear.fila("SELECT invitacion_pendiente FROM usuarios WHERE correo = 'carlos@unas.co'")[
        "invitacion_pendiente"] == 0
    r = _invitar(client, correo="ana@unas.co", cc="1144999888", password="Clave5678")
    assert r.status_code == 400 and "no coinciden" in r.get_json()["msg"]


def test_invitar_respeta_el_tope_de_profesionales(client, crear):
    _admin_con_negocio(client)
    crear.fila("UPDATE tiendas SET plan_id = 'basico'")
    for i in range(3):
        assert _invitar(client, correo=f"p{i}@unas.co", cc=f"11440000{i}0").status_code == 201
    r = _invitar(client, correo="p9@unas.co", cc="1144000990")
    assert r.status_code == 403 and r.get_json()["code"] == "limite_plan"


# ---------- Aislamiento entre negocios ----------

def test_un_negocio_no_ve_ni_toca_los_datos_de_otro(client, app, crear):
    # Negocio A con su equipo.
    assert _registrar(client).status_code == 302
    id_carlos = _invitar(client).get_json()["id_usuario"]
    sede_a = crear.fila("SELECT id_sede FROM sedes WHERE id_tienda = 1")["id_sede"]
    id_laura = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'laura@unas.co'")["id_usuario"]

    # Negocio B, registrado por otra persona.
    b = app.test_client()
    r = b.post("/registro", data=_registro(
        nombre_negocio="Barbería Norte", tipo_negocio="barberia", admin_nombre="Pedro",
        admin_cc="1144555666", admin_correo="pedro@norte.co"))
    assert r.location.endswith("/inicio")

    equipo_b = b.get("/equipo").get_data(as_text=True)
    assert "Pedro" in equipo_b
    assert "laura@unas.co" not in equipo_b and "carlos@unas.co" not in equipo_b
    sedes_b = b.get("/sedes").get_data(as_text=True)
    assert "Uñas Divinas" not in sedes_b

    # Cualquier ID de A responde como si no existiera.
    for id_ajeno in (id_carlos, id_laura):
        assert b.put(f"/api/usuarios/{id_ajeno}", json={"nombre": "X", "rol": "Admin"}).status_code == 404
        assert b.delete(f"/api/usuarios/{id_ajeno}").status_code == 404
        assert b.post(f"/api/usuarios/{id_ajeno}/invitacion").status_code == 404
    assert b.put(f"/api/sedes/{sede_a}", json={"nombre": "Robada"}).status_code == 404
    assert b.delete(f"/api/sedes/{sede_a}").status_code == 404
    assert b.post("/seleccionar-sede", data={"id_sede": sede_a}).status_code in (302, 404)
    with b.session_transaction() as s:
        assert s["id_sede"] != sede_a
    # Crear un usuario con la sede de A tampoco pasa.
    r = b.post("/api/usuarios", json={"nombre": "Infiltrado", "cc": "1144777888", "correo": "x@norte.co",
                                      "rol": "Profesional", "id_sede": sede_a})
    assert r.status_code in (400, 404)

    # A sigue intacto.
    assert crear.fila("SELECT nombre FROM sedes WHERE id_sede = %s", (sede_a,))["nombre"] == "Principal"
    fila = crear.fila("SELECT nombre_completo, estado_activo FROM usuarios WHERE id_usuario = %s", (id_carlos,))
    assert fila["nombre_completo"] == "Carlos Ruiz" and fila["estado_activo"] == 1
    assert crear.fila("SELECT COUNT(*) AS n FROM usuarios WHERE id_tienda = 2")["n"] == 1
