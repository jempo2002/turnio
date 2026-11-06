"""Panel Master: alta de negocios, plan, suscripcion y baja.

Tomado de jemPOS Chef. El negocio lo crea el Master desde su panel o el
dueno desde el registro abierto (/registro, T3); los dos usan crear_negocio y
arrancan con la prueba gratis (DIAS_PRUEBA dias del plan PLAN_PRUEBA, hoy 14
dias del Pro). Al registrar el primer pago el Master le pone el plan que
eligio.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta

from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash

from app.services import plan_service, usuario_service, vertical_service
from app.services.auth_service import (
    LIBERAR_USUARIO_SQL,
    first_password_policy_error,
    is_valid_email,
    liberar_datos_inactivos,
)
from app.services.sede_service import sembrar_horario
from app.services.vertical_service import TIPOS_NEGOCIO
from app.utils.helpers import ahora_local, hoy_local, normalize_phone
from app.utils.validation import sanitize_optional_text, sanitize_text
from database import get_db

PERIODOS = (1, 3, 6, 12)
_SLUG_MAX = 60


# Situacion de cada negocio en el panel, en el orden de los filtros.
SITUACIONES = {
    "prueba": "En prueba",
    "al_dia": "Al día",
    "por_vencer": "Vence pronto",
    "vencido": "Vencido",
    "suspendido": "Suspendido",
}
DIAS_POR_VENCER = 7
_MONTO_MAX = 99_999_999


class MasterError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def sumar_meses(base: date, meses: int) -> date:
    m = base.month - 1 + meses
    anio = base.year + m // 12
    mes = m % 12 + 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def slug_base(nombre: str) -> str:
    """'Barbería El Cuartel' -> 'barberia-el-cuartel'. Va en la URL publica
    de reservas, asi que solo a-z, 0-9 y guiones."""
    texto = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return texto[:_SLUG_MAX].strip("-") or "negocio"


def _slug_libre(cur, nombre: str) -> str:
    """Primer slug libre: barberia-el-cuartel, barberia-el-cuartel-2, ...
    El UNIQUE de la base es el respaldo si dos altas chocan a la vez."""
    base = slug_base(nombre)
    cur.execute(
        "SELECT slug FROM tiendas WHERE slug = %s OR slug LIKE %s",
        (base, base[: _SLUG_MAX - 4] + "-%"),
    )
    usados = {fila["slug"] for fila in cur.fetchall()}
    if base not in usados:
        return base
    n = 2
    while f"{base[: _SLUG_MAX - 4]}-{n}" in usados:
        n += 1
    return f"{base[: _SLUG_MAX - 4]}-{n}"


def _parse_tipo(raw) -> str:
    tipo = str(raw or "otro").strip()
    if tipo not in TIPOS_NEGOCIO:
        raise ValueError("Elige el tipo de negocio de la lista.")
    return tipo


def _parse_plan(raw) -> str:
    plan = str(raw or "").strip()
    if plan not in plan_service.PLANES:
        raise ValueError("Ese plan no existe. Elige uno de la lista.")
    return plan


def listar_negocios(id_tienda: int | None = None) -> list[dict]:
    """Negocios no eliminados (o solo `id_tienda`) con sus conteos."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT t.id_tienda, t.nombre_negocio, t.slug, t.tipo_negocio, t.nit, t.telefono, t.plan_id, "
            "t.estado, t.fecha_creacion, t.fecha_fin_suscripcion, t.trial_ends_at, "
            "(SELECT COUNT(*) FROM sedes s WHERE s.id_tienda = t.id_tienda AND s.estado = 'Activa') AS sedes, "
            "(SELECT COUNT(*) FROM usuarios u WHERE u.id_tienda = t.id_tienda AND u.estado_activo = 1) AS usuarios, "
            # Montajes de sedes activas aun no cobrados (pago unico por sede).
            "(SELECT COALESCE(SUM(s.costo_montaje), 0) FROM sedes s WHERE s.id_tienda = t.id_tienda "
            "AND s.estado = 'Activa' AND s.montaje_pagado = 0) AS montaje_pendiente "
            "FROM tiendas t WHERE t.estado <> 'Eliminado' AND (%s IS NULL OR t.id_tienda = %s) "
            "ORDER BY t.nombre_negocio",
            (id_tienda, id_tienda),
        )
        filas = cur.fetchall()
    finally:
        conn.close()
    hoy = hoy_local()
    for f in filas:
        _completar(f, hoy)
    return filas


