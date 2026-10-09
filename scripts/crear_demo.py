"""Crea los negocios de demostracion para probar Turnio (local o staging).

1. "Barberia Turnio Demo": prueba del plan Pro, sede Principal con el horario
   de configuracion.html, 7 servicios, 7 productos, las citas de hoy de
   Carlos y Junior (con su bloqueo de almuerzo) y los cobros de las citas ya
   completadas. Dos Admin, que es el tope del plan:

    admin@turnio.demo      Admin        (configura el negocio)
    admin2@turnio.demo     Admin        (segundo Admin)
    recepcion@turnio.demo  Recepcion    (agenda y caja)
    carlos@turnio.demo     Profesional
    junior@turnio.demo     Profesional

2. "Salon Turnio Multisede Demo": plan Multisede con 3 sedes (Centro, Norte y
   Sur). La tercera pasa las 2 incluidas, asi que nace con su montaje
   pendiente y suma la sede extra a la mensualidad. Una estilista por sede,
   productos con stock por sede y citas de hoy:

    multisede@turnio.demo  Admin        (ve todas las sedes)
    norte@turnio.demo      Recepcion    (sede Norte)
    laura@turnio.demo      Profesional  (Centro)
    sofia@turnio.demo      Profesional  (Norte)
    valeria@turnio.demo    Profesional  (Sur)

Todos con la misma contrasena, que se pide por consola (o DEMO_CLAVE).
Usa la base del .env (corre antes scripts/migrar.py). Se puede correr las
veces que sea: un negocio que ya existe no se toca, solo se le crean los
usuarios demo que le falten.

La contrasena es conocida, asi que el script se niega a correr en
produccion (RAILWAY_ENVIRONMENT_NAME=production o, fuera de Railway,
FLASK_ENV=production) salvo con --en-produccion.

    python scripts/crear_demo.py

"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime, time, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from app import create_app  # noqa: E402
from app.services import master_service, sede_service, usuario_service  # noqa: E402
from app.services.auth_service import first_password_policy_error  # noqa: E402
from app.services.plan_service import LimitePlanError  # noqa: E402
from app.services.usuario_service import UsuarioError  # noqa: E402
from app.utils.helpers import hoy_local  # noqa: E402
from database import get_db  # noqa: E402

NOMBRE = "Barbería Turnio Demo"
DOMINIO = "turnio.demo"

# nombre, correo (antes de la @), rol, cedula
USUARIOS = [("Admin 2 Demo", "admin2", "Admin", "1000000005"),
            ("Recepción Demo", "recepcion", "Recepcion", "1000000002"),
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


MULTI_NOMBRE = "Salón Turnio Multisede Demo"
# La principal la crea crear_negocio; las otras dos, sede_service (la tercera
# pasa las 2 incluidas en el plan y nace con su montaje pendiente).
MULTI_SEDES = [("Centro", "Cl. 15 # 8-20, Tuluá"), ("Norte", "Av. 4N # 23-10, Cali"),
               ("Sur", "Cra. 100 # 11-60, Cali")]
MULTI_USUARIOS = [("Recepción Norte", "norte", "Recepcion", "1000000012", "Norte"),
                  ("Laura", "laura", "Profesional", "1000000013", "Centro"),
                  ("Sofía", "sofia", "Profesional", "1000000014", "Norte"),
                  ("Valeria", "valeria", "Profesional", "1000000015", "Sur")]
# codigo, emoji, nombre, costo, precio, stock por sede (Centro, Norte, Sur)
MULTI_PRODUCTOS = [("7701234100018", "🧴", "Shampoo sin sal", 14000, 24000, (8, 3, 0)),
                   ("7701234100025", "💆", "Ampolla capilar", 6000, 12000, (12, 6, 4)),
                   ("7701234100032", "💧", "Agua 500 ml", 1200, 2000, (20, 2, 10))]
# profesional, hora, cliente, servicio (del catalogo de peluqueria), telefono
MULTI_CITAS = [("Laura", "09:00", "Mariana López", "Corte de dama", "573011112233"),
               ("Laura", "15:00", "Paula Restrepo", "Cepillado", "573012223344"),
               ("Sofía", "10:00", "Daniela Cruz", "Tinte completo", "573013334455"),
               ("Sofía", "16:00", "Isabella Rojas", "Corte de dama", "573014445566"),
               ("Valeria", "11:00", "Camila Torres", "Keratina", "573015556677")]

def _id_tienda(nombre: str) -> int | None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id_tienda FROM tiendas WHERE slug = %s AND estado <> 'Eliminado' LIMIT 1",
            (master_service.slug_base(nombre),),
        )
        fila = cur.fetchone()
        return fila[0] if fila else None
    finally:
        conn.close()


def _crear_usuarios(id_tienda: int, usuarios, clave: str, sedes: dict | None = None) -> dict[str, int]:
    """Crea los usuarios demo que falten y devuelve {nombre: id_usuario} de
    los que quedaron. Cada usuario es (nombre, prefijo, rol, cc[, sede])."""
    ids = {}
    for nombre, prefijo, rol, cc, *sede in usuarios:
        correo = f"{prefijo}@{DOMINIO}"
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s AND estado_activo = 1", (correo,))
            fila = cur.fetchone()
        finally:
            conn.close()
        if fila:
            ids[nombre] = fila[0]
            continue
        datos = {"nombre": nombre, "cc": cc, "rol": rol, "correo": correo,
                 "password": clave, "confirm_password": clave}
        if sede:
            datos["id_sede"] = sedes[sede[0]]
        try:
            ids[nombre] = usuario_service.crear_usuario(id_tienda, datos)
        except (ValueError, LimitePlanError, UsuarioError) as exc:
            # Un negocio demo que alguien cambio a mano (otro plan, otro
            # usuario con esa cedula): se avisa y se sigue con el resto.
            print(f"No se creó {correo}: {exc}")
    return ids


def sembrar(clave: str) -> int | None:
    """Crea la barberia demo y devuelve su id_tienda; None si ya existia (en
    ese caso solo crea los usuarios que le falten). Necesita un app context
    (el pool de conexiones)."""
    existente = _id_tienda(NOMBRE)
    if existente:
        _crear_usuarios(existente, USUARIOS, clave)
        return None

    id_tienda = master_service.crear_negocio({
        "nombre_negocio": NOMBRE, "tipo_negocio": "barberia", "telefono": "3000000000",
        "sede_nombre": "Principal", "admin_nombre": "Admin Demo", "admin_cc": "1000000001",
        "admin_correo": f"admin@{DOMINIO}", "admin_password": clave,
    })
    ids = _crear_usuarios(id_tienda, USUARIOS, clave)

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_sede FROM sedes WHERE id_tienda = %s AND es_principal = 1", (id_tienda,))
        id_sede = cur.fetchone()["id_sede"]
        cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s", (f"admin@{DOMINIO}",))
        id_admin = cur.fetchone()["id_usuario"]
        # En la demo atienden Carlos y Junior; los Admin no tienen agenda.
        cur.execute("UPDATE usuarios SET atiende = 0 WHERE id_tienda = %s AND rol = 'Admin'", (id_tienda,))

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


def sembrar_multisede(clave: str) -> int | None:
    """Crea el salon Multisede con 3 sedes; None si ya existia (solo crea los
    usuarios que le falten)."""
    existente = _id_tienda(MULTI_NOMBRE)
    if existente:
        _crear_usuarios(existente, MULTI_USUARIOS, clave, _sedes(existente))
        return None

    (principal, direccion), *otras = MULTI_SEDES
    id_tienda = master_service.crear_negocio({
        "nombre_negocio": MULTI_NOMBRE, "tipo_negocio": "peluqueria", "telefono": "3000000010",
        "sede_nombre": principal, "admin_nombre": "Admin Multisede", "admin_cc": "1000000011",
        "admin_correo": f"multisede@{DOMINIO}", "admin_password": clave,
    })
    master_service.cambiar_plan(id_tienda, "multisede")
    for nombre, dir_sede in otras:
        sede_service.crear_sede(id_tienda, {"nombre": nombre, "direccion": dir_sede})
    sedes = _sedes(id_tienda)
    ids = _crear_usuarios(id_tienda, MULTI_USUARIOS, clave, sedes)
    sede_de = {u[0]: sedes[u[4]] for u in MULTI_USUARIOS}

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("UPDATE sedes SET direccion = %s WHERE id_sede = %s", (direccion, sedes[principal]))
        cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s", (f"multisede@{DOMINIO}",))
        id_admin = cur.fetchone()["id_usuario"]
        cur.execute("UPDATE usuarios SET atiende = 0 WHERE id_usuario = %s", (id_admin,))
        cur.execute("SELECT id_servicio, nombre, duracion_min, precio FROM servicios WHERE id_tienda = %s",
                    (id_tienda,))
        servicios = {f["nombre"]: f for f in cur.fetchall()}
        for codigo, emoji, nombre, costo, precio, stocks in MULTI_PRODUCTOS:
            cur.execute(
                "INSERT INTO productos (id_tienda, codigo_barras, emoji, nombre, costo, precio, stock_minimo) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (id_tienda, codigo, emoji, nombre, costo, precio, 3),
            )
            id_producto = cur.lastrowid
            for (sede, _), stock in zip(MULTI_SEDES, stocks):
                cur.execute("INSERT INTO stock_sedes (id_sede, id_producto, stock) VALUES (%s, %s, %s)",
                            (sedes[sede], id_producto, stock))
                if stock:
                    cur.execute(
                        "INSERT INTO movimientos_inventario (id_tienda, id_sede, id_producto, id_usuario, tipo, "
                        "cantidad, stock_anterior, stock_posterior, motivo) "
                        "VALUES (%s, %s, %s, %s, 'Entrada', %s, 0, %s, 'Carga inicial')",
                        (id_tienda, sedes[sede], id_producto, id_admin, stock, stock),
                    )
        hoy = hoy_local()
        for profesional, hora, cliente, servicio, telefono in MULTI_CITAS:
            inicio = datetime.combine(hoy, time.fromisoformat(hora))
            serv = servicios[servicio]
            cur.execute(
                "INSERT INTO citas (id_tienda, id_sede, id_servicio, id_profesional, cliente_nombre, "
                "cliente_telefono, inicio, fin, estado, precio, id_usuario_registra) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'reservada', %s, %s)",
                (id_tienda, sede_de[profesional], serv["id_servicio"], ids[profesional], cliente, telefono, inicio,
                 inicio + timedelta(minutes=serv["duracion_min"]), serv["precio"], id_admin),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return id_tienda


def _sedes(id_tienda: int) -> dict[str, int]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT nombre, id_sede FROM sedes WHERE id_tienda = %s AND estado = 'Activa'", (id_tienda,))
        return dict(cur.fetchall())
    finally:
        conn.close()


def en_produccion() -> bool:
    """En Railway manda el nombre del entorno (staging tambien usa
    FLASK_ENV=production); fuera de Railway, FLASK_ENV."""
    railway = os.getenv("RAILWAY_ENVIRONMENT_NAME")
    if railway:
        return railway.strip().lower() == "production"
    return str(os.getenv("FLASK_ENV") or "").strip().lower() == "production"


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea los negocios demo de Turnio.")
    parser.add_argument("--en-produccion", action="store_true",
                        help="correr aunque el entorno sea produccion (la contrasena demo es conocida)")
    args = parser.parse_args()
    if en_produccion() and not args.en_produccion:
        print("Este entorno es produccion: las cuentas demo tienen una contrasena conocida.")
        print("Correlo en staging. Si de verdad lo quieres aqui, agrega --en-produccion.")
        return 2
    clave = os.environ.get("DEMO_CLAVE") or getpass.getpass("Contrasena para los usuarios demo: ")
    error = first_password_policy_error(clave)
    if error:
        print(error)
        return 2

    app = create_app()
    with app.app_context():
        for nombre, sembrador in ((NOMBRE, sembrar), (MULTI_NOMBRE, sembrar_multisede)):
            print(f'{"Creado" if sembrador(clave) else "Ya existía (solo se completaron usuarios)"}: "{nombre}"')
    correos = ["admin", "admin2"] + [u[1] for u in USUARIOS[1:]] + ["multisede"] + [u[1] for u in MULTI_USUARIOS]
    print("Usuarios: " + ", ".join(f"{c}@{DOMINIO}" for c in correos))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
