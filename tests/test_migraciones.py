"""Migraciones desde cero, el registro de aplicadas, el seed y las reglas de la base."""
import os
import shutil
from datetime import datetime, timedelta

import mysql.connector
import pytest

from conftest import CLAVE, base_vacia
from scripts import migrar as m

DB_MIGRAR = os.getenv("TEST_DB_NAME", "turnio_pytest") + "_migrar"


@pytest.fixture
def conn_vacia(base):
    conn = base_vacia(DB_MIGRAR)
    yield conn
    conn.cursor().execute(f"DROP DATABASE IF EXISTS `{DB_MIGRAR}`")
    conn.close()


def test_migra_desde_cero_y_la_segunda_vez_no_hace_nada(conn_vacia):
    aplicadas = m.migrar(conn_vacia, salida=lambda _: None)
    assert aplicadas == [os.path.basename(r) for r in m.archivos()]
    assert m.migrar(conn_vacia, salida=lambda _: None) == []
    cur = conn_vacia.cursor()
    cur.execute("SHOW TABLES")
    tablas = {fila[0] for fila in cur.fetchall()}
    assert {"tiendas", "sedes", "usuarios", "horarios_sede", "servicios", "citas", "productos",
            "movimientos_caja", "schema_migraciones"} <= tablas


def test_cada_migracion_se_puede_repetir(conn_vacia):
    """Una base que ya tiene el esquema (por ejemplo creada a mano con
    run_migration.py) se pone al dia sin errores."""
    for ruta in m.archivos():
        with open(ruta, encoding="utf-8") as fh:
            m._ejecutar(conn_vacia.cursor(), fh.read(), ruta)
    assert len(m.migrar(conn_vacia, salida=lambda _: None)) == len(m.archivos())


def test_detecta_una_migracion_aplicada_que_cambio(conn_vacia, tmp_path):
    for ruta in m.archivos():
        shutil.copy(ruta, tmp_path)
    m.migrar(conn_vacia, carpeta=str(tmp_path), salida=lambda _: None)
    primera = sorted(tmp_path.glob("*.sql"))[0]
    primera.write_text(primera.read_text(encoding="utf-8") + "\n-- editada\n", encoding="utf-8")
    with pytest.raises(m.MigracionError, match="cambio despues de aplicarse"):
        m.migrar(conn_vacia, carpeta=str(tmp_path), salida=lambda _: None)


def test_el_seed_carga_la_barberia_demo(app, crear):
    from scripts.crear_demo import CITAS, PRODUCTOS, SERVICIOS, sembrar

    with app.app_context():
        id_tienda = sembrar(CLAVE)
        assert sembrar(CLAVE) is None  # la segunda vez no duplica
    contar = lambda tabla: crear.fila(f"SELECT COUNT(*) AS n FROM {tabla} WHERE id_tienda = %s", (id_tienda,))["n"]  # noqa: E731
    assert contar("servicios") == len(SERVICIOS)
    assert contar("productos") == len(PRODUCTOS)
    assert contar("citas") == len(CITAS)
    assert contar("usuarios") == 4
    caja = crear.fila(
        "SELECT SUM(IF(tipo = 'ingreso', monto, -monto)) AS neto, SUM(pago_profesional) AS comisiones "
        "FROM movimientos_caja WHERE id_tienda = %s", (id_tienda,),
    )
    assert int(caja["neto"]) == 25000 + 18000 + 13000 + 18000 - 35000
    assert int(caja["comisiones"]) == 15000 + 12000
    assert crear.fila("SELECT COUNT(*) AS n FROM horarios_sede")["n"] == 7

    c = app.test_client()
    r = c.post("/login", data={"correo": "carlos@turnio.demo", "contrasena": CLAVE})
    assert r.location.endswith("/inicio")


def _cita(cur, id_tienda, id_sede, id_profesional, inicio, estado="reservada"):
    cur.execute(
        "INSERT INTO citas (id_tienda, id_sede, id_profesional, inicio, fin, estado) VALUES (%s, %s, %s, %s, %s, %s)",
        (id_tienda, id_sede, id_profesional, inicio, inicio + timedelta(minutes=45), estado),
    )
    return cur.lastrowid


