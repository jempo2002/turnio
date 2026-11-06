"""Panel Master: alta de negocios, cambio de plan y renovacion."""

from conftest import entrar

NUEVO = {
    "nombre_negocio": "Barbería El Cuartel", "tipo_negocio": "barberia", "plan_id": "basico",
    "sede_nombre": "Centro", "admin_nombre": "Ana Dueña", "admin_cc": "1112223",
    "admin_correo": "ana@turnio.co", "admin_password": "Clave123",
}


def _master(client, crear):
    crear.usuario("master@turnio.co", "Master")
    assert entrar(client, "master@turnio.co").location.endswith("/panel-master")


def test_crear_negocio_con_sede_admin_y_slug(client, crear):
    _master(client, crear)
    r = client.post("/api/master/negocios", json=NUEVO)
    assert r.status_code == 201, r.get_json()
    id_tienda = r.get_json()["id_tienda"]
    t = crear.fila(
        "SELECT plan_id, DATEDIFF(trial_ends_at, CURDATE()) AS dias, slug, tipo_negocio FROM tiendas "
        "WHERE id_tienda = %s", (id_tienda,),
    )
    # Prueba gratis: 14 dias del Pro, sin importar el plan que llegue en el alta.
    assert t["plan_id"] == "pro" and t["dias"] == 14
    assert t["slug"] == "barberia-el-cuartel" and t["tipo_negocio"] == "barberia"
    s = crear.fila("SELECT nombre, es_principal FROM sedes WHERE id_tienda = %s", (id_tienda,))
    assert s == {"nombre": "Centro", "es_principal": 1}
    assert client.post("/api/master/negocios", json=NUEVO).status_code == 409
    assert "Barbería El Cuartel" in client.get("/panel-master").get_data(as_text=True)

    nuevo = client.application.test_client()
    assert entrar(nuevo, "ana@turnio.co").location.endswith("/citas")


def test_slug_repetido_recibe_numero(client, crear):
    _master(client, crear)
    otro = dict(NUEVO, admin_correo="beto@turnio.co", admin_cc="4445556")
    assert client.post("/api/master/negocios", json=NUEVO).status_code == 201
    r = client.post("/api/master/negocios", json=otro)
    assert r.status_code == 201
    assert crear.fila("SELECT slug FROM tiendas WHERE id_tienda = %s", (r.get_json()["id_tienda"],))["slug"] == \
        "barberia-el-cuartel-2"
    malo = dict(NUEVO, tipo_negocio="restaurante", admin_correo="c@turnio.co", admin_cc="7778889")
    assert client.post("/api/master/negocios", json=malo).status_code == 400


