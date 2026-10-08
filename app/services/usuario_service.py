"""Equipo de un negocio (tomado de jemPOS Chef): el Admin crea, edita y desactiva usuarios.

Invitaciones (T3): si el Admin no pone contrasena, el usuario queda con una
clave aleatoria e `invitacion_pendiente = 1`, y el Admin recibe un enlace para
mandarle por WhatsApp (y por correo si hay SMTP). Con el enlace la persona
elige su contrasena (aceptar_invitacion).

Soft delete: estado_activo = 0 y el correo y la cedula quedan liberados con el
prefijo deleted_<ts>_ (LIBERAR_USUARIO_SQL), asi se pueden volver a usar.
"""
from __future__ import annotations

import hmac
import secrets

from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash

from app.services import plan_service
from app.services.auth_service import (
    LIBERAR_USUARIO_SQL,
    first_password_policy_error,
    huella_clave,
    is_valid_email,
    liberar_datos_inactivos,
)
from app.services.sede_service import sede_de_tienda
from app.utils.helpers import normalize_phone, only_digits
from app.utils.validation import sanitize_text
from database import get_db

# Roles que un Admin puede dar. Master solo existe fuera de los negocios.
# Profesional: quien atiende (agenda propia, comisiones). Recepcion: agenda y
# caja de todos, sin configurar el negocio.
ROLES_NEGOCIO = ("Admin", "Recepcion", "Profesional")


class UsuarioError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _parse_cc(raw) -> str:
    cc = only_digits(raw)
    if not cc:
        raise ValueError("La cedula es requerida.")
    if not 5 <= len(cc) <= 15:
        raise ValueError("La cedula debe tener entre 5 y 15 digitos.")
    return cc


def _parse_rol(raw) -> str:
    rol = str(raw or "").strip().capitalize()
    if rol not in ROLES_NEGOCIO:
        raise ValueError("Rol invalido.")
    return rol


def _parse_sede(cur, id_tienda: int, rol: str, raw) -> int | None:
    """Admin: NULL = todas las sedes. Los demas roles siempre tienen una; si
    el negocio tiene una sola sede se usa esa."""
    if raw not in (None, ""):
        return sede_de_tienda(cur, id_tienda, raw)
    if rol == "Admin":
        return None
    cur.execute(
        "SELECT id_sede FROM sedes WHERE id_tienda = %s AND estado = 'Activa'",
        (id_tienda,),
    )
    sedes = cur.fetchall()
    if len(sedes) != 1:
        raise ValueError("Elige la sede donde trabaja.")
    return sedes[0]["id_sede"]