def test_candado_de_reservas_por_profesional(crear, db):
    id_tienda, (sede,) = crear.tienda()
    carlos = crear.usuario("carlos@turnio.co", "Profesional", id_tienda, sede)
    junior = crear.usuario("junior@turnio.co", "Profesional", id_tienda, sede)
    cur = db.cursor()
    diez = datetime(2026, 10, 9, 10, 0)
    id_cita = _cita(cur, id_tienda, sede, carlos, diez)
    _cita(cur, id_tienda, sede, junior, diez)  # otro profesional, misma hora: si
    with pytest.raises(mysql.connector.IntegrityError):
        _cita(cur, id_tienda, sede, carlos, diez)
    with pytest.raises(mysql.connector.IntegrityError):
        _cita(cur, id_tienda, sede, carlos, diez, "bloqueada")
    # Cancelada, la franja queda libre otra vez.
    cur.execute("UPDATE citas SET estado = 'cancelada' WHERE id_cita = %s", (id_cita,))
    _cita(cur, id_tienda, sede, carlos, diez)


def test_la_base_rechaza_valores_imposibles(crear, db):
    id_tienda, (sede,) = crear.tienda()
    cur = db.cursor()
    with pytest.raises(mysql.connector.Error):  # paga al profesional mas que el precio
        cur.execute(
            "INSERT INTO servicios (id_tienda, nombre, duracion_min, precio, pago_profesional) "
            "VALUES (%s, 'Corte', 45, 20000, 25000)", (id_tienda,),
        )
    cur.execute("INSERT INTO productos (id_tienda, codigo_barras, nombre, precio) VALUES (%s, '1', 'Gel', 100)",
                (id_tienda,))
    id_gel = cur.lastrowid
    with pytest.raises(mysql.connector.Error):  # stock negativo
        cur.execute("INSERT INTO stock_sedes (id_sede, id_producto, stock) VALUES (%s, %s, -1)", (sede, id_gel))
    with pytest.raises(mysql.connector.Error):  # precio negativo
        cur.execute("INSERT INTO productos (id_tienda, nombre, precio) VALUES (%s, 'Cera', -1)", (id_tienda,))
    with pytest.raises(mysql.connector.Error):  # cita que termina antes de empezar
        cur.execute(
            "INSERT INTO citas (id_tienda, id_sede, inicio, fin) VALUES (%s, %s, '2026-10-09 10:00', '2026-10-09 09:00')",
            (id_tienda, sede),
        )
    with pytest.raises(mysql.connector.Error):  # almuerzo fuera del horario
        cur.execute(
            "INSERT INTO horarios_sede (id_sede, dia, abre, cierra, almuerzo_desde, almuerzo_hasta) "
            "VALUES (%s, 0, '08:00', '12:00', '13:00', '14:00')", (sede,),
        )
    cur.execute(
        "INSERT INTO productos (id_tienda, codigo_barras, nombre, precio) VALUES (%s, '77', 'Gel', 100)", (id_tienda,)
    )
    with pytest.raises(mysql.connector.IntegrityError):  # codigo repetido en el mismo negocio
        cur.execute(
            "INSERT INTO productos (id_tienda, codigo_barras, nombre, precio) VALUES (%s, '77', 'Cera', 100)",
            (id_tienda,),
        )


def test_el_stock_viejo_pasa_a_la_sede_principal(conn_vacia, tmp_path):
    """T5: productos.stock (de la tienda) pasa a stock_sedes de la principal."""
    rutas = m.archivos()
    t5 = next(r for r in rutas if r.endswith("_07_caja_inventario.sql"))
    for ruta in rutas[:rutas.index(t5)]:
        shutil.copy(ruta, tmp_path)
    m.migrar(conn_vacia, carpeta=str(tmp_path), salida=lambda _: None)
    cur = conn_vacia.cursor()
    cur.execute("INSERT INTO tiendas (nombre_negocio, slug) VALUES ('Vieja', 'vieja')")
    id_tienda = cur.lastrowid
    cur.execute("INSERT INTO sedes (id_tienda, nombre, es_principal) VALUES (%s, 'Otra', 0)", (id_tienda,))
    cur.execute("INSERT INTO sedes (id_tienda, nombre, es_principal) VALUES (%s, 'Principal', 1)", (id_tienda,))
    principal = cur.lastrowid
    cur.execute("INSERT INTO productos (id_tienda, codigo_barras, nombre, stock, precio) VALUES (%s, '1', 'Gel', 7, 100)",
                (id_tienda,))
    shutil.copy(t5, tmp_path)
    m.migrar(conn_vacia, carpeta=str(tmp_path), salida=lambda _: None)
    cur.execute("SELECT id_sede, stock FROM stock_sedes")
    assert cur.fetchall() == [(principal, 7)]