def _completar(f: dict, hoy: date) -> None:
    """Campos calculados de un negocio: plan, mensualidad, vencimiento y en
    que situacion esta (ver SITUACIONES)."""
    f["plan_nombre"] = plan_service.plan_de(f["plan_id"])["nombre"]
    f["mensualidad"] = plan_service.mensualidad(f["plan_id"], f["sedes"])
    f["montaje_pendiente"] = int(f["montaje_pendiente"])
    f["en_prueba"] = f["fecha_fin_suscripcion"] is None and f["trial_ends_at"] is not None
    f["vence"] = f["fecha_fin_suscripcion"] or f["trial_ends_at"]
    f["dias"] = (f["vence"] - hoy).days if f["vence"] else None
    f["situacion"] = _situacion(f)


def crear_negocio(data: dict) -> int:
    """Tienda + sede principal + Admin dueno, en una sola transaccion."""
    nombre = sanitize_text(data.get("nombre_negocio"), "El nombre del negocio", max_len=150)
    tipo = _parse_tipo(data.get("tipo_negocio"))
    nit = sanitize_optional_text(data.get("nit"), "NIT", max_len=30)
    telefono = normalize_phone(data.get("telefono"), max_len=20)
    plan_id = plan_service.PLAN_PRUEBA
    sede_nombre = sanitize_text(data.get("sede_nombre") or "Principal", "El nombre de la sede", max_len=120)
    sede_direccion = sanitize_optional_text(data.get("sede_direccion"), "La dirección", max_len=200)
    admin_nombre = sanitize_text(data.get("admin_nombre"), "El nombre del administrador", max_len=150)
    admin_cc = usuario_service._parse_cc(data.get("admin_cc"))
    admin_correo = str(data.get("admin_correo", "")).strip().lower()
    password = str(data.get("admin_password", ""))
    if not admin_correo or len(admin_correo) > 150 or not is_valid_email(admin_correo):
        raise ValueError("Revisa el correo del administrador: debe verse así, nombre@gmail.com.")
    if len(password) > 128:
        raise ValueError("La contraseña es muy larga: usa máximo 128 caracteres.")
    pwd_error = first_password_policy_error(password)
    if pwd_error:
        raise ValueError(pwd_error)

    fin_prueba = hoy_local() + timedelta(days=plan_service.DIAS_PRUEBA)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        liberar_datos_inactivos(cur, admin_correo, admin_cc)
        cur.execute(
            "SELECT 1 FROM usuarios WHERE correo = %s OR cc = %s LIMIT 1", (admin_correo, admin_cc)
        )
        if cur.fetchone():
            raise MasterError("Ya existe un usuario con ese correo o cedula.", 409)
        cur.execute(
            "INSERT INTO tiendas (nombre_negocio, slug, tipo_negocio, nit, telefono, plan_id, trial_ends_at, "
            "estado_suscripcion) VALUES (%s, %s, %s, %s, %s, %s, %s, 'activa')",
            # nombre ya viene escapado para HTML; el slug se saca del texto original.
            (nombre, _slug_libre(cur, data.get("nombre_negocio")), tipo, nit or admin_cc, telefono, plan_id, fin_prueba),
        )
        id_tienda = cur.lastrowid
        cur.execute(
            "INSERT INTO sedes (id_tienda, nombre, direccion, telefono, es_principal) VALUES (%s, %s, %s, %s, 1)",
            (id_tienda, sede_nombre, sede_direccion, telefono),
        )
        # Horario y servicios del tipo de negocio (T9): el link de reservas
        # sirve desde el primer dia y el dueno solo ajusta precios.
        sembrar_horario(cur, cur.lastrowid, vertical_service.horario(tipo))
        vertical_service.sembrar_servicios(cur, id_tienda, tipo)
        cur.execute(
            # Admin sin sede fija (NULL): ve todas las sedes del negocio. En
            # un negocio que empieza el dueno casi siempre atiende (atiende =
            # 1, tiene agenda); si no, lo apaga en Ajustes.
            "INSERT INTO usuarios (id_tienda, id_sede, nombre_completo, correo, clave_hash, rol, cc, atiende) "
            "VALUES (%s, NULL, %s, %s, %s, 'Admin', %s, 1)",
            (id_tienda, admin_nombre, admin_correo, generate_password_hash(password), admin_cc),
        )
        conn.commit()
        return id_tienda
    except IntegrityError as exc:
        conn.rollback()
        raise MasterError("El NIT, el correo o la cedula ya estan registrados.", 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_plan(id_tienda: int, raw_plan) -> str:
    plan_id = _parse_plan(raw_plan)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT 1 FROM tiendas WHERE id_tienda = %s AND estado <> 'Eliminado' LIMIT 1", (id_tienda,)
        )
        if not cur.fetchone():
            raise MasterError("Negocio no encontrado.", 404)
        plan_service.verificar_cambio_plan(cur, id_tienda, plan_id)
        cur.execute("UPDATE tiendas SET plan_id = %s WHERE id_tienda = %s", (plan_id, id_tienda))
        conn.commit()
        return plan_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def marcar_montajes_pagados(id_tienda: int, id_master: int | None = None) -> int:
    """Marca cobrados los montajes pendientes de las sedes activas. Devuelve
    cuanto se cobro."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COALESCE(SUM(costo_montaje), 0) AS total FROM sedes "
            "WHERE id_tienda = %s AND estado = 'Activa' AND montaje_pagado = 0 AND costo_montaje > 0 FOR UPDATE",
            (id_tienda,),
        )
        total = int(cur.fetchone()["total"])
        if not total:
            raise MasterError("No hay montajes pendientes.", 404)
        cur.execute(
            "UPDATE sedes SET montaje_pagado = 1, fecha_pago_montaje = %s "
            "WHERE id_tienda = %s AND estado = 'Activa' AND montaje_pagado = 0 AND costo_montaje > 0",
            (ahora_local(), id_tienda),
        )
        _registrar_pago(cur, id_tienda, "Montaje", total, id_master)
        conn.commit()
        return total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def renovar(id_tienda: int, raw_meses, raw_monto=None, raw_nota=None, id_master: int | None = None) -> date:
    """Registra un pago de `meses`. Corre desde hoy o desde el vencimiento
    vigente, lo que sea mas tarde: pagar antes de tiempo no pierde dias.

    Queda en pagos_master con el monto cobrado: por defecto la mensualidad
    del plan (con sus sedes extra) por los meses; el Master puede escribir
    otro (un descuento, por ejemplo)."""
    try:
        meses = int(raw_meses)
    except (TypeError, ValueError) as exc:
        raise ValueError("Elige un periodo de la lista.") from exc
    if meses not in PERIODOS:
        raise ValueError("Periodo de suscripcion no permitido.")
    monto_manual = _parse_monto(raw_monto)
    nota = sanitize_optional_text(raw_nota, "La nota", max_len=200)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT plan_id, COALESCE(fecha_fin_suscripcion, trial_ends_at) AS vence FROM tiendas "
            "WHERE id_tienda = %s AND estado <> 'Eliminado' FOR UPDATE",
            (id_tienda,),
        )
        tienda = cur.fetchone()
        if not tienda:
            raise MasterError("Negocio no encontrado.", 404)
        hoy = hoy_local()
        desde = max(hoy, tienda["vence"] or hoy)
        fin = sumar_meses(desde, meses)
        cur.execute(
            "UPDATE tiendas SET fecha_inicio_suscripcion = %s, fecha_fin_suscripcion = %s, "
            "estado_suscripcion = 'activa' WHERE id_tienda = %s",
            (hoy, fin, id_tienda),
        )
        if monto_manual is None:
            monto = plan_service.mensualidad(tienda["plan_id"], plan_service._contar_sedes(cur, id_tienda)) * meses
        else:
            monto = monto_manual
        _registrar_pago(cur, id_tienda, "Mensualidad", monto, id_master, plan_id=tienda["plan_id"],
                        meses=meses, vence_hasta=fin, nota=nota)
        conn.commit()
        return fin
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def eliminar_negocio(id_tienda: int) -> None:
    """Soft delete: un DELETE real borraria el historial contable. Se liberan
    el NIT y los correos para poder registrarlos de nuevo."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tiendas SET estado = 'Eliminado', estado_suscripcion = 'suspendida', "
            "fecha_fin_suscripcion = CURDATE(), nit = CONCAT('deleted_', UNIX_TIMESTAMP(), '_', nit) "
            "WHERE id_tienda = %s AND estado <> 'Eliminado'",
            (id_tienda,),
        )
        if cur.rowcount == 0:
            raise MasterError("Negocio no encontrado.", 404)
        cur.execute(
            "UPDATE sedes SET estado = 'Eliminada', fecha_eliminacion = %s "
            "WHERE id_tienda = %s AND estado = 'Activa'",
            (ahora_local(), id_tienda),
        )
        cur.execute(
            "UPDATE usuarios SET " + LIBERAR_USUARIO_SQL +
            " WHERE id_tienda = %s AND rol <> 'Master' AND estado_activo = 1",
            (id_tienda,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Panel Master ampliado (2026-11-06): resumen, ficha del negocio, ──
# ── suspender, historial de cobros y usuarios de toda la plataforma. ──

def _situacion(f: dict) -> str:
    if f.get("estado") == "Suspendido":
        return "suspendido"
    if f["dias"] is not None and f["dias"] <= 0:
        return "vencido"
    if f["en_prueba"]:
        return "prueba"
    if f["dias"] is not None and f["dias"] <= DIAS_POR_VENCER:
        return "por_vencer"
    return "al_dia"


def filtrar(negocios: list[dict], situacion: str | None, q: str | None) -> list[dict]:
    """Filtro del listado: por situacion y por texto (nombre, enlace, NIT o
    telefono). Se hace en memoria: son decenas o cientos de negocios."""
    if situacion in SITUACIONES:
        negocios = [n for n in negocios if n["situacion"] == situacion]
    texto = str(q or "").strip().lower()[:100]
    if texto:
        negocios = [
            n for n in negocios
            if any(texto in str(n.get(c) or "").lower() for c in ("nombre_negocio", "slug", "nit", "telefono"))
        ]
    return negocios


def resumen(negocios: list[dict]) -> dict:
    """Cifras de arriba del panel. `negocios` es listar_negocios() completo."""
    conteo = {clave: 0 for clave in SITUACIONES}
    for n in negocios:
        conteo[n["situacion"]] += 1
    hoy = hoy_local()
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COALESCE(SUM(monto), 0) AS cobrado FROM pagos_master WHERE fecha >= %s",
            (hoy.replace(day=1),),
        )
        cobrado_mes = int(cur.fetchone()["cobrado"])
        cur.execute(
            "SELECT COUNT(*) AS n FROM usuarios u JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "WHERE u.estado_activo = 1 AND t.estado <> 'Eliminado'"
        )
        usuarios = int(cur.fetchone()["n"])
    finally:
        conn.close()
    pagan = [n for n in negocios if n["situacion"] in ("al_dia", "por_vencer")]
    return {
        "negocios": len(negocios),
        "conteo": conteo,
        "mrr": sum(n["mensualidad"] for n in pagan),
        "montajes": sum(n["montaje_pendiente"] for n in negocios),
        "cobrado_mes": cobrado_mes,
        "usuarios": usuarios,
    }


def negocio(id_tienda: int) -> dict:
    """Ficha completa de un negocio para el Master: datos, sedes, usuarios y
    cobros."""
    filas = listar_negocios(id_tienda)
    if not filas:
        raise MasterError("Negocio no encontrado.", 404)
    ficha = filas[0]
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_sede, nombre, direccion, telefono, es_principal, costo_montaje, montaje_pagado "
            "FROM sedes WHERE id_tienda = %s AND estado = 'Activa' ORDER BY es_principal DESC, nombre",
            (id_tienda,),
        )
        sedes = cur.fetchall()
        cur.execute(
            "SELECT u.id_usuario, u.nombre_completo, u.correo, u.cc, u.telefono, u.rol, u.id_sede, "
            "u.invitacion_pendiente, s.nombre AS sede "
            "FROM usuarios u LEFT JOIN sedes s ON s.id_sede = u.id_sede "
            "WHERE u.id_tienda = %s AND u.estado_activo = 1 AND u.rol <> 'Master' "
            "ORDER BY FIELD(u.rol, 'Admin', 'Recepcion', 'Profesional'), u.nombre_completo",
            (id_tienda,),
        )
        usuarios = cur.fetchall()
        cur.execute(
            "SELECT p.fecha, p.concepto, p.plan_id, p.meses, p.monto, p.vence_hasta, p.nota, "
            "u.nombre_completo AS registro "
            "FROM pagos_master p LEFT JOIN usuarios u ON u.id_usuario = p.id_usuario "
            "WHERE p.id_tienda = %s ORDER BY p.fecha DESC, p.id_pago DESC LIMIT 50",
            (id_tienda,),
        )
        pagos = cur.fetchall()
    finally:
        conn.close()
    plan = plan_service.plan_de(ficha["plan_id"])
    incluidas = plan["sedes_incluidas"]
    for i, sede in enumerate(sedes):
        # Como mensualidad(): las primeras son las incluidas, y solo el plan
        # con sedes extra las cobra.
        sede["extra"] = bool(plan["sede_extra"]) and i + 1 > incluidas
        sede["precio_mes"] = plan_service.precio_sede_extra(i + 1 - incluidas) if sede["extra"] else 0
    for p in pagos:
        p["plan_nombre"] = plan_service.plan_de(p["plan_id"])["nombre"] if p["plan_id"] else ""
    ficha.update(
        sedes=sedes,
        usuarios=usuarios,
        pagos=pagos,
        admins=sum(1 for u in usuarios if u["rol"] == "Admin"),
        tope_admins=plan_service.tope(ficha["plan_id"], "administradores", len(sedes)),
    )
    return ficha


