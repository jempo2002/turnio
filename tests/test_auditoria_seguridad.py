"""Auditoria de seguridad (la misma de jemPOS, aplicada a Turnio).

- Otro negocio: con los IDs de un negocio ajeno, ninguna API lee ni cambia
  nada suyo (sus filas quedan identicas).
- Montos y cantidades raros (true, 2.5, negativos, enormes, infinito, listas)
  dan 400 y no tocan la base; nunca un 500.
- Cambiar la contrasena cierra las demas sesiones de la cuenta.
- Dos peticiones iguales al mismo tiempo (doble clic, dos celulares) no
  cobran, liquidan ni anulan dos veces.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from conftest import CLAVE, DB_NAME, _conectar, entrar
from test_caja import _cita, _negocio, _producto

from app.utils.helpers import ahora_local

_TABLAS_TIENDA = (
    "tiendas", "sedes", "usuarios", "servicios", "productos", "citas", "ventas", "movimientos_caja",
    "cajas_dia", "liquidaciones", "movimientos_inventario", "imagenes",
)


def _foto(id_tienda: int) -> dict:
    """Todas las filas del negocio, para comparar antes y despues."""
    filas = {}
    for tabla in _TABLAS_TIENDA:
        filas[tabla] = _todas(f"SELECT * FROM `{tabla}` WHERE id_tienda = %s ORDER BY 1", (id_tienda,))
    filas["stock_sedes"] = _todas(
        "SELECT ss.* FROM stock_sedes ss JOIN sedes s ON s.id_sede = ss.id_sede WHERE s.id_tienda = %s "
               "ORDER BY 1, 2", (id_tienda,))
    filas["profesional_servicios"] = _todas(
        "SELECT ps.* FROM profesional_servicios ps JOIN usuarios u ON u.id_usuario = ps.id_usuario "
               "WHERE u.id_tienda = %s ORDER BY 1, 2", (id_tienda,))
    filas["horarios_sede"] = _todas(
        "SELECT h.* FROM horarios_sede h JOIN sedes s ON s.id_sede = h.id_sede WHERE s.id_tienda = %s "
               "ORDER BY 1, 2", (id_tienda,))
    return filas


def _todas(sql, params):
    conn = _conectar(database=DB_NAME)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _manana(hora: int) -> str:
    dia = (ahora_local() + timedelta(days=1)).date()
    return f"{dia.isoformat()}T{hora:02d}:00"


def _semana():
    return [{"dia": d, "abierto": True, "abre": "06:00", "cierra": "22:00"} for d in range(7)]


# ── Otro negocio ────────────────────────────────────────────────────

def test_ningun_id_de_otro_negocio_sirve(client, crear):
    victima = _negocio(client, crear, plan="multisede", sedes=("Principal", "Norte"))
    b0, b1 = victima["sedes"]
    cera = _producto(client)
    venta = client.post("/api/ventas", json={"items": [{"id_producto": cera}]}).get_json()["venta"]["id_venta"]
    gasto = client.post("/api/caja/gastos", json={"concepto": "Arriendo", "monto": 1000}).get_json()["id_movimiento"]
    cita = _cita(crear, victima, victima["carlos"], minutos=60)
    cobrada = _cita(crear, victima, victima["carlos"], minutos=180)
    assert client.post(f"/api/citas/{cobrada}/cobrar", json={}).status_code == 200
    r = client.post("/api/bloqueos", json={"desde": _manana(10), "hasta": _manana(11),
                                           "id_profesional": victima["junior"]})
    assert r.status_code == 201, r.get_json()
    bloqueo = r.get_json()["bloqueo"]["id_cita"]
    client.post("/logout")
    antes = _foto(victima["tienda"])

    otra, (a0, a1) = crear.tienda("multisede", nombre="Atacante", sedes=("Centro", "Sur"))
    crear.usuario("dueno@atacante.co", "Admin", otra)
    entrar(client, "dueno@atacante.co")
    client.post("/seleccionar-sede", data={"id_sede": a0})
    propia = _producto(client, nombre="Gel", codigo="7701234000066")

    ataques = [
        ("get", f"/api/citas/{cita}", None),
        ("put", f"/api/citas/{cita}", {"inicio": _manana(15)}),
        ("post", f"/api/citas/{cita}/cancelar", {}),
        ("post", f"/api/citas/{cita}/no-asistio", {}),
        ("post", f"/api/citas/{cita}/cobrar", {}),
        ("delete", f"/api/citas/{cobrada}/cobro", None),
        ("delete", f"/api/bloqueos/{bloqueo}", None),
        ("post", "/api/citas", {"id_profesional": victima["carlos"], "id_servicio": victima["corte"],
                                "inicio": _manana(9), "cliente_nombre": "Intruso"}),
        ("put", f"/api/servicios/{victima['corte']}", {"nombre": "Mío", "duracion_min": 30, "precio": 1}),
        ("delete", f"/api/servicios/{victima['corte']}", None),
        ("put", f"/api/productos/{cera}", {"nombre": "Mía", "precio": 1}),
        ("delete", f"/api/productos/{cera}", None),
        ("post", f"/api/productos/{cera}/movimientos", {"tipo": "Ajuste", "cantidad": 0}),
        ("get", f"/api/productos/{cera}/movimientos", None),
        ("post", "/api/ventas", {"items": [{"id_producto": cera}]}),
        ("delete", f"/api/ventas/{venta}", None),
        ("delete", f"/api/caja/movimientos/{gasto}", None),
        ("get", f"/api/caja?id_sede={b0}", None),
        ("post", "/api/inventario/traslados", {"id_producto": cera, "desde": b0, "hacia": b1, "cantidad": 1}),
        ("post", "/api/inventario/traslados", {"id_producto": propia, "desde": a0, "hacia": b1, "cantidad": 1}),
        ("post", "/api/comisiones/liquidar", {"id_profesional": victima["carlos"]}),
        ("put", f"/api/profesionales/{victima['carlos']}", {"reserva_online": False}),
        ("put", f"/api/usuarios/{victima['carlos']}", {"nombre": "Intruso", "rol": "Admin"}),
        ("delete", f"/api/usuarios/{victima['carlos']}", None),
        ("post", f"/api/usuarios/{victima['carlos']}/invitacion", {}),
        ("delete", f"/api/usuarios/{victima['carlos']}/foto", None),
        ("put", f"/api/sedes/{b1}", {"nombre": "Mía"}),
        ("delete", f"/api/sedes/{b1}", None),
        ("put", "/api/horario", {"id_sede": b0, "dias": _semana()}),
        ("get", f"/api/horario?id_sede={b0}", None),
    ]
    abiertos = []
    for metodo, ruta, cuerpo in ataques:
        r = getattr(client, metodo)(ruta, json=cuerpo) if cuerpo is not None else getattr(client, metodo)(ruta)
        if r.status_code not in (400, 403, 404):
            abiertos.append((metodo.upper(), ruta, r.status_code, r.get_json()))
    assert abiertos == [], "\n".join(map(str, abiertos))
    assert _foto(victima["tienda"]) == antes


# ── Montos raros ────────────────────────────────────────────────────

_RAROS = [True, -1, 2.5, 10**15, "abc", "1e3", [5], {"x": 1}]


@pytest.fixture
def caja_lista(client, crear):
    n = _negocio(client, crear, plan="multisede", sedes=("Principal", "Norte"))
    n["cera"] = _producto(client, stock=10)
    n["cita"] = _cita(crear, n, n["carlos"], minutos=30)
    n["antes"] = _foto(n["tienda"])
    return n


def _envios(n, v):
    s0, s1 = n["sedes"]
    return [
        ("post", "/api/caja/gastos", {"concepto": "X", "monto": v}),
        ("put", "/api/caja/base", {"base": v}),
        ("post", "/api/caja/cierre", {"contado": v}),
        ("post", "/api/servicios", {"nombre": "Tinte", "duracion_min": 30, "precio": v}),
        ("post", "/api/servicios", {"nombre": "Tinte", "duracion_min": v, "precio": 1000}),
        ("put", f"/api/servicios/{n['corte']}", {"nombre": "Corte", "duracion_min": 45, "precio": 25000,
                                                  "pago_profesional": v}),
        ("post", "/api/productos", {"nombre": "Gel", "precio": v}),
        ("post", "/api/productos", {"nombre": "Gel", "precio": 100, "stock": v}),
        ("put", f"/api/productos/{n['cera']}", {"nombre": "Cera", "precio": 18000, "costo": v}),
        ("post", f"/api/productos/{n['cera']}/movimientos", {"tipo": "Entrada", "cantidad": v}),
        ("post", "/api/ventas", {"items": [{"id_producto": n["cera"], "cantidad": v}]}),
        ("post", "/api/ventas", {"items": [{"id_producto": n["cera"]}],
                                 "pagos": [{"metodo": "efectivo", "monto": v}]}),
        ("post", f"/api/citas/{n['cita']}/cobrar", {"precio": v}),
        ("post", "/api/inventario/traslados", {"id_producto": n["cera"], "desde": s0, "hacia": s1, "cantidad": v}),
        ("put", f"/api/profesionales/{n['carlos']}", {"servicios": [{"id_servicio": n["corte"],
                                                                    "pago_profesional": v}]}),
    ]


@pytest.mark.parametrize("valor", _RAROS, ids=repr)
def test_montos_y_cantidades_raros_dan_400_y_no_tocan_nada(client, crear, caja_lista, valor):
    fallas = []
    s0, s1 = caja_lista["sedes"]
    envios = _envios(caja_lista, valor) + [
        # Un ID raro: 400, o 404 si es un entero valido que no existe.
        ("post", "/api/inventario/traslados", {"id_producto": valor, "desde": s0, "hacia": s1, "cantidad": 1}),
    ]
    for metodo, ruta, cuerpo in envios:
        r = getattr(client, metodo)(ruta, json=cuerpo)
        esperado = (400, 404) if "id_producto" in cuerpo and cuerpo["id_producto"] == valor else (400,)
        if r.status_code not in esperado:
            fallas.append((metodo.upper(), ruta, cuerpo, r.status_code))
    assert fallas == []
    assert _foto(caja_lista["tienda"]) == caja_lista["antes"]


def test_infinito_en_el_json_no_rompe_el_servidor(client, crear, caja_lista):
    # JSON acepta 1e400; Python lo lee como infinito e int() lanzaba OverflowError.
    for ruta, cuerpo in (
        ("/api/caja/gastos", '{"concepto": "X", "monto": 1e400}'),
        ("/api/ventas", '{"items": [{"id_producto": %d, "cantidad": 1e400}]}' % caja_lista["cera"]),
        ("/api/servicios", '{"nombre": "Tinte", "duracion_min": 30, "precio": -1e400}'),
    ):
        r = client.post(ruta, data=cuerpo, content_type="application/json")
        assert r.status_code == 400, (ruta, r.status_code)
    assert _foto(caja_lista["tienda"]) == caja_lista["antes"]


# ── Sesiones ────────────────────────────────────────────────────────

def test_cambiar_la_clave_cierra_las_otras_sesiones(app, crear):
    id_tienda, _ = crear.tienda("pro")
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    celular, computador, vieja = app.test_client(), app.test_client(), app.test_client()
    for c in (celular, computador, vieja):
        entrar(c, "admin@turnio.co")
        assert c.get("/api/servicios").status_code == 200
    # Una sesion abierta antes de este cambio (sin huella) la adopta sin salir.
    with vieja.session_transaction() as s:
        s.pop("huella")
    assert vieja.get("/api/servicios").status_code == 200

    r = computador.put("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "NuevaClave456"})
    assert r.status_code == 200, r.get_json()
    assert celular.get("/api/servicios").status_code == 401
    assert vieja.get("/api/servicios").status_code == 401
    assert computador.get("/api/servicios").status_code == 200  # quien la cambio sigue adentro

    # Un reset por correo cambia el hash igual: tambien cierra esta.
    crear.fila("UPDATE usuarios SET clave_hash = CONCAT(clave_hash, 'x') WHERE correo = 'admin@turnio.co'")
    assert computador.get("/api/servicios").status_code == 401


# ── Doble clic ──────────────────────────────────────────────────────

def _a_la_vez(app, cliente_base, n, peticion):
    """`n` clientes con la misma sesion lanzan `peticion` al mismo tiempo."""
    with cliente_base.session_transaction() as s:
        datos = dict(s)
    clientes = []
    for _ in range(n):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(datos)
        clientes.append(c)
    salida = threading.Barrier(n)

    def _uno(c):
        salida.wait()
        return peticion(c).status_code

    with ThreadPoolExecutor(n) as hilos:
        return sorted(hilos.map(_uno, clientes))


def test_cobro_liquidacion_y_anulacion_simultaneos_pasan_una_vez(app, client, crear):
    n = _negocio(client, crear)
    cita = _cita(crear, n, n["carlos"], minutos=-60)
    codigos = _a_la_vez(app, client, 5, lambda c: c.post(f"/api/citas/{cita}/cobrar", json={}))
    assert codigos.count(200) == 1, codigos
    assert crear.fila("SELECT COUNT(*) AS n FROM movimientos_caja WHERE id_cita = %s", (cita,))["n"] == 1

    codigos = _a_la_vez(app, client, 5, lambda c: c.post("/api/comisiones/liquidar",
                                                          json={"id_profesional": n["carlos"]}))
    assert codigos.count(201) == 1, codigos
    assert crear.fila("SELECT COUNT(*) AS n FROM liquidaciones")["n"] == 1

    cera = _producto(client, stock=10)
    venta = client.post("/api/ventas", json={"items": [{"id_producto": cera, "cantidad": 3}]}).get_json()
    codigos = _a_la_vez(app, client, 5, lambda c: c.delete(f"/api/ventas/{venta['venta']['id_venta']}"))
    assert codigos.count(200) == 1, codigos
    assert crear.fila("SELECT stock FROM stock_sedes WHERE id_producto = %s", (cera,))["stock"] == 10
