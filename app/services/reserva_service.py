"""Reservas publicas (T8): lo que ve y hace el cliente final en /r/<slug>,
sin cuenta.

Solo sale lo que el cliente necesita para reservar: nombre, logo y WhatsApp
del negocio, sedes con su direccion y horario, servicios con duracion y
precio, y quienes reciben reservas en linea (`reserva_online`).
Nunca correos, roles, pagos al profesional ni citas de otros clientes: de la
agenda solo salen horas libres.

Las reservas pasan por las mismas reglas de la agenda (T6): horario,
almuerzo, cruces con bloqueo de la sede y del profesional. Ademas:
  - no se reserva en una hora que ya paso ni a mas de MAX_DIAS_ADELANTE;
  - un mismo WhatsApp tiene como maximo MAX_PENDIENTES_POR_TELEFONO citas
    por venir en el negocio (frena a quien llena la agenda de reservas falsas);
  - un negocio suspendido no existe y uno con la suscripcion vencida no
    recibe reservas (su cuenta esta en solo lectura).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from app.services import agenda_service, imagen_service, local_service, profesional_service
from app.services.agenda_service import (
    _bloquear_sede,
    _cruce,
    _escribir,
    _profesional,
    _servicio,
    _validar_horario,
)
from app.services.errores import Conflicto, ErrorServicio, NoEncontrado
from app.utils.helpers import ahora_local, enlace_whatsapp, hora_12, hoy_local, only_digits
from app.utils.validation import parse_int, sanitize_text
from database import get_db

MAX_DIAS_ADELANTE = 30
MAX_PENDIENTES_POR_TELEFONO = 3
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NO_ENCONTRADO = "Negocio no encontrado."
SIN_RESERVAS = "Este negocio no está recibiendo reservas en línea por ahora. Escríbele por WhatsApp."
_NADIE_LIBRE = "Esa hora se acaba de ocupar. Elige otra."


# ── Negocio ─────────────────────────────────────────────────────────

def tienda(slug: str) -> dict:
    """El negocio activo de ese enlace. Suspendido o eliminado = no existe."""
    slug = str(slug or "").strip().lower()
    if not 3 <= len(slug) <= 60 or not _SLUG.match(slug):
        raise NoEncontrado(_NO_ENCONTRADO)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            # Sin pago registrado (fecha_fin NULL) manda el fin de la prueba,
            # igual que en login_required.
            "SELECT id_tienda, nombre_negocio, slug, tipo_negocio, telefono, id_logo, "
            "COALESCE(fecha_fin_suscripcion, trial_ends_at) AS vence "
            "FROM tiendas WHERE slug = %s AND estado = 'Activo'",
            (slug,),
        )
        fila = cur.fetchone()
    finally:
        conn.close()
    if not fila:
        raise NoEncontrado(_NO_ENCONTRADO)
    # Vencida = solo lectura (login_required): sin reservas nuevas.
    fila["recibe_reservas"] = fila["vence"] is None or fila["vence"] > hoy_local()
    return fila


def _sedes(id_tienda: int) -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id_sede, nombre, direccion, telefono FROM sedes WHERE id_tienda = %s AND estado = 'Activa' "
            "ORDER BY es_principal DESC, nombre",
            (id_tienda,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _catalogo_sede(id_tienda: int, id_sede: int) -> tuple[list[dict], list[dict]]:
    """Servicios y profesionales en linea de la sede. Un servicio sale si al
    menos uno de ellos lo hace."""
    profesionales, servicios = [], {}
    for p in profesional_service.listar_profesionales(id_tienda, id_sede):
        if not p["reserva_online"]:
            continue
        for s in p["servicios"]:
            servicios.setdefault(s["id_servicio"], {
                "id_servicio": s["id_servicio"], "nombre": s["nombre"],
                "duracion_min": s["duracion_min"], "precio": s["precio"],
            })
        # Columnas explicitas: ni rol, ni pago, ni sede fija.
        profesionales.append({
            "id_profesional": p["id_usuario"], "nombre": p["nombre_completo"],
            "servicios": [s["id_servicio"] for s in p["servicios"]],
        })
    return sorted(servicios.values(), key=lambda s: s["nombre"].lower()), profesionales


def datos_publicos(t: dict) -> dict:
    """Todo lo que pinta la pagina de reservas del negocio `t` (de tienda())."""
    sedes = []
    for s in _sedes(t["id_tienda"]):
        servicios, profesionales = _catalogo_sede(t["id_tienda"], s["id_sede"])
        dias = local_service.horario(t["id_tienda"], s["id_sede"])
        sedes.append({
            "id_sede": s["id_sede"], "nombre": s["nombre"], "direccion": s["direccion"],
            "whatsapp": s["telefono"] or t["telefono"],
            "horario": [{k: d[k] for k in ("dia", "nombre", "abierto", "abre", "cierra")} for d in dias],
            "servicios": servicios, "profesionales": profesionales,
        })
    return {
        "negocio": {
            "nombre": t["nombre_negocio"], "slug": t["slug"], "tipo_negocio": t["tipo_negocio"],
            "logo_url": imagen_service.url(t["id_logo"]), "whatsapp": t["telefono"],
            "recibe_reservas": t["recibe_reservas"],
        },
        "hoy": hoy_local().isoformat(),
        "max_dias": MAX_DIAS_ADELANTE,
        "sedes": sedes,
    }


def _sede_de(t: dict, id_sede) -> int:
    id_sede = parse_int(id_sede, "Sede", min_value=1)
    if id_sede not in {s["id_sede"] for s in _sedes(t["id_tienda"])}:
        raise NoEncontrado("Sede no encontrada.")
    return id_sede


def _validar_dia(dia) -> None:
    if dia < hoy_local():
        raise ErrorServicio("Ese día ya pasó.")
    if dia > hoy_local() + timedelta(days=MAX_DIAS_ADELANTE):
        raise ErrorServicio(f"Se reserva con máximo {MAX_DIAS_ADELANTE} días de anticipación.")


# ── Horas libres ────────────────────────────────────────────────────

def disponibilidad(t: dict, id_sede, id_servicio, fecha) -> dict:
    """Horas libres del dia para el servicio, solo de quienes reciben reservas
    en linea. Sin nombres de clientes ni citas: solo horas."""
    id_sede = _sede_de(t, id_sede)
    dia = agenda_service.parse_fecha(fecha)
    _validar_dia(dia)
    datos = agenda_service.disponibilidad(t["id_tienda"], id_sede, dia, id_servicio, solo_online=True)
    return {
        "fecha": datos["fecha"], "abierto": datos["abierto"], "paso_min": datos["paso_min"],
        "profesionales": [{"id_profesional": p["id_profesional"], "horas": p["horas"]} for p in datos["profesionales"]],
    }


# ── Reservar ────────────────────────────────────────────────────────

def _telefono(raw) -> str:
    digitos = only_digits(raw)
    if not 10 <= len(digitos) <= 15:
        raise ValueError("Escribe tu WhatsApp completo (10 dígitos, ej. 300 123 4567).")
    return digitos


def _pendientes(cur, id_tienda: int, telefono: str) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM citas WHERE id_tienda = %s AND cliente_telefono = %s "
        "AND estado = 'reservada' AND inicio >= %s",
        (id_tienda, telefono, ahora_local()),
    )
    return cur.fetchone()["n"]


def _candidatos(cur, id_tienda: int, id_sede: int, inicio: datetime) -> list[int]:
    """Para "cualquiera": quienes reciben reservas en linea en la sede, el que
    menos citas tiene ese dia primero (reparte el trabajo)."""
    cur.execute(
        "SELECT u.id_usuario FROM usuarios u "
        "WHERE u.id_tienda = %s AND u.estado_activo = 1 AND u.atiende = 1 AND u.reserva_online = 1 "
        "AND u.rol <> 'Master' AND (u.id_sede IS NULL OR u.id_sede = %s) "
        "ORDER BY (SELECT COUNT(*) FROM citas c WHERE c.id_profesional = u.id_usuario AND c.estado = 'reservada' "
        "AND c.inicio >= %s AND c.inicio < %s), u.nombre_completo",
        (id_tienda, id_sede, datetime.combine(inicio.date(), datetime.min.time()),
         datetime.combine(inicio.date() + timedelta(days=1), datetime.min.time())),
    )
    return [f["id_usuario"] for f in cur.fetchall()]


def _libre(cur, id_tienda: int, id_sede: int, id_profesional, servicio: dict, inicio, fin) -> dict | None:
    """El profesional si recibe reservas en linea, hace el servicio y esta
    libre de `inicio` a `fin`; si no, None."""
    try:
        profesional = _profesional(cur, id_tienda, id_sede, id_profesional)
        if not profesional["reserva_online"]:
            return None
        _servicio(cur, id_tienda, profesional, servicio["id_servicio"])
    except ErrorServicio:
        return None
    if _cruce(cur, id_tienda, id_sede, profesional["id_usuario"], inicio, fin):
        return None
    return profesional


def reservar(t: dict, data: dict) -> dict:
    """{id_sede, id_servicio, inicio, cliente_nombre, cliente_telefono,
    id_profesional?}. Sin profesional: el primero libre a esa hora."""
    if not t["recibe_reservas"]:
        raise ErrorServicio(SIN_RESERVAS, 403)
    id_sede = _sede_de(t, data.get("id_sede"))
    inicio = agenda_service.parse_momento(data.get("inicio"))
    cliente = sanitize_text(data.get("cliente_nombre"), "Tu nombre", min_len=2, max_len=60)
    telefono = _telefono(data.get("cliente_telefono"))
    _validar_dia(inicio.date())
    if inicio < ahora_local():
        raise ErrorServicio("Esa hora ya pasó. Elige otra.")
    elegido = data.get("id_profesional") not in (None, "", "cualquiera")
    id_tienda = t["id_tienda"]

    def _crear(cur):
        _bloquear_sede(cur, id_tienda, id_sede)
        # Dentro del bloqueo de la sede: dos envios seguidos no pasan los dos.
        if _pendientes(cur, id_tienda, telefono) >= MAX_PENDIENTES_POR_TELEFONO:
            raise ErrorServicio(
                f"Ya tienes {MAX_PENDIENTES_POR_TELEFONO} citas por venir en este negocio. "
                "Para otra, escríbele por WhatsApp.", 429,
            )
        # El servicio y el horario no dependen de quien atienda.
        servicio = _servicio(cur, id_tienda, {"atiende_todos": 1}, data.get("id_servicio"))
        fin = inicio + timedelta(minutes=int(servicio["duracion_min"]))
        _validar_horario(cur, id_sede, inicio, fin)
        if elegido:
            id_profesional = parse_int(data["id_profesional"], "Profesional", min_value=1)
            profesional = _libre(cur, id_tienda, id_sede, id_profesional, servicio, inicio, fin)
        else:
            profesional = next(
                filter(None, (_libre(cur, id_tienda, id_sede, p, servicio, inicio, fin)
                              for p in _candidatos(cur, id_tienda, id_sede, inicio))),
                None,
            )
        if profesional is None:
            # Ocupado, no hace el servicio o no sale en linea: la misma
            # respuesta, para no delatar a quien no se muestra.
            raise Conflicto(_NADIE_LIBRE)
        cur.execute(
            "INSERT INTO citas (id_tienda, id_sede, id_servicio, id_profesional, cliente_nombre, cliente_telefono, "
            "inicio, fin, estado, precio, origen) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'reservada', %s, 'publica')",
            (id_tienda, id_sede, servicio["id_servicio"], profesional["id_usuario"], cliente, telefono,
             inicio, fin, servicio["precio"]),
        )
        return {"id_cita": cur.lastrowid, "profesional": profesional["nombre_completo"],
                "servicio": servicio["nombre"], "precio": int(servicio["precio"]), "fin": fin}

    hecha = _escribir(_crear)
    return _confirmacion(t, _sedes(id_tienda), id_sede, inicio, cliente, hecha)


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")


def _confirmacion(t: dict, sedes: list[dict], id_sede: int, inicio: datetime, cliente: str, hecha: dict) -> dict:
    """Lo que ve el cliente al reservar y el mensaje listo para avisarle al
    negocio por WhatsApp (los recordatorios automaticos son de T12)."""
    sede = next(s for s in sedes if s["id_sede"] == id_sede)
    fecha = f"{_DIAS[inicio.weekday()]} {inicio.day} de {_MESES[inicio.month - 1]}"
    # Los textos se guardan escapados para HTML; WhatsApp los quiere planos.
    plano = html.unescape
    donde = plano(t["nombre_negocio"]) + (f" ({plano(sede['nombre'])})" if len(sedes) > 1 else "")
    texto = (
        f"Hola, soy {plano(cliente)}. Reservé {plano(hecha['servicio'])} con {plano(hecha['profesional'])} "
        f"el {fecha} a las {hora_12(inicio)} en {donde}. ¡Nos vemos!"
    )
    return {
        "id_cita": hecha["id_cita"],
        "fecha": inicio.date().isoformat(), "hora": f"{inicio:%H:%M}", "hasta": f"{hecha['fin']:%H:%M}",
        "fecha_texto": fecha,
        "servicio": hecha["servicio"], "profesional": hecha["profesional"], "precio": hecha["precio"],
        "sede": sede["nombre"], "direccion": sede["direccion"],
        "whatsapp_url": enlace_whatsapp(sede["telefono"] or t["telefono"], texto),
    }