def ultimos_pagos(limite: int = 20) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT p.fecha, p.concepto, p.meses, p.monto, p.id_tienda, t.nombre_negocio "
            "FROM pagos_master p JOIN tiendas t ON t.id_tienda = p.id_tienda "
            "ORDER BY p.fecha DESC, p.id_pago DESC LIMIT %s",
            (limite,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _parse_monto(raw) -> int | None:
    """Monto en pesos enteros; vacio = el que calcula el plan."""
    texto = str(raw if raw is not None else "").strip().replace(".", "").replace("$", "").replace(" ", "")
    if not texto:
        return None
    if not texto.isdigit():
        raise ValueError("Escribe el monto en pesos, solo números. Ejemplo: 89000.")
    monto = int(texto)
    if monto > _MONTO_MAX:
        raise ValueError("Ese monto es muy alto. Revísalo.")
    return monto


def _registrar_pago(cur, id_tienda: int, concepto: str, monto: int, id_master: int | None, *,
                    plan_id=None, meses=None, vence_hasta=None, nota=None) -> None:
    cur.execute(
        "INSERT INTO pagos_master (id_tienda, concepto, plan_id, meses, monto, vence_hasta, nota, id_usuario) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (id_tienda, concepto, plan_id, meses, monto, vence_hasta, nota, id_master),
    )


def editar_negocio(id_tienda: int, data: dict) -> None:
    """Nombre, tipo, NIT, telefono y enlace de reservas (slug)."""
    nombre = sanitize_text(data.get("nombre_negocio"), "El nombre del negocio", max_len=150)
    tipo = _parse_tipo(data.get("tipo_negocio"))
    nit = sanitize_optional_text(data.get("nit"), "NIT", max_len=30)
    telefono = normalize_phone(data.get("telefono"), max_len=20)
    slug = str(data.get("slug") or "").strip().lower()
    if not slug or slug_base(slug) != slug or len(slug) < 3:
        raise ValueError("El enlace solo lleva letras minúsculas, números y guiones. Ejemplo: barberia-el-cuartel.")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT 1 FROM tiendas WHERE id_tienda = %s AND estado <> 'Eliminado' FOR UPDATE", (id_tienda,)
        )
        if not cur.fetchone():
            raise MasterError("Negocio no encontrado.", 404)
        cur.execute("SELECT 1 FROM tiendas WHERE slug = %s AND id_tienda <> %s LIMIT 1", (slug, id_tienda))
        if cur.fetchone():
            raise MasterError("Ese enlace ya lo usa otro negocio. Prueba con otro.", 409)
        cur.execute(
            "UPDATE tiendas SET nombre_negocio = %s, tipo_negocio = %s, nit = %s, telefono = %s, slug = %s "
            "WHERE id_tienda = %s",
            (nombre, tipo, nit, telefono, slug, id_tienda),
        )
        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        raise MasterError("Ese NIT o ese enlace ya los usa otro negocio.", 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_estado(id_tienda: int, suspender: bool) -> None:
    """Suspendido: nadie del negocio entra (login_required lo saca al
    instante) y su enlace de reservas deja de existir. Nada se borra; se
    reactiva igual."""
    nuevo, antes = ("Suspendido", "Activo") if suspender else ("Activo", "Suspendido")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tiendas SET estado = %s, estado_suscripcion = %s WHERE id_tienda = %s AND estado = %s",
            (nuevo, "suspendida" if suspender else "activa", id_tienda, antes),
        )
        if cur.rowcount == 0:
            raise MasterError("Ese negocio no existe o ya estaba " + ("suspendido." if suspender else "activo."), 404)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fijar_vencimiento(id_tienda: int, raw_fecha) -> date:
    """Corrige a mano la fecha de vencimiento (cortesia, error al registrar
    un pago). No registra cobro."""
    try:
        fecha = date.fromisoformat(str(raw_fecha or "").strip()[:10])
    except ValueError as exc:
        raise ValueError("Elige la fecha en el calendario.") from exc
    hoy = hoy_local()
    if not hoy - timedelta(days=366) <= fecha <= hoy + timedelta(days=3 * 366):
        raise ValueError("Esa fecha está muy lejos. Revísala.")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tiendas SET fecha_fin_suscripcion = %s, fecha_inicio_suscripcion = "
            "COALESCE(fecha_inicio_suscripcion, %s) WHERE id_tienda = %s AND estado <> 'Eliminado'",
            (fecha, hoy, id_tienda),
        )
        if cur.rowcount == 0:
            cur.execute("SELECT 1 FROM tiendas WHERE id_tienda = %s AND estado <> 'Eliminado'", (id_tienda,))
            if not cur.fetchone():
                raise MasterError("Negocio no encontrado.", 404)
        conn.commit()
        return fecha
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Usuarios de toda la plataforma ───────────────────────────────────

