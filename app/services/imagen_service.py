"""Logo del negocio y fotos de los profesionales, guardados en la base.

Solo PNG, JPEG y WebP, reconocidos por sus primeros bytes (no por el nombre
ni por lo que diga el navegador): asi nunca se sirve un SVG o un HTML
disfrazado de imagen. Cada cambio crea una imagen nueva y borra la anterior,
asi /img/<id> se puede cachear para siempre.
"""
from __future__ import annotations

from database import get_db

MAX_BYTES = 2 * 1024 * 1024


def tipo_de(datos: bytes) -> str | None:
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(datos) > 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return None


def validar(datos: bytes | None) -> str:
    """El tipo MIME de la imagen, o ValueError."""
    if not datos:
        raise ValueError("Elige una imagen.")
    if len(datos) > MAX_BYTES:
        raise ValueError("La imagen supera 2 MB.")
    tipo = tipo_de(datos)
    if not tipo:
        raise ValueError("La imagen debe ser PNG, JPG o WebP.")
    return tipo


def guardar(cur, id_tienda: int, datos: bytes, tipo: str) -> int:
    cur.execute(
        "INSERT INTO imagenes (id_tienda, tipo, datos) VALUES (%s, %s, %s)",
        (id_tienda, tipo, datos),
    )
    return cur.lastrowid


def borrar(cur, id_tienda: int, id_imagen: int | None) -> None:
    if id_imagen:
        cur.execute("DELETE FROM imagenes WHERE id_imagen = %s AND id_tienda = %s", (id_imagen, id_tienda))


def leer(id_imagen: int) -> dict | None:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT tipo, datos FROM imagenes WHERE id_imagen = %s", (id_imagen,))
        return cur.fetchone()
    finally:
        conn.close()


def url(id_imagen: int | None) -> str | None:
    return f"/img/{id_imagen}" if id_imagen else None
