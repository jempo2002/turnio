"""Crea una barberia de demostracion con los datos del prototipo.

Plan Basico, sede Principal con el horario de configuracion.html, 7
servicios, 7 productos, las citas de hoy de Carlos y Junior (con su bloqueo
de almuerzo) y los cobros de las citas ya completadas. Un usuario por rol:

    admin@turnio.demo      Admin        (configura el negocio)
    recepcion@turnio.demo  Recepcion    (agenda y caja)
    carlos@turnio.demo     Profesional
    junior@turnio.demo     Profesional

Todos con la misma contrasena, que se pide por consola (o DEMO_CLAVE).
Usa la base del .env (corre antes scripts/migrar.py). Si el negocio demo ya
existe no toca nada.

    python scripts/crear_demo.py

"""
from __future__ import annotations

import getpass
import os
import sys
from datetime import datetime, time, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from app import create_app  # noqa: E402
from app.services import master_service, usuario_service  # noqa: E402
from app.services.auth_service import first_password_policy_error  # noqa: E402
from app.utils.helpers import hoy_local  # noqa: E402
from database import get_db  # noqa: E402

NOMBRE = "Barbería Turnio Demo"
DOMINIO = "turnio.demo"

USUARIOS = [("Recepción Demo", "recepcion", "Recepcion", "1000000002"),
            ("Carlos", "carlos", "Profesional", "1000000003"),
            ("Junior", "junior", "Profesional", "1000000004")]

# dia (0 = lunes), abierto, abre, cierra. Almuerzo de 1 a 2 p. m. los dias abiertos.
HORARIO = [(0, 1, "08:00", "20:00"), (1, 1, "08:00", "20:00"), (2, 1, "08:00", "20:00"),
           (3, 1, "08:00", "20:00"), (4, 1, "08:00", "21:00"), (5, 1, "09:00", "21:00"),
           (6, 0, "10:00", "14:00")]

# nombre, duracion (min), precio, pago al profesional
SERVICIOS = [("Corte clásico", 45, 20000, 13000), ("Corte + barba", 60, 25000, 15000),
             ("Perfilado de barba", 30, 15000, 10000), ("Fade", 45, 18000, 12000),
             ("Corte + cejas", 45, 22000, 14000), ("Fade + diseño", 60, 30000, 19000),
             ("Cejas", 15, 6000, 4000)]

# codigo, emoji, nombre, stock, costo, precio, vendidos
PRODUCTOS = [("7701234000011", "🍺", "Cerveza en lata", 18, 3000, 5000, 42),
             ("7701234000028", "💧", "Agua 500 ml", 4, 1200, 2000, 31),
             ("7701234000035", "🍪", "Snack surtido", 11, 1800, 3000, 18),
             ("7701234000042", "🥤", "Gaseosa", 2, 2200, 3500, 25),
             ("7701234000059", "🧴", "Cera moldeadora", 7, 11000, 18000, 9),
             ("7701234000066", "☕", "Café", 0, 1000, 2500, 37),
             ("7701234000073", "🧴", "Gel fijador", 9, 6000, 10000, 4)]

# profesional, hora, cliente, servicio, telefono, estado (None = bloqueo de almuerzo)
CITAS = [("Carlos", "08:00", "Andrés Mejía", "Corte + barba", "573001112233", "completada"),
         ("Carlos", "10:00", "Julián Pardo", "Corte clásico", "573003334455", "reservada"),
         ("Carlos", "12:00", "Mateo Guzmán", "Corte + cejas", "573004445566", "reservada"),
         ("Carlos", "13:00", None, None, None, "bloqueada"),
         ("Carlos", "14:00", "Santiago Lozano", "Perfilado de barba", "573005556677", "reservada"),
         ("Carlos", "16:00", "Nicolás Vargas", "Corte + barba", "573006667788", "reservada"),
         ("Carlos", "18:00", "Daniel Ospina", "Fade + diseño", "573007778899", "reservada"),
         ("Junior", "09:00", "Kevin Ríos", "Fade", "573002223344", "completada"),
         ("Junior", "10:00", "Felipe Castaño", "Corte clásico", "573008889900", "reservada"),
         ("Junior", "13:00", None, None, None, "bloqueada"),
         ("Junior", "15:00", "Tomás Herrera", "Fade", "573009990011", "reservada"),
         ("Junior", "16:00", "Camilo Duque", "Corte + barba", "573001230045", "reservada")]

# Cobros de las citas completadas (metodo por cliente) y otros movimientos del dia.
METODO_COBRO = {"Andrés Mejía": "efectivo", "Kevin Ríos": "transferencia"}
OTROS_MOVIMIENTOS = [("ingreso", "Cerveza x2 + snack", 13000, "efectivo"),
                     ("ingreso", "Cera para cabello", 18000, "transferencia"),
                     ("salida", "Cuchillas y talco", 35000, "efectivo")]


