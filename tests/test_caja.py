"""T5: caja del dia, cobro de citas, venta rapida, inventario, cierre y comisiones."""
from datetime import timedelta

from conftest import entrar

from app.utils.helpers import ahora_local


def _negocio(client, crear, plan="pro", sedes=("Principal",)):
    """Negocio con Admin (en sesion), Recepcion, dos profesionales y un servicio."""
    id_tienda, ids = crear.tienda(plan, sedes=sedes)
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    crear.usuario("ana@turnio.co", "Recepcion", id_tienda, ids[0])
    carlos = crear.usuario("carlos@turnio.co", "Profesional", id_tienda, ids[0])
    junior = crear.usuario("junior@turnio.co", "Profesional", id_tienda, ids[0])
    entrar(client, "admin@turnio.co")
    if len(ids) > 1:
        client.post("/seleccionar-sede", data={"id_sede": ids[0]})
    r = client.post("/api/servicios", json={"nombre": "Corte", "duracion_min": 45, "precio": 25000,
                                            "pago_profesional": 15000})
    return {"tienda": id_tienda, "sedes": ids, "carlos": carlos, "junior": junior,
            "corte": r.get_json()["id_servicio"]}


def _cita(crear, n, id_profesional, minutos=0, precio=25000):
    inicio = ahora_local().replace(second=0, microsecond=0) + timedelta(minutes=minutos)
    crear.fila(
        "INSERT INTO citas (id_tienda, id_sede, id_servicio, id_profesional, cliente_nombre, inicio, fin, precio) "
        "VALUES (%s, %s, %s, %s, 'Andrés', %s, %s, %s)",
        (n["tienda"], n["sedes"][0], n["corte"], id_profesional, inicio, inicio + timedelta(minutes=45), precio),
    )
    return crear.fila("SELECT MAX(id_cita) AS id FROM citas")["id"]


def _producto(client, nombre="Cera", codigo="7701234000059", stock=10, precio=18000, costo=11000, **extra):
    r = client.post("/api/productos", json={"nombre": nombre, "codigo_barras": codigo, "stock": stock,
                                            "precio": precio, "costo": costo, **extra})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id_producto"]


def _caja(client, **params):
    return client.get("/api/caja", query_string=params).get_json()["caja"]