def buscar_usuarios(q: str | None, limite: int = 100) -> list[dict]:
    """Usuarios activos de negocios no eliminados y los Master. Busca por
    nombre, correo, cedula o negocio."""
    texto = str(q or "").strip()[:100]
    filtro, params = "", []
    if texto:
        filtro = ("AND (u.nombre_completo LIKE %s OR u.correo LIKE %s OR u.cc LIKE %s "
                  "OR t.nombre_negocio LIKE %s) ")
        params = [f"%{texto}%"] * 4
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.id_usuario, u.nombre_completo, u.correo, u.cc, u.rol, u.id_tienda, u.invitacion_pendiente, "
            "t.nombre_negocio, t.estado AS estado_tienda, s.nombre AS sede "
            "FROM usuarios u LEFT JOIN tiendas t ON t.id_tienda = u.id_tienda "
            "LEFT JOIN sedes s ON s.id_sede = u.id_sede "
            "WHERE u.estado_activo = 1 AND (u.rol = 'Master' OR t.estado <> 'Eliminado') " + filtro +
            "ORDER BY u.rol <> 'Master', t.nombre_negocio, FIELD(u.rol, 'Admin', 'Recepcion', 'Profesional'), "
            "u.nombre_completo LIMIT %s",
            (*params, limite),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _usuario_activo(cur, id_usuario: int) -> dict:
    cur.execute(
        "SELECT id_usuario, id_tienda, id_sede, rol, atiende, correo FROM usuarios "
        "WHERE id_usuario = %s AND estado_activo = 1 FOR UPDATE",
        (id_usuario,),
    )
    usuario = cur.fetchone()
    if not usuario:
        raise MasterError("Usuario no encontrado.", 404)
    return usuario