def sembrar(clave: str) -> int | None:
    """Crea el negocio demo y devuelve su id_tienda; None si ya existia.
    Necesita un app context (el pool de conexiones)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM tiendas WHERE slug = %s AND estado <> 'Eliminado' LIMIT 1",
            (master_service.slug_base(NOMBRE),),
        )
        if cur.fetchone():
            return None
    finally:
        conn.close()

    id_tienda = master_service.crear_negocio({
        "nombre_negocio": NOMBRE, "tipo_negocio": "barberia", "telefono": "3000000000",
        "sede_nombre": "Principal", "admin_nombre": "Admin Demo", "admin_cc": "1000000001",
        "admin_correo": f"admin@{DOMINIO}", "admin_password": clave,
    })
    ids = {}
    for nombre, prefijo, rol, cc in USUARIOS:
        ids[nombre] = usuario_service.crear_usuario(id_tienda, {
            "nombre": nombre, "cc": cc, "rol": rol,
            "correo": f"{prefijo}@{DOMINIO}", "password": clave, "confirm_password": clave,
        })

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_sede FROM sedes WHERE id_tienda = %s AND es_principal = 1", (id_tienda,))
        id_sede = cur.fetchone()["id_sede"]
        cur.execute("SELECT id_usuario FROM usuarios WHERE id_tienda = %s AND rol = 'Admin'", (id_tienda,))
        id_admin = cur.fetchone()["id_usuario"]
        # En la demo atienden Carlos y Junior; el Admin no tiene agenda.
        cur.execute("UPDATE usuarios SET atiende = 0 WHERE id_usuario = %s", (id_admin,))

        cur.executemany(
            # REPLACE: la sede ya nace con el horario de fabrica.
            "REPLACE INTO horarios_sede (id_sede, dia, abierto, abre, cierra, almuerzo_desde, almuerzo_hasta) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(id_sede, dia, abierto, abre, cierra, "13:00" if abierto else None, "14:00" if abierto else None)
             for dia, abierto, abre, cierra in HORARIO],
        )
        # La demo trae el catalogo del prototipo, no el de referencia que
        # crear_negocio siembra para una barberia (T9).
        cur.execute("DELETE FROM servicios WHERE id_tienda = %s", (id_tienda,))
        servicios = {}
        for nombre, duracion, precio, pago in SERVICIOS:
            cur.execute(
                "INSERT INTO servicios (id_tienda, nombre, duracion_min, precio, pago_profesional) "
                "VALUES (%s, %s, %s, %s, %s)",
                (id_tienda, nombre, duracion, precio, pago),
            )
            servicios[nombre] = (cur.lastrowid, duracion, precio, pago)
        for codigo, emoji, nombre, stock, costo, precio, vendidos in PRODUCTOS:
            cur.execute(
                "INSERT INTO productos (id_tienda, codigo_barras, emoji, nombre, costo, precio, stock_minimo, vendidos) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (id_tienda, codigo, emoji, nombre, costo, precio, 3, vendidos),
            )
            id_producto = cur.lastrowid
            # El stock es de la sede (stock_sedes); la carga inicial va al kardex.
            cur.execute("INSERT INTO stock_sedes (id_sede, id_producto, stock) VALUES (%s, %s, %s)",
                        (id_sede, id_producto, stock))
            if stock:
                cur.execute(
                    "INSERT INTO movimientos_inventario (id_tienda, id_sede, id_producto, id_usuario, tipo, cantidad, "
                    "stock_anterior, stock_posterior, motivo) VALUES (%s, %s, %s, %s, 'Entrada', %s, 0, %s, 'Carga inicial')",
                    (id_tienda, id_sede, id_producto, id_admin, stock, stock),
                )

        hoy = hoy_local()
        for profesional, hora, cliente, servicio, telefono, estado in CITAS:
            inicio = datetime.combine(hoy, time.fromisoformat(hora))
            id_servicio, duracion, precio, pago = servicios.get(servicio, (None, 60, 0, 0))
            cur.execute(
                "INSERT INTO citas (id_tienda, id_sede, id_servicio, id_profesional, cliente_nombre, "
                "cliente_telefono, inicio, fin, estado, precio, nota, id_usuario_registra) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (id_tienda, id_sede, id_servicio, ids[profesional], cliente, telefono, inicio,
                 inicio + timedelta(minutes=duracion), estado, precio,
                 "Almuerzo" if estado == "bloqueada" else None, id_admin),
            )
            if estado == "completada":
                cur.execute(
                    "INSERT INTO movimientos_caja (id_tienda, id_sede, tipo, concepto, monto, metodo, "
                    "id_profesional, id_cita, pago_profesional, id_usuario_registra, fecha) "
                    "VALUES (%s, %s, 'ingreso', %s, %s, %s, %s, %s, %s, %s, %s)",
                    (id_tienda, id_sede, f"{servicio} · {cliente}", precio, METODO_COBRO[cliente],
                     ids[profesional], cur.lastrowid, pago, id_admin, inicio + timedelta(minutes=duracion)),
                )
        cur.executemany(
            "INSERT INTO movimientos_caja (id_tienda, id_sede, tipo, concepto, monto, metodo, id_usuario_registra) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(id_tienda, id_sede, tipo, concepto, monto, metodo, id_admin)
             for tipo, concepto, monto, metodo in OTROS_MOVIMIENTOS],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return id_tienda


def main() -> int:
    clave = os.environ.get("DEMO_CLAVE") or getpass.getpass("Contrasena para los usuarios demo: ")
    error = first_password_policy_error(clave)
    if error:
        print(error)
        return 2

    app = create_app()
    with app.app_context():
        id_tienda = sembrar(clave)
    if id_tienda is None:
        print(f'"{NOMBRE}" ya existe. Entra con admin@{DOMINIO}.')
        return 0
    print(f'Listo: "{NOMBRE}" con {len(SERVICIOS)} servicios, {len(PRODUCTOS)} productos y {len(CITAS)} citas hoy.')
    print("Usuarios: " + ", ".join(f"{p}@{DOMINIO}" for p in ["admin"] + [u[1] for u in USUARIOS]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