def listar_usuarios(id_tienda: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.id_usuario, u.nombre_completo, u.correo, u.cc, u.rol, u.id_sede, u.invitacion_pendiente, "
            "s.nombre AS sede "
            "FROM usuarios u LEFT JOIN sedes s ON s.id_sede = u.id_sede "
            "WHERE u.id_tienda = %s AND u.estado_activo = 1 AND u.rol <> 'Master' "
            "ORDER BY FIELD(u.rol, 'Admin', 'Recepcion', 'Profesional'), u.nombre_completo",
            (id_tienda,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def validar_clave_nueva(password, confirm) -> str:
    password = str(password or "")
    if len(password) > 128:
        raise ValueError("La contrasena supera el maximo permitido.")
    if password != str(confirm or ""):
        raise ValueError("Las contrasenas no coinciden.")
    pwd_error = first_password_policy_error(password)
    if pwd_error:
        raise ValueError(pwd_error)
    return password


def crear_usuario(id_tienda: int, data: dict) -> int:
    """Lanza ValueError, LimitePlanError o UsuarioError. Sin contrasena, el
    usuario queda invitado (ver datos_invitacion)."""
    nombre = sanitize_text(data.get("nombre"), "El nombre completo", max_len=150)
    cc = _parse_cc(data.get("cc"))
    rol = _parse_rol(data.get("rol"))
    correo = str(data.get("correo", "")).strip().lower()
    if not correo or len(correo) > 150 or not is_valid_email(correo):
        raise ValueError("El correo no es valido.")
    telefono = normalize_phone(data.get("telefono"), max_len=20)
    invitar = not data.get("password") and not data.get("confirm_password")
    if invitar:
        # Nadie conoce esta clave: hasta aceptar la invitacion no se puede entrar.
        password = secrets.token_urlsafe(32)
    else:
        password = validar_clave_nueva(data.get("password"), data.get("confirm_password"))

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        liberar_datos_inactivos(cur, correo, cc)
        cur.execute("SELECT 1 FROM usuarios WHERE correo = %s OR cc = %s LIMIT 1", (correo, cc))
        if cur.fetchone():
            raise UsuarioError("Ya existe un usuario con ese correo o cedula.", 409)
        id_sede = _parse_sede(cur, id_tienda, rol, data.get("id_sede"))
        plan_service.verificar_limite_rol(cur, id_tienda, rol)
        cur.execute(
            "INSERT INTO usuarios (id_tienda, id_sede, nombre_completo, correo, clave_hash, rol, cc, telefono, "
            "invitacion_pendiente) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (id_tienda, id_sede, nombre, correo, generate_password_hash(password), rol, cc, telefono, int(invitar)),
        )
        id_usuario = cur.lastrowid
        conn.commit()
        return id_usuario
    except IntegrityError as exc:
        # Carrera entre el SELECT y el INSERT: uq_usuarios_correo / uq_usuarios_cc.
        conn.rollback()
        raise UsuarioError("Ya existe un usuario con ese correo o cedula.", 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _usuario_de_tienda(cur, id_tienda: int, id_usuario: int) -> dict:
    cur.execute(
        "SELECT id_usuario, rol FROM usuarios "
        "WHERE id_usuario = %s AND id_tienda = %s AND estado_activo = 1 AND rol <> 'Master' FOR UPDATE",
        (id_usuario, id_tienda),
    )
    usuario = cur.fetchone()
    if not usuario:
        raise UsuarioError("Usuario no encontrado.", 404)
    return usuario


def _es_ultimo_admin(cur, id_tienda: int, id_usuario: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) AS n FROM usuarios "
        "WHERE id_tienda = %s AND rol = 'Admin' AND estado_activo = 1 AND id_usuario <> %s",
        (id_tienda, id_usuario),
    )
    return cur.fetchone()["n"] == 0


def actualizar_usuario(id_tienda: int, id_actor: int, id_usuario: int, data: dict) -> None:
    nombre = sanitize_text(data.get("nombre"), "El nombre completo", max_len=150)
    rol = _parse_rol(data.get("rol"))
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_de_tienda(cur, id_tienda, id_usuario)
        if usuario["rol"] == "Admin" and rol != "Admin":
            if id_usuario == id_actor:
                raise UsuarioError("No puedes quitarte el rol de Admin a ti mismo.")
            if _es_ultimo_admin(cur, id_tienda, id_usuario):
                raise UsuarioError("El negocio debe tener al menos un Admin.")
        if rol != usuario["rol"]:
            plan_service.verificar_limite_rol(cur, id_tienda, rol)
        id_sede = _parse_sede(cur, id_tienda, rol, data.get("id_sede"))
        cur.execute(
            "UPDATE usuarios SET nombre_completo = %s, rol = %s, id_sede = %s WHERE id_usuario = %s",
            (nombre, rol, id_sede, id_usuario),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desactivar_usuario(id_tienda: int, id_actor: int, id_usuario: int) -> None:
    if id_usuario == id_actor:
        raise UsuarioError("No puedes desactivar tu propia cuenta.")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_de_tienda(cur, id_tienda, id_usuario)
        if usuario["rol"] == "Admin" and _es_ultimo_admin(cur, id_tienda, id_usuario):
            raise UsuarioError("El negocio debe tener al menos un Admin.")
        cur.execute("UPDATE usuarios SET " + LIBERAR_USUARIO_SQL + " WHERE id_usuario = %s", (id_usuario,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def datos_invitacion(id_tienda: int, id_usuario: int) -> dict:
    """Lo necesario para armar el enlace de invitacion de un usuario del
    negocio que todavia no la acepta. Si ya entro, el Admin no puede generarle
    un enlace (seria una forma de tomar su cuenta): que use "Olvide mi
    contrasena"."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.nombre_completo, u.correo, u.clave_hash, u.telefono, u.invitacion_pendiente, "
            "t.nombre_negocio FROM usuarios u JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.id_usuario = %s AND u.id_tienda = %s AND u.estado_activo = 1 AND u.rol <> 'Master'",
            (id_usuario, id_tienda),
        )
        usuario = cur.fetchone()
    finally:
        conn.close()
    if not usuario:
        raise UsuarioError("Usuario no encontrado.", 404)
    if not usuario["invitacion_pendiente"]:
        raise UsuarioError("Esta persona ya acepto la invitacion. Si olvido la clave, que use \"Olvide mi contrasena\".")
    return usuario


def invitacion_vigente(correo: str, huella: str) -> dict | None:
    """El usuario del enlace si la invitacion sigue pendiente y la huella
    coincide (el enlace sirve una vez: al elegir clave la huella cambia)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.id_usuario, u.id_tienda, u.id_sede, u.nombre_completo, u.correo, u.clave_hash, u.rol, "
            "u.estado_activo, t.nombre_negocio FROM usuarios u JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.correo = %s AND u.invitacion_pendiente = 1 AND u.estado_activo = 1 "
            "AND t.estado <> 'Eliminado' LIMIT 1",
            (correo,),
        )
        usuario = cur.fetchone()
    finally:
        conn.close()
    if not usuario or not hmac.compare_digest(huella, huella_clave(usuario["clave_hash"])):
        return None
    return usuario


def aceptar_invitacion(usuario: dict, password, confirm) -> None:
    password = validar_clave_nueva(password, confirm)
    conn = get_db()
    try:
        cur = conn.cursor()
        # La condicion sobre clave_hash evita que dos envios del mismo enlace
        # ganen los dos.
        cur.execute(
            "UPDATE usuarios SET clave_hash = %s, invitacion_pendiente = 0 "
            "WHERE id_usuario = %s AND invitacion_pendiente = 1 AND clave_hash = %s",
            (generate_password_hash(password), usuario["id_usuario"], usuario["clave_hash"]),
        )
        if cur.rowcount != 1:
            raise UsuarioError("Enlace invalido o expirado.", 410)
        conn.commit()
    finally:
        conn.close()