def test_cobro_de_cita_con_pago_mixto_y_desglose(client, crear):
    n = _negocio(client, crear)
    id_cita = _cita(crear, n, n["carlos"])
    r = client.post(f"/api/citas/{id_cita}/cobrar", json={"pagos": [
        {"metodo": "efectivo", "monto": 10000}, {"metodo": "transferencia", "monto": 10000}]})
    assert r.status_code == 400  # no suma el total
    r = client.post(f"/api/citas/{id_cita}/cobrar", json={"pagos": [
        {"metodo": "efectivo", "monto": 10000}, {"metodo": "transferencia", "monto": 15000}]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["cobro"] == {"id_cita": id_cita, "total": 25000, "pago_profesional": 15000, "local": 10000,
                                     "id_profesional": n["carlos"]}
    assert crear.fila("SELECT estado FROM citas WHERE id_cita = %s", (id_cita,))["estado"] == "completada"
    assert client.post(f"/api/citas/{id_cita}/cobrar", json={}).status_code == 409  # dos veces no

    caja = _caja(client)
    assert (caja["ingresos"], caja["efectivo_esperado"], caja["transferencias"]) == (25000, 10000, 15000)
    assert caja["comisiones"] == 15000 and caja["local"] == 10000
    assert caja["profesionales"] == [{"id_profesional": n["carlos"], "nombre": "Carlos", "citas": 1,
                                      "total": 25000, "pago": 15000, "local": 10000}]
    assert len(caja["movimientos"]) == 2  # una fila por metodo
    assert sum(m["pago_profesional"] or 0 for m in caja["movimientos"]) == 15000  # la comision, una vez

    # Deshacer con su horario ya ocupado por otra cita: no.
    otra = _cita(crear, n, n["carlos"], 15)
    assert client.delete(f"/api/citas/{id_cita}/cobro").status_code == 409
    crear.fila("UPDATE citas SET estado = 'cancelada' WHERE id_cita = %s", (otra,))
    # Deshacer: sale de caja y la cita vuelve a estar por cobrar.
    assert client.delete(f"/api/citas/{id_cita}/cobro").status_code == 200
    assert crear.fila("SELECT estado FROM citas WHERE id_cita = %s", (id_cita,))["estado"] == "reservada"
    assert _caja(client)["ingresos"] == 0


def test_pago_propio_del_profesional_y_precio_cambiado(client, crear):
    n = _negocio(client, crear)
    r = client.put(f"/api/profesionales/{n['junior']}",
                   json={"servicios": [{"id_servicio": n["corte"], "pago_profesional": 18000}]})
    assert r.status_code == 200
    id_cita = _cita(crear, n, n["junior"])
    cobro = client.post(f"/api/citas/{id_cita}/cobrar", json={"metodo": "transferencia"}).get_json()["cobro"]
    assert cobro["pago_profesional"] == 18000
    # Descuento por debajo de lo que gana: el profesional no gana mas que lo cobrado.
    id_cita = _cita(crear, n, n["carlos"], 60)
    cobro = client.post(f"/api/citas/{id_cita}/cobrar", json={"precio": 12000}).get_json()["cobro"]
    assert (cobro["total"], cobro["pago_profesional"]) == (12000, 12000)


def test_profesional_solo_cobra_sus_citas(client, crear):
    n = _negocio(client, crear)
    ajena = _cita(crear, n, n["junior"])
    suya = _cita(crear, n, n["carlos"], 60)
    sin_profesional = _cita(crear, n, None, 120)
    client.post("/logout")
    entrar(client, "carlos@turnio.co")
    assert client.post(f"/api/citas/{ajena}/cobrar", json={}).status_code == 404
    assert client.post(f"/api/citas/{suya}/cobrar", json={}).status_code == 200
    # Sin profesional asignado: queda a nombre de quien la cobra.
    assert client.post(f"/api/citas/{sin_profesional}/cobrar", json={}).status_code == 200
    fila = crear.fila("SELECT id_profesional FROM citas WHERE id_cita = %s", (sin_profesional,))
    assert fila["id_profesional"] == n["carlos"]
    assert client.get("/api/caja").status_code == 403  # la caja es de Admin y Recepcion
    assert client.delete(f"/api/citas/{suya}/cobro").status_code == 200

    # Recepcion no atiende: una cita sin profesional no se le puede cargar.
    client.post("/logout")
    entrar(client, "ana@turnio.co")
    otra = _cita(crear, n, None, 180)
    assert client.post(f"/api/citas/{otra}/cobrar", json={}).status_code == 400


def test_venta_rapida_por_codigo_descuenta_stock_y_anula(client, crear):
    _negocio(client, crear)
    cera = _producto(client)
    agua = _producto(client, "Agua", "7701234000028", stock=2, precio=2000, costo=1200)
    assert client.get("/api/productos/codigo/7701234000028").get_json()["producto"]["stock"] == 2
    assert client.get("/api/productos/codigo/000").status_code == 404

    r = client.post("/api/ventas", json={"items": [{"codigo_barras": "7701234000028", "cantidad": 3}]})
    assert r.status_code == 409 and "Agua (quedan 2)" in r.get_json()["msg"]
    r = client.post("/api/ventas", json={"metodo": "efectivo", "items": [
        {"codigo_barras": "7701234000059"}, {"id_producto": agua, "cantidad": 2}, {"id_producto": cera}]})
    assert r.status_code == 201, r.get_json()
    venta = r.get_json()["venta"]
    assert venta["total"] == 18000 * 2 + 2000 * 2
    productos = {p["id_producto"]: p for p in client.get("/api/productos").get_json()["productos"]}
    assert (productos[cera]["stock"], productos[cera]["vendidos"]) == (8, 2)
    assert productos[agua]["stock"] == 0
    caja = _caja(client)
    assert caja["productos"] == 40000 and caja["local"] == 40000
    assert caja["movimientos"][0]["concepto"] == "Cera x2 + Agua x2"

    # Recepcion anula: vuelve el stock, sale de caja, el kardex guarda todo.
    client.post("/logout")
    entrar(client, "ana@turnio.co")
    assert client.delete(f"/api/ventas/{venta['id_venta']}").status_code == 200
    assert client.delete(f"/api/ventas/{venta['id_venta']}").status_code == 409
    assert client.get("/api/productos/codigo/7701234000059").get_json()["producto"]["stock"] == 10
    assert _caja(client)["ingresos"] == 0
    tipos = [m["tipo"] for m in client.get(f"/api/productos/{cera}/movimientos").get_json()["movimientos"]]
    assert tipos == ["Anulacion", "Venta", "Entrada"]


def test_profesional_vende_pero_no_ve_costos_ni_toca_el_catalogo(client, crear):
    _negocio(client, crear)
    cera = _producto(client)
    client.post("/logout")
    entrar(client, "carlos@turnio.co")
    producto = client.get("/api/productos").get_json()["productos"][0]
    assert "costo" not in producto
    assert client.post("/api/ventas", json={"items": [{"id_producto": cera}]}).status_code == 201
    assert client.post("/api/productos", json={"nombre": "X", "precio": 1}).status_code == 403
    assert client.post(f"/api/productos/{cera}/movimientos", json={"tipo": "Entrada", "cantidad": 1}).status_code == 403


def test_movimientos_de_inventario_y_codigo_unico(client, crear):
    _negocio(client, crear)
    cera = _producto(client, stock_minimo=5)
    assert client.post("/api/productos", json={"nombre": "Otra", "codigo_barras": "7701234000059",
                                               "precio": 1}).status_code == 409
    assert client.post("/api/productos", json={"nombre": "Sin código", "precio": 1000}).status_code == 201

    mover = lambda **d: client.post(f"/api/productos/{cera}/movimientos", json=d)  # noqa: E731
    assert mover(tipo="Entrada", cantidad=5).get_json()["stock"] == 15
    assert mover(tipo="Salida", cantidad=20).status_code == 409
    assert mover(tipo="Ajuste", cantidad=4).get_json()["stock"] == 4
    alertas = client.get("/api/inventario/alertas").get_json()["productos"]
    assert [p["id_producto"] for p in alertas] == [cera]

    assert client.delete(f"/api/productos/{cera}").status_code == 200
    _producto(client, "Cera nueva")  # el codigo quedo libre


def test_basico_topa_en_150_productos_y_sin_alertas(client, crear, db):
    n = _negocio(client, crear, plan="basico")
    cur = db.cursor()
    cur.executemany("INSERT INTO productos (id_tienda, nombre, precio) VALUES (%s, %s, 1000)",
                    [(n["tienda"], f"P{i}") for i in range(149)])
    _producto(client)
    r = client.post("/api/productos", json={"nombre": "Uno más", "precio": 1000})
    assert r.status_code == 403 and r.get_json()["code"] == "limite_plan"
    assert client.get("/api/inventario/alertas").get_json()["code"] == "funcion_no_incluida"
    assert client.get("/api/comisiones").status_code == 403


def test_gastos_cierre_con_arqueo_y_reapertura(client, crear):
    n = _negocio(client, crear)
    assert client.put("/api/caja/base", json={"base": 50000}).status_code == 200
    id_cita = _cita(crear, n, n["carlos"])
    client.post(f"/api/citas/{id_cita}/cobrar", json={"metodo": "efectivo"})
    r = client.post("/api/caja/gastos", json={"concepto": "Cuchillas", "monto": 8000, "metodo": "efectivo"})
    assert r.status_code == 201
    id_gasto = r.get_json()["id_movimiento"]
    otro = client.post("/api/caja/gastos", json={"concepto": "Talco", "monto": 2000}).get_json()["id_movimiento"]
    assert client.delete(f"/api/caja/movimientos/{otro}").status_code == 200

    caja = _caja(client)
    assert caja["efectivo_esperado"] == 50000 + 25000 - 8000
    assert caja["gastos"] == 8000 and caja["local"] == 25000 - 15000 - 8000

    r = client.post("/api/caja/cierre", json={"contado": 66000, "observaciones": "Faltan mil"})
    assert r.status_code == 200
    assert (r.get_json()["caja"]["diferencia"], r.get_json()["caja"]["estado"]) == (-1000, "cerrada")
    assert _caja(client)["cierre"]["contado"] == 66000

    # Cerrada: no entra nada ni se borra nada hasta reabrir.
    otra = _cita(crear, n, n["junior"], 60)
    assert client.post(f"/api/citas/{otra}/cobrar", json={}).status_code == 409
    assert client.post("/api/caja/gastos", json={"concepto": "X", "monto": 1}).status_code == 409
    assert client.delete(f"/api/caja/movimientos/{id_gasto}").status_code == 409
    assert client.delete(f"/api/citas/{id_cita}/cobro").status_code == 409

    client.post("/logout")
    entrar(client, "ana@turnio.co")
    assert client.post("/api/caja/reabrir", json={}).status_code == 403
    client.post("/logout")
    entrar(client, "admin@turnio.co")
    assert client.post("/api/caja/reabrir", json={}).status_code == 200
    assert client.post(f"/api/citas/{otra}/cobrar", json={}).status_code == 200
    assert client.post("/api/caja/cierre", json={"fecha": "2999-01-01", "contado": 0}).status_code == 400


def test_liquidacion_de_comisiones(client, crear):
    n = _negocio(client, crear)
    for minutos in (0, 60):
        client.post(f"/api/citas/{_cita(crear, n, n['carlos'], minutos)}/cobrar", json={})
    ultima = _cita(crear, n, n["junior"], 120)
    client.post(f"/api/citas/{ultima}/cobrar", json={})

    datos = client.get("/api/comisiones").get_json()
    pendientes = {p["id_profesional"]: p for p in datos["pendientes"]}
    assert (pendientes[n["carlos"]]["cobros"], pendientes[n["carlos"]]["total"]) == (2, 30000)

    r = client.post("/api/comisiones/liquidar", json={"id_profesional": n["carlos"], "metodo": "efectivo"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["liquidacion"]["total"] == 30000
    assert client.post("/api/comisiones/liquidar", json={"id_profesional": n["carlos"]}).status_code == 409

    caja = _caja(client)
    assert caja["pagos_profesionales"] == 30000
    assert caja["efectivo_esperado"] == 75000 - 30000
    assert caja["local"] == 75000 - 45000  # el pago no se descuenta dos veces
    # Un cobro ya liquidado no se deshace.
    primera = crear.fila("SELECT MIN(id_cita) AS id FROM citas")["id"]
    assert client.delete(f"/api/citas/{primera}/cobro").status_code == 409

    # El profesional ve solo lo suyo.
    client.post("/logout")
    entrar(client, "junior@turnio.co")
    datos = client.get("/api/comisiones").get_json()
    assert [p["id_profesional"] for p in datos["periodo"]] == [n["junior"]]
    assert datos["pendientes"][0]["total"] == 15000 and datos["liquidaciones"] == []
    assert client.post("/api/comisiones/liquidar", json={"id_profesional": n["junior"]}).status_code == 403


def test_resumen_del_mes_con_ganancia_real(client, crear):
    n = _negocio(client, crear, plan="basico")
    client.post(f"/api/citas/{_cita(crear, n, n['carlos'])}/cobrar", json={})
    cera = _producto(client)
    client.post("/api/ventas", json={"items": [{"id_producto": cera, "cantidad": 2}]})
    client.post("/api/caja/gastos", json={"concepto": "Arriendo", "monto": 5000})
    resumen = client.get("/api/caja/mes").get_json()["resumen"]
    assert resumen["ganancia"] == (25000 - 15000) + (36000 - 22000) - 5000
    assert resumen["principales_gastos"] == [{"concepto": "Arriendo", "veces": 1, "total": 5000}]


def test_multisede_caja_por_sede_consolidada_y_traslados(client, crear):
    n = _negocio(client, crear, plan="multisede", sedes=("Centro", "Norte"))
    centro, norte = n["sedes"]
    cera = _producto(client, stock=10)
    r = client.post("/api/inventario/traslados", json={"id_producto": cera, "desde": centro, "hacia": norte,
                                                       "cantidad": 4})
    assert r.status_code == 200, r.get_json()

    def stock(sede):
        return client.get("/api/productos", query_string={"id_sede": sede}).get_json()["productos"][0]["stock"]

    assert (stock(centro), stock(norte)) == (6, 4)
    assert client.post("/api/inventario/traslados", json={"id_producto": cera, "desde": norte, "hacia": centro,
                                                          "cantidad": 5}).status_code == 409

    client.post("/api/ventas", json={"items": [{"id_producto": cera}]})  # en Centro, la sede de la sesion
    client.post("/seleccionar-sede", data={"id_sede": norte})
    client.post("/api/caja/gastos", json={"concepto": "Aseo", "monto": 3000})
    assert _caja(client, id_sede=centro)["ingresos"] == 18000
    assert _caja(client)["salidas"] == 3000
    consolidada = _caja(client, id_sede="todas")
    assert (consolidada["ingresos"], consolidada["salidas"]) == (18000, 3000)
    cierre = client.post("/api/caja/cierre", json={"id_sede": centro, "contado": 18000}).get_json()["caja"]
    assert cierre["diferencia"] == 0


def test_caja_y_ventas_de_otro_negocio_no_se_tocan(client, crear):
    ajeno = _negocio(client, crear)
    cera = _producto(client)
    venta = client.post("/api/ventas", json={"items": [{"id_producto": cera}]}).get_json()["venta"]["id_venta"]
    id_cita = _cita(crear, ajeno, ajeno["carlos"])
    gasto = client.post("/api/caja/gastos", json={"concepto": "X", "monto": 1}).get_json()["id_movimiento"]
    client.post("/logout")

    otra, _ = crear.tienda("pro", nombre="Otro")
    crear.usuario("dueno@otro.co", "Admin", otra)
    entrar(client, "dueno@otro.co")
    assert client.get("/api/productos").get_json()["productos"] == []
    assert client.post("/api/ventas", json={"items": [{"id_producto": cera}]}).status_code == 404
    assert client.delete(f"/api/ventas/{venta}").status_code == 404
    assert client.post(f"/api/citas/{id_cita}/cobrar", json={}).status_code == 404
    assert client.delete(f"/api/caja/movimientos/{gasto}").status_code == 404
    assert client.put(f"/api/productos/{cera}", json={"nombre": "Mía", "precio": 1}).status_code == 404
    assert client.get("/api/caja", query_string={"id_sede": ajeno["sedes"][0]}).status_code == 404
    assert _caja(client)["ingresos"] == 0
