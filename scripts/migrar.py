"""Aplica en orden las migraciones de migrations/ que falten en la base.

Cada archivo aplicado queda anotado en la tabla `schema_migraciones` con su
huella (sha256): la siguiente corrida lo salta. Si un archivo ya aplicado
cambio despues, se detiene sin tocar nada: las migraciones aplicadas no se
editan, se escribe una nueva.

    python scripts/migrar.py            # aplica las pendientes
    python scripts/migrar.py --estado   # lista aplicadas y pendientes

Las sentencias se ejecutan con el mismo lector de run_migration.py (entiende
DELIMITER y trata como no-op los "ya existe"), asi que una base creada antes
de este registro se puede poner al dia sin errores. Un GET_LOCK evita que dos
despliegues migren a la vez. Credenciales: variables DB_* del entorno o .env.
"""
from __future__ import annotations

import glob
import hashlib
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from scripts.run_migration import _sentencias, _ya_aplicada  # noqa: E402

CARPETA = os.path.join(RAIZ, "migrations")
_LOCK = "turnio_migraciones"

_TABLA = (
    "CREATE TABLE IF NOT EXISTS `schema_migraciones` ("
    "`archivo` varchar(191) NOT NULL, "
    "`huella` char(64) NOT NULL, "
    "`aplicada_en` timestamp NOT NULL DEFAULT current_timestamp(), "
    "PRIMARY KEY (`archivo`)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
)


class MigracionError(Exception):
    pass


def archivos(carpeta: str = CARPETA) -> list[str]:
    """Migraciones en orden. El nombre empieza por la fecha: el orden
    alfabetico es el cronologico."""
    return sorted(glob.glob(os.path.join(carpeta, "*.sql")))


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _ejecutar(cur, sql: str, nombre: str) -> None:
    for sentencia in _sentencias(sql):
        try:
            cur.execute(sentencia)
            if cur.with_rows:
                cur.fetchall()
        except mysql.connector.Error as exc:
            if _ya_aplicada(exc):
                continue
            raise MigracionError(f"{nombre}: ERROR {exc.errno} {exc.msg}\n  en: {sentencia[:160]}") from exc


def migrar(conn, carpeta: str = CARPETA, salida=print) -> list[str]:
    """Aplica las pendientes sobre `conn` (autocommit) y devuelve sus nombres."""
    cur = conn.cursor()
    cur.execute("SELECT GET_LOCK(%s, 120)", (_LOCK,))
    if cur.fetchone()[0] != 1:
        raise MigracionError("Otra migracion esta corriendo. Intenta de nuevo en un momento.")
    try:
        cur.execute(_TABLA)
        cur.execute("SELECT archivo, huella FROM schema_migraciones")
        hechas = dict(cur.fetchall())
        pendientes = []
        for ruta in archivos(carpeta):
            nombre = os.path.basename(ruta)
            with open(ruta, encoding="utf-8") as fh:
                sql = fh.read()
            if nombre in hechas:
                if hechas[nombre] != _huella(sql):
                    raise MigracionError(
                        f"{nombre} cambio despues de aplicarse. No se editan migraciones aplicadas: "
                        "escribe una nueva."
                    )
                continue
            pendientes.append((nombre, sql))

        for nombre, sql in pendientes:
            _ejecutar(cur, sql, nombre)
            cur.execute(
                "INSERT INTO schema_migraciones (archivo, huella) VALUES (%s, %s)", (nombre, _huella(sql))
            )
            salida(f"OK {nombre}")
        return [n for n, _ in pendientes]
    finally:
        cur.execute("SELECT RELEASE_LOCK(%s)", (_LOCK,))
        cur.fetchall()
        cur.close()


def conectar():
    load_dotenv(os.path.join(RAIZ, ".env"))
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT") or 3306),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD") or "",
        database=os.getenv("DB_NAME"),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=True,
    )


def main(argv: list[str]) -> int:
    conn = conectar()
    try:
        if "--estado" in argv:
            cur = conn.cursor()
            cur.execute(_TABLA)
            cur.execute("SELECT archivo FROM schema_migraciones")
            hechas = {fila[0] for fila in cur.fetchall()}
            for ruta in archivos():
                nombre = os.path.basename(ruta)
                print(("aplicada  " if nombre in hechas else "PENDIENTE ") + nombre)
            return 0
        aplicadas = migrar(conn)
    except MigracionError as exc:
        print(exc)
        return 1
    finally:
        conn.close()
    print(f"{len(aplicadas)} migraciones aplicadas." if aplicadas else "La base ya esta al dia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