def test_cambiar_plan(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda("basico")
    assert client.put(f"/api/master/negocios/{id_tienda}/plan", json={"plan_id": "pro"}).status_code == 200
    assert crear.fila("SELECT plan_id FROM tiendas WHERE id_tienda = %s", (id_tienda,))["plan_id"] == "pro"
    assert client.put(f"/api/master/negocios/{id_tienda}/plan", json={"plan_id": "cadena"}).status_code == 400


def test_cambio_de_plan_con_sedes_de_sobra_se_bloquea(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda("pro", sedes=("Centro", "Norte"))
    r = client.put(f"/api/master/negocios/{id_tienda}/plan", json={"plan_id": "basico"})
    assert r.status_code == 400 and "sedes" in r.get_json()["msg"]
    crear.fila("UPDATE sedes SET estado = 'Eliminada' WHERE nombre = 'Norte'")
    assert client.put(f"/api/master/negocios/{id_tienda}/plan", json={"plan_id": "basico"}).status_code == 200


def test_montaje_pendiente_y_cobrado(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda("pro")
    crear.fila("INSERT INTO sedes (id_tienda, nombre, costo_montaje) VALUES (%s, 'Norte', 79000)", (id_tienda,))
    assert "Montaje pendiente $79.000" in client.get("/panel-master").get_data(as_text=True)
    r = client.post(f"/api/master/negocios/{id_tienda}/montaje")
    assert r.status_code == 200 and "$79.000" in r.get_json()["msg"]
    assert client.post(f"/api/master/negocios/{id_tienda}/montaje").status_code == 404
    assert "Montaje pendiente" not in client.get("/panel-master").get_data(as_text=True)


def test_renovar_suma_desde_el_vencimiento(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda()
    crear.fila("UPDATE tiendas SET trial_ends_at = DATE_ADD(CURDATE(), INTERVAL 10 DAY) WHERE id_tienda = %s", (id_tienda,))
    assert client.post(f"/api/master/negocios/{id_tienda}/renovar", json={"meses": 1}).status_code == 200
    t = crear.fila("SELECT DATEDIFF(fecha_fin_suscripcion, CURDATE()) AS d FROM tiendas WHERE id_tienda = %s", (id_tienda,))
    assert t["d"] >= 10 + 28
    assert client.post(f"/api/master/negocios/{id_tienda}/renovar", json={"meses": 2}).status_code == 400


def test_eliminar_negocio_saca_a_sus_usuarios(client, crear):
    _master(client, crear)
    id_tienda, (sede,) = crear.tienda()
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    otro = client.application.test_client()
    entrar(otro, "admin@turnio.co")
    assert client.delete(f"/api/master/negocios/{id_tienda}").status_code == 200
    assert otro.get("/citas").location.endswith("/login")
    assert crear.fila("SELECT estado FROM sedes WHERE id_sede = %s", (sede,))["estado"] == "Eliminada"


def test_solo_el_master_entra_al_panel(client, crear):
    id_tienda, _ = crear.tienda()
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    entrar(client, "admin@turnio.co")
    assert client.get("/panel-master").status_code == 302
    assert client.post("/api/master/negocios", json=NUEVO).status_code == 403


# ── Panel Master ampliado: resumen, ficha, suspender, cobros y usuarios ──

def test_resumen_filtros_y_busqueda(client, crear):
    _master(client, crear)
    al_dia, _ = crear.tienda("pro", nombre="Uñas Bonitas")
    crear.fila("UPDATE tiendas SET fecha_fin_suscripcion = DATE_ADD(CURDATE(), INTERVAL 40 DAY) WHERE id_tienda = %s", (al_dia,))
    vencido, _ = crear.tienda("basico", nombre="Cejas Viejas")
    crear.fila("UPDATE tiendas SET fecha_fin_suscripcion = DATE_SUB(CURDATE(), INTERVAL 2 DAY) WHERE id_tienda = %s", (vencido,))
    html = client.get("/panel-master").get_data(as_text=True)
    assert "Ingreso mensual" in html and "$89.000" in html  # solo el que esta al dia
    html = client.get("/panel-master?situacion=vencido").get_data(as_text=True)
    assert "Cejas Viejas" in html and "Uñas Bonitas" not in html
    html = client.get("/panel-master?q=bonitas").get_data(as_text=True)
    assert "Uñas Bonitas" in html and "Cejas Viejas" not in html


def test_ficha_del_negocio(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda("multisede", nombre="Salon Tres", sedes=("Centro", "Norte", "Sur"))
    crear.usuario("dueno@turnio.co", "Admin", id_tienda)
    html = client.get(f"/panel-master/negocios/{id_tienda}").get_data(as_text=True)
    assert "Salon Tres" in html and "dueno@turnio.co" in html
    assert "Sede extra: $45.000/mes" in html and html.count("Incluida en el plan") == 2
    r = client.get("/panel-master/negocios/9999")
    assert r.status_code == 302 and r.location.endswith("/panel-master")


def test_editar_datos_del_negocio(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda(nombre="Viejo Nombre")
    crear.tienda(nombre="Ocupado")
    datos = {"nombre_negocio": "Nuevo Nombre", "tipo_negocio": "unas", "nit": "900123", "telefono": "3001234567",
             "slug": "nuevo-nombre"}
    assert client.put(f"/api/master/negocios/{id_tienda}", json=datos).status_code == 200
    t = crear.fila("SELECT nombre_negocio, tipo_negocio, slug, telefono FROM tiendas WHERE id_tienda = %s", (id_tienda,))
    assert t == {"nombre_negocio": "Nuevo Nombre", "tipo_negocio": "unas", "slug": "nuevo-nombre", "telefono": "3001234567"}
    assert client.put(f"/api/master/negocios/{id_tienda}", json=dict(datos, slug="ocupado")).status_code == 409
    assert client.put(f"/api/master/negocios/{id_tienda}", json=dict(datos, slug="Con Espacios")).status_code == 400


def test_suspender_saca_al_equipo_y_cierra_reservas(client, crear):
    _master(client, crear)
    id_tienda, (sede,) = crear.tienda(nombre="Barberia Pausa")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    otro = client.application.test_client()
    entrar(otro, "admin@turnio.co")
    assert client.post(f"/api/master/negocios/{id_tienda}/suspender").status_code == 200
    assert client.post(f"/api/master/negocios/{id_tienda}/suspender").status_code == 404
    assert otro.get("/citas").location.endswith("/login")
    r = client.application.test_client().post(
        "/login", json={"correo": "admin@turnio.co", "contrasena": "Clave123"})
    assert r.status_code == 403 and "suspendido" in r.get_json()["msg"]
    assert client.application.test_client().get("/r/barberia-pausa").status_code == 404
    assert "Reactivar negocio" in client.get(f"/panel-master/negocios/{id_tienda}").get_data(as_text=True)

    assert client.post(f"/api/master/negocios/{id_tienda}/reactivar").status_code == 200
    assert entrar(client.application.test_client(), "admin@turnio.co").status_code == 302
    assert crear.fila("SELECT estado FROM tiendas WHERE id_tienda = %s", (id_tienda,))["estado"] == "Activo"


def test_pagos_quedan_en_el_historial(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda("multisede", sedes=("Centro", "Norte", "Sur"))
    # Multisede con 3 sedes: 139.000 + 45.000 de la tercera.
    assert client.post(f"/api/master/negocios/{id_tienda}/renovar", json={"meses": 3}).status_code == 200
    r = client.post(f"/api/master/negocios/{id_tienda}/renovar",
                    json={"meses": 1, "monto": "150.000", "nota": "Descuento Nequi"})
    assert r.status_code == 200
    assert client.post(f"/api/master/negocios/{id_tienda}/renovar", json={"meses": 1, "monto": "abc"}).status_code == 400
    crear.fila("UPDATE sedes SET costo_montaje = 79000 WHERE nombre = 'Sur'")
    assert client.post(f"/api/master/negocios/{id_tienda}/montaje").status_code == 200
    filas = crear.fila(
        "SELECT GROUP_CONCAT(CONCAT(concepto, ':', monto) ORDER BY id_pago) AS p, "
        "COUNT(id_usuario) AS con_master FROM pagos_master WHERE id_tienda = %s", (id_tienda,))
    assert filas["p"] == "Mensualidad:552000,Mensualidad:150000,Montaje:79000" and filas["con_master"] == 3
    html = client.get(f"/panel-master/negocios/{id_tienda}").get_data(as_text=True)
    assert "Descuento Nequi" in html and "$552.000" in html
    assert "$781.000" in client.get("/panel-master").get_data(as_text=True)  # cobrado este mes


def test_corregir_vencimiento(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda()
    r = client.put(f"/api/master/negocios/{id_tienda}/vencimiento", json={"fecha": "2027-01-31"})
    assert r.status_code == 200
    assert str(crear.fila("SELECT fecha_fin_suscripcion AS f FROM tiendas WHERE id_tienda = %s", (id_tienda,))["f"]) == "2027-01-31"
    assert client.put(f"/api/master/negocios/{id_tienda}/vencimiento", json={"fecha": "ayer"}).status_code == 400
    assert crear.fila("SELECT COUNT(*) AS n FROM pagos_master")["n"] == 0


def test_usuarios_de_toda_la_plataforma(client, crear):
    _master(client, crear)
    a, _ = crear.tienda(nombre="Negocio A")
    b, _ = crear.tienda(nombre="Negocio B")
    crear.usuario("ana@a.co", "Admin", a)
    crear.usuario("beto@b.co", "Admin", b)
    html = client.get("/panel-master/usuarios").get_data(as_text=True)
    assert "ana@a.co" in html and "beto@b.co" in html and "master@turnio.co" in html
    html = client.get("/panel-master/usuarios?q=Negocio B").get_data(as_text=True)
    assert "beto@b.co" in html and "ana@a.co" not in html


def test_editar_usuario_respeta_reglas_del_negocio(client, crear):
    _master(client, crear)
    id_tienda, (sede,) = crear.tienda("basico")
    admin = crear.usuario("admin@turnio.co", "Admin", id_tienda)
    prof = crear.usuario("prof@turnio.co", "Profesional", id_tienda, sede)
    crear.usuario("otro@turnio.co", "Recepcion", id_tienda, sede)
    url = f"/api/master/usuarios/{prof}"
    # Correo y nombre, sin tocar rol ni sede (pantalla Usuarios).
    assert client.put(url, json={"nombre": "Prof Nuevo", "correo": "nuevo@turnio.co"}).status_code == 200
    assert crear.fila("SELECT correo, rol, id_sede FROM usuarios WHERE id_usuario = %s", (prof,)) == \
        {"correo": "nuevo@turnio.co", "rol": "Profesional", "id_sede": sede}
    assert client.put(url, json={"nombre": "X", "correo": "otro@turnio.co"}).status_code == 409
    # Basico: 1 Admin. Un segundo choca con el tope del plan.
    assert client.put(url, json={"nombre": "X", "correo": "nuevo@turnio.co", "rol": "Admin"}).status_code != 200
    # El unico Admin no deja de serlo.
    r = client.put(f"/api/master/usuarios/{admin}", json={"nombre": "A", "correo": "admin@turnio.co", "rol": "Recepcion",
                                                         "id_sede": sede})
    assert r.status_code == 400 and "Admin" in r.get_json()["msg"]


def test_cambiar_clave_y_desactivar(client, crear):
    _master(client, crear)
    id_tienda, _ = crear.tienda()
    admin = crear.usuario("admin@turnio.co", "Admin", id_tienda)
    prof = crear.usuario("prof@turnio.co", "Profesional", id_tienda)
    sesion = client.application.test_client()
    entrar(sesion, "admin@turnio.co")
    assert sesion.get("/citas").status_code == 200
    clave = {"password": "Nueva1234", "confirm_password": "Nueva1234"}
    assert client.put(f"/api/master/usuarios/{admin}/clave", json=dict(clave, confirm_password="x")).status_code == 400
    assert client.put(f"/api/master/usuarios/{admin}/clave", json=clave).status_code == 200
    assert sesion.get("/citas").location.endswith("/login")  # la sesion vieja se cerro
    assert entrar(client.application.test_client(), "admin@turnio.co", "Nueva1234").status_code == 302

    assert client.delete(f"/api/master/usuarios/{admin}").status_code == 400  # unico Admin
    assert client.delete(f"/api/master/usuarios/{prof}").status_code == 200
    assert crear.fila("SELECT estado_activo FROM usuarios WHERE id_usuario = %s", (prof,))["estado_activo"] == 0
    yo = crear.fila("SELECT id_usuario FROM usuarios WHERE rol = 'Master'")["id_usuario"]
    assert client.delete(f"/api/master/usuarios/{yo}").status_code == 400
    # Su propia clave: sigue dentro.
    assert client.put(f"/api/master/usuarios/{yo}/clave", json=clave).status_code == 200
    assert client.get("/panel-master").status_code == 200


def test_agregar_usuario_a_un_negocio(client, crear):
    _master(client, crear)
    id_tienda, (sede,) = crear.tienda("basico")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    nuevo = {"nombre": "Lina", "cc": "1234567", "correo": "lina@turnio.co", "rol": "Profesional"}
    assert client.post(f"/api/master/negocios/{id_tienda}/usuarios", json=nuevo).status_code == 400  # sin clave
    nuevo.update(password="Clave123", confirm_password="Clave123")
    assert client.post(f"/api/master/negocios/{id_tienda}/usuarios", json=nuevo).status_code == 201
    otro_admin = dict(nuevo, correo="dos@turnio.co", cc="7654321", rol="Admin")
    assert client.post(f"/api/master/negocios/{id_tienda}/usuarios", json=otro_admin).status_code != 201
    assert client.post("/api/master/negocios/9999/usuarios", json=dict(nuevo, correo="z@z.co", cc="99999")).status_code == 404


def test_un_admin_no_usa_las_apis_del_master(client, crear):
    id_tienda, _ = crear.tienda()
    otro = crear.usuario("otro@turnio.co", "Admin", id_tienda)
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    entrar(client, "admin@turnio.co")
    assert client.get("/panel-master/usuarios").status_code == 302
    assert client.get(f"/panel-master/negocios/{id_tienda}").status_code == 302
    assert client.put(f"/api/master/usuarios/{otro}/clave",
                      json={"password": "Nueva1234", "confirm_password": "Nueva1234"}).status_code == 403
    assert client.post(f"/api/master/negocios/{id_tienda}/suspender").status_code == 403