def _correo_libre(cur, correo: str, id_usuario: int) -> str:
    correo = str(correo or "").strip().lower()
    if not correo or len(correo) > 150 or not is_valid_email(correo):
        raise ValueError("Revisa el correo: debe verse así, nombre@gmail.com.")
    liberar_datos_inactivos(cur, correo)
    cur.execute("SELECT 1 FROM usuarios WHERE correo = %s AND id_usuario <> %s LIMIT 1", (correo, id_usuario))
    if cur.fetchone():
        raise MasterError("Ya existe otro usuario con ese correo.", 409)
    return correo


def editar_usuario(id_master: int, id_usuario: int, data: dict) -> None:
    """Nombre, correo, rol y sede de cualquier usuario. Las reglas del
    negocio siguen: al menos un Admin, y el tope de Admin y profesionales del
    plan (maximo 2 Admin). Un Master solo cambia nombre y correo: el rol
    Master se da y se quita con scripts/crear_master.py."""
    nombre = sanitize_text(data.get("nombre"), "El nombre completo", max_len=150)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_activo(cur, id_usuario)
        correo = _correo_libre(cur, data.get("correo"), id_usuario)
        if usuario["rol"] == "Master":
            cur.execute(
                "UPDATE usuarios SET nombre_completo = %s, correo = %s WHERE id_usuario = %s",
                (nombre, correo, id_usuario),
            )
        else:
            id_tienda = usuario["id_tienda"]
            # Sin la clave, el rol y la sede no cambian (la pantalla Usuarios
            # solo edita nombre y correo).
            rol = usuario_service._parse_rol(data["rol"]) if "rol" in data else usuario["rol"]
            if usuario["rol"] == "Admin" and rol != "Admin" and usuario_service._es_ultimo_admin(
                cur, id_tienda, id_usuario
            ):
                raise MasterError("El negocio debe tener al menos un Admin. Nombra otro antes de cambiar este.")
            if rol != usuario["rol"] and not (rol == "Profesional" and usuario["atiende"]):
                plan_service.verificar_limite_rol(cur, id_tienda, rol)
            if "id_sede" in data or rol != usuario["rol"]:
                id_sede = usuario_service._parse_sede(cur, id_tienda, rol, data.get("id_sede"))
            else:
                id_sede = usuario["id_sede"]
            cur.execute(
                "UPDATE usuarios SET nombre_completo = %s, correo = %s, rol = %s, id_sede = %s, "
                "atiende = IF(%s = 'Profesional', 1, atiende) WHERE id_usuario = %s AND id_tienda = %s",
                (nombre, correo, rol, id_sede, rol, id_usuario, id_tienda),
            )
        conn.commit()
    except IntegrityError as exc:
        conn.rollback()
        raise MasterError("Ya existe otro usuario con ese correo.", 409) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_clave(id_usuario: int, password, confirm) -> str:
    """Pone una contrasena nueva (el usuario la olvido y no tiene correo a
    mano). Cierra sus otras sesiones (cambia la huella) y anula una
    invitacion pendiente. Devuelve el hash nuevo."""
    password = usuario_service.validar_clave_nueva(password, confirm)
    nuevo_hash = generate_password_hash(password)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        _usuario_activo(cur, id_usuario)
        cur.execute(
            "UPDATE usuarios SET clave_hash = %s, invitacion_pendiente = 0 WHERE id_usuario = %s",
            (nuevo_hash, id_usuario),
        )
        conn.commit()
        return nuevo_hash
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def desactivar_usuario(id_master: int, id_usuario: int) -> None:
    if id_usuario == id_master:
        raise MasterError("No puedes desactivar tu propia cuenta.")
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_activo(cur, id_usuario)
        if usuario["rol"] == "Admin" and usuario_service._es_ultimo_admin(cur, usuario["id_tienda"], id_usuario):
            raise MasterError("Es el único Admin de su negocio. Nombra otro antes de desactivarlo.")
        cur.execute("UPDATE usuarios SET " + LIBERAR_USUARIO_SQL + " WHERE id_usuario = %s", (id_usuario,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def crear_usuario(id_tienda: int, data: dict) -> int:
    """Alta de un usuario en un negocio desde el panel Master, con las mismas
    reglas y topes que la pantalla Equipo del Admin. Aqui la contrasena es
    obligatoria: el Master se la pasa a la persona."""
    if not str(data.get("password") or ""):
        raise ValueError("Escribe una contraseña inicial y pásasela a la persona.")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM tiendas WHERE id_tienda = %s AND estado <> 'Eliminado'", (id_tienda,))
        if not cur.fetchone():
            raise MasterError("Negocio no encontrado.", 404)
    finally:
        conn.close()
    return usuario_service.crear_usuario(id_tienda, data)
