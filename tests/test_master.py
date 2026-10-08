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
    assert entrar(nuevo, "ana@turnio.co").location.endswith("/inicio")


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
    assert otro.get("/inicio").location.endswith("/login")
    assert crear.fila("SELECT estado FROM sedes WHERE id_sede = %s", (sede,))["estado"] == "Eliminada"


def test_solo_el_master_entra_al_panel(client, crear):
    id_tienda, _ = crear.tienda()
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    entrar(client, "admin@turnio.co")
    assert client.get("/panel-master").status_code == 302
    assert client.post("/api/master/negocios", json=NUEVO).status_code == 403
