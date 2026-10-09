"""Agenda (T6): citas con la duracion real del servicio, bloqueos de horario,
cancelar, reprogramar y los espacios libres de cada profesional.

Horas: todo va en hora de Colombia (app/utils/helpers.ZONA_NEGOCIO) y se
guarda sin zona, como lo compara MySQL. Si el cliente manda una hora con zona
(`...Z` o `-05:00`), se pasa a la del negocio.

Cruces: una cita ocupa de `inicio` a `fin`. MySQL no tiene exclusion
constraints, asi que cada escritura bloquea la fila de la sede (y la del
profesional) con SELECT ... FOR UPDATE y despues busca cruces: dos reservas
simultaneas en la misma sede se atienden en fila. El UNIQUE
uq_citas_profesional_franja queda de respaldo para la misma hora de inicio.

Bloqueos: filas de `citas` con estado 'bloqueada'. id_profesional NULL =
toda la sede. El almuerzo del horario de la sede tambien bloquea.

El cobro (pasar la cita a 'completada' y registrar la caja) es de T5.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from mysql.connector import IntegrityError

from app.services.errores import Conflicto, ErrorServicio, NoEncontrado
from app.utils.helpers import ZONA_NEGOCIO, ahora_local, hoy_local, normalize_phone
from app.utils.validation import parse_int, sanitize_optional_text, sanitize_text
from database import get_db

PASO_MIN = 15  # cada cuanto se ofrece una hora libre
MAX_DIAS_CONSULTA = 42  # vista de semana o de mes, no mas
MAX_DIAS_BLOQUEO = 31  # vacaciones
VIGENTES = ("reservada", "bloqueada")
_OCUPADO = "Ese horario ya está ocupado."


# ── Fechas y horas ──────────────────────────────────────────────────

def parse_fecha(raw, etiqueta: str = "La fecha") -> date:
    try:
        return date.fromisoformat(str(raw or "").strip()[:10])
    except ValueError as exc:
        raise ValueError(f"{etiqueta}: fecha invalida (usa AAAA-MM-DD).") from exc


def parse_momento(raw, etiqueta: str = "La hora") -> datetime:
    """'2026-10-09T15:30' en hora de Colombia, o con zona y se convierte."""
    texto = str(raw or "").strip().replace(" ", "T")
    if texto.endswith(("Z", "z")):
        texto = texto[:-1] + "+00:00"
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError as exc:
        raise ValueError(f"{etiqueta}: fecha y hora invalidas (usa AAAA-MM-DDTHH:MM).") from exc
    if momento.tzinfo is not None:
        momento = momento.astimezone(ZONA_NEGOCIO).replace(tzinfo=None)
    return momento.replace(second=0, microsecond=0)


def _iso(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%dT%H:%M")


def _hora(valor) -> time:
    """MySQL devuelve TIME como timedelta."""
    if isinstance(valor, timedelta):
        minutos = int(valor.total_seconds() // 60)
        return time(minutos // 60, minutos % 60)
    return valor


def _se_cruzan(a_ini, a_fin, b_ini, b_fin) -> bool:
    return a_ini < b_fin and b_ini < a_fin


# ── Lecturas ────────────────────────────────────────────────────────

_SELECT_CITA = (
    "SELECT c.id_cita, c.id_sede, c.id_servicio, c.id_profesional, c.cliente_nombre, c.cliente_telefono, "
    "c.inicio, c.fin, c.estado, c.precio, c.origen, c.nota, c.motivo_cancelacion, "
    "s.nombre AS servicio, u.nombre_completo AS profesional "
    "FROM citas c "
    "LEFT JOIN servicios s ON s.id_servicio = c.id_servicio "
    "LEFT JOIN usuarios u ON u.id_usuario = c.id_profesional "
)


def _fila(f: dict) -> dict:
    return {
        "id_cita": f["id_cita"],
        "estado": f["estado"],
        "fecha": f["inicio"].date().isoformat(),
        "hora": f["inicio"].strftime("%H:%M"),
        "inicio": _iso(f["inicio"]),
        "fin": _iso(f["fin"]),
        "duracion_min": int((f["fin"] - f["inicio"]).total_seconds() // 60),
        "id_profesional": f["id_profesional"],
        "profesional": f["profesional"],
        "toda_la_sede": f["estado"] == "bloqueada" and f["id_profesional"] is None,
        "id_servicio": f["id_servicio"],
        "servicio": f["servicio"],
        "cliente_nombre": f["cliente_nombre"],
        "cliente_telefono": f["cliente_telefono"],
        "precio": int(f["precio"]),
        "origen": f["origen"],
        "nota": f["nota"],
        "motivo_cancelacion": f["motivo_cancelacion"],
    }


def listar(id_tienda: int, id_sede: int, desde: date, hasta: date, id_profesional: int | None = None) -> list[dict]:
    """Citas y bloqueos de la sede entre dos dias (ambos incluidos), sin las
    canceladas. Un bloqueo de varios dias sale en todos los que toca."""
    if hasta < desde:
        raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
    if (hasta - desde).days >= MAX_DIAS_CONSULTA:
        raise ValueError(f"Consulta como maximo {MAX_DIAS_CONSULTA} dias.")
    sql = (
        _SELECT_CITA + "WHERE c.id_tienda = %s AND c.id_sede = %s AND c.estado <> 'cancelada' "
        "AND c.inicio < %s AND c.fin > %s"
    )
    params: list = [id_tienda, id_sede, datetime.combine(hasta + timedelta(days=1), time()), datetime.combine(desde, time())]
    if id_profesional is not None:
        # Su agenda: sus citas y los bloqueos de toda la sede.
        sql += " AND (c.id_profesional = %s OR (c.id_profesional IS NULL AND c.estado = 'bloqueada'))"
        params.append(id_profesional)
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql + " ORDER BY c.inicio, c.id_cita", params)
        return [_fila(f) for f in cur.fetchall()]
    finally:
        conn.close()


def obtener(id_tienda: int, id_sede: int, id_cita: int) -> dict:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(_SELECT_CITA + "WHERE c.id_cita = %s AND c.id_tienda = %s AND c.id_sede = %s",
                    (id_cita, id_tienda, id_sede))
        fila = cur.fetchone()
    finally:
        conn.close()
    if not fila:
        raise NoEncontrado("Cita no encontrada.")
    return _fila(fila)


# ── Validaciones dentro de la transaccion ───────────────────────────

def _bloquear_sede(cur, id_tienda: int, id_sede: int) -> None:
    cur.execute(
        "SELECT id_sede FROM sedes WHERE id_sede = %s AND id_tienda = %s AND estado = 'Activa' FOR UPDATE",
        (id_sede, id_tienda),
    )
    if not cur.fetchone():
        raise NoEncontrado("Sede no encontrada.")


def _profesional(cur, id_tienda: int, id_sede: int, id_profesional) -> dict:
    """Quien atiende en la sede, bloqueado para esta transaccion."""
    id_profesional = parse_int(id_profesional, "Profesional", min_value=1)
    cur.execute(
        "SELECT id_usuario, nombre_completo, atiende_todos, reserva_online FROM usuarios "
        "WHERE id_usuario = %s AND id_tienda = %s AND estado_activo = 1 AND atiende = 1 AND rol <> 'Master' "
        "AND (id_sede IS NULL OR id_sede = %s) FOR UPDATE",
        (id_profesional, id_tienda, id_sede),
    )
    fila = cur.fetchone()
    if not fila:
        raise NoEncontrado("Profesional no encontrado en esta sede.")
    return fila


def _servicio(cur, id_tienda: int, profesional: dict, id_servicio) -> dict:
    id_servicio = parse_int(id_servicio, "Servicio", min_value=1)
    cur.execute(
        "SELECT id_servicio, nombre, duracion_min, precio FROM servicios "
        "WHERE id_servicio = %s AND id_tienda = %s AND estado_activo = 1",
        (id_servicio, id_tienda),
    )
    servicio = cur.fetchone()
    if not servicio:
        raise NoEncontrado("Servicio no encontrado.")
    if not profesional["atiende_todos"]:
        cur.execute(
            "SELECT 1 FROM profesional_servicios WHERE id_usuario = %s AND id_servicio = %s",
            (profesional["id_usuario"], id_servicio),
        )
        if not cur.fetchone():
            raise ErrorServicio(f"{profesional['nombre_completo']} no hace {servicio['nombre']}.")
    return servicio


def _horario_del_dia(cur, id_sede: int, dia: date) -> dict | None:
    cur.execute(
        "SELECT abierto, abre, cierra, almuerzo_desde, almuerzo_hasta FROM horarios_sede WHERE id_sede = %s AND dia = %s",
        (id_sede, dia.weekday()),
    )
    fila = cur.fetchone()
    if not fila or not fila["abierto"]:
        return None
    return {
        "abre": datetime.combine(dia, _hora(fila["abre"])),
        "cierra": datetime.combine(dia, _hora(fila["cierra"])),
        "almuerzo": (
            (datetime.combine(dia, _hora(fila["almuerzo_desde"])), datetime.combine(dia, _hora(fila["almuerzo_hasta"])))
            if fila["almuerzo_desde"] is not None else None
        ),
    }


def _validar_horario(cur, id_sede: int, inicio: datetime, fin: datetime) -> None:
    if inicio.date() < hoy_local():
        raise ErrorServicio("No se puede agendar en un día que ya pasó.")
    horario = _horario_del_dia(cur, id_sede, inicio.date())
    if horario is None:
        raise ErrorServicio("La sede no abre ese día.")
    if inicio < horario["abre"] or fin > horario["cierra"]:
        raise ErrorServicio(
            f"Fuera del horario: ese día se atiende de {horario['abre']:%H:%M} a {horario['cierra']:%H:%M} "
            f"y la cita terminaría a las {fin:%H:%M}."
        )
    almuerzo = horario["almuerzo"]
    if almuerzo and _se_cruzan(inicio, fin, *almuerzo):
        raise ErrorServicio(f"Se cruza con el almuerzo ({almuerzo[0]:%H:%M} a {almuerzo[1]:%H:%M}).")


def _cruce(cur, id_tienda: int, id_sede: int, id_profesional: int | None, inicio: datetime, fin: datetime,
           estados=VIGENTES, excluir: int = 0) -> dict | None:
    """Primera cita o bloqueo vigente que se cruza. Con profesional: lo suyo
    (en cualquier sede) y los bloqueos de toda la sede. Sin profesional (un
    bloqueo de toda la sede): lo de cualquiera en la sede."""
    marcas = ", ".join(["%s"] * len(estados))
    sql = (
        f"SELECT inicio, fin, estado FROM citas WHERE id_tienda = %s AND estado IN ({marcas}) "
        "AND inicio < %s AND fin > %s AND id_cita <> %s AND "
    )
    params: list = [id_tienda, *estados, fin, inicio, excluir]
    if id_profesional is None:
        sql += "id_sede = %s"
        params.append(id_sede)
    else:
        sql += "(id_profesional = %s OR (id_profesional IS NULL AND id_sede = %s))"
        params += [id_profesional, id_sede]
    cur.execute(sql + " ORDER BY inicio LIMIT 1", params)
    return cur.fetchone()


def _sin_cruces(cur, id_tienda, id_sede, id_profesional, inicio, fin, excluir: int = 0) -> None:
    otra = _cruce(cur, id_tienda, id_sede, id_profesional, inicio, fin, excluir=excluir)
    if otra:
        que = "un bloqueo" if otra["estado"] == "bloqueada" else "otra cita"
        raise Conflicto(f"{_OCUPADO} Se cruza con {que} de {otra['inicio']:%H:%M} a {otra['fin']:%H:%M}.")


def _duracion(data: dict, servicio: dict) -> int:
    """La del servicio, o una propia para esta cita (un combo, un cabello largo)."""
    if data.get("duracion_min") in (None, ""):
        return int(servicio["duracion_min"])
    return parse_int(data["duracion_min"], "La duracion", min_value=5, max_value=720)


def _escribir(fn):
    """Corre fn(cur) en una transaccion; un UNIQUE roto es un cruce."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        resultado = fn(cur)
        conn.commit()
        return resultado
    except IntegrityError as exc:
        conn.rollback()
        raise Conflicto(_OCUPADO) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Citas ───────────────────────────────────────────────────────────

def crear_cita(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> int:
    inicio = parse_momento(data.get("inicio"))
    cliente = sanitize_text(data.get("cliente_nombre"), "El nombre del cliente", max_len=120)
    telefono = normalize_phone(data.get("cliente_telefono"), max_len=20)
    nota = sanitize_optional_text(data.get("nota"), "La nota")

    def _crear(cur):
        _bloquear_sede(cur, id_tienda, id_sede)
        profesional = _profesional(cur, id_tienda, id_sede, data.get("id_profesional"))
        servicio = _servicio(cur, id_tienda, profesional, data.get("id_servicio"))
        fin = inicio + timedelta(minutes=_duracion(data, servicio))
        _validar_horario(cur, id_sede, inicio, fin)
        _sin_cruces(cur, id_tienda, id_sede, profesional["id_usuario"], inicio, fin)
        cur.execute(
            "INSERT INTO citas (id_tienda, id_sede, id_servicio, id_profesional, cliente_nombre, cliente_telefono, "
            "inicio, fin, estado, precio, origen, nota, id_usuario_registra) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'reservada', %s, 'panel', %s, %s)",
            (id_tienda, id_sede, servicio["id_servicio"], profesional["id_usuario"], cliente, telefono,
             inicio, fin, servicio["precio"], nota, id_usuario),
        )
        return cur.lastrowid

    return _escribir(_crear)


def _cita_para_cambiar(cur, id_tienda: int, id_sede: int, id_cita: int, estados=("reservada",)) -> dict:
    cur.execute(
        "SELECT id_cita, id_servicio, id_profesional, inicio, fin, estado FROM citas "
        "WHERE id_cita = %s AND id_tienda = %s AND id_sede = %s FOR UPDATE",
        (id_cita, id_tienda, id_sede),
    )
    cita = cur.fetchone()
    if not cita:
        raise NoEncontrado("Cita no encontrada.")
    if cita["estado"] not in estados:
        raise ErrorServicio(f"La cita ya está {cita['estado'].replace('_', ' ')}: no se puede cambiar.", 409)
    return cita


def dueno_de_cita(id_tienda: int, id_sede: int, id_cita: int) -> int | None:
    """id_profesional de la cita (para que un Profesional solo toque lo suyo)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id_profesional FROM citas WHERE id_cita = %s AND id_tienda = %s AND id_sede = %s",
                    (id_cita, id_tienda, id_sede))
        fila = cur.fetchone()
    finally:
        conn.close()
    if not fila:
        raise NoEncontrado("Cita no encontrada.")
    return fila[0]


def reprogramar(id_tienda: int, id_sede: int, id_cita: int, data: dict) -> None:
    """Mueve una cita reservada: otra hora, otro profesional u otro servicio.
    Lo que no venga queda igual; la duracion se recalcula con el servicio."""
    nuevo_inicio = parse_momento(data["inicio"]) if data.get("inicio") else None

    def _mover(cur):
        # La sede primero, como al crear: mismo orden de bloqueos, sin deadlocks.
        _bloquear_sede(cur, id_tienda, id_sede)
        cita = _cita_para_cambiar(cur, id_tienda, id_sede, id_cita)
        profesional = _profesional(cur, id_tienda, id_sede, data.get("id_profesional") or cita["id_profesional"])
        servicio = _servicio(cur, id_tienda, profesional, data.get("id_servicio") or cita["id_servicio"])
        inicio = nuevo_inicio or cita["inicio"]
        if "duracion_min" in data or "id_servicio" in data:
            duracion = _duracion(data, servicio)
        else:
            duracion = int((cita["fin"] - cita["inicio"]).total_seconds() // 60)
        fin = inicio + timedelta(minutes=duracion)
        _validar_horario(cur, id_sede, inicio, fin)
        _sin_cruces(cur, id_tienda, id_sede, profesional["id_usuario"], inicio, fin, excluir=id_cita)
        cur.execute(
            "UPDATE citas SET inicio = %s, fin = %s, id_profesional = %s, id_servicio = %s, precio = %s "
            "WHERE id_cita = %s",
            (inicio, fin, profesional["id_usuario"], servicio["id_servicio"], servicio["precio"], id_cita),
        )

    _escribir(_mover)


def cancelar(id_tienda: int, id_sede: int, id_cita: int, motivo=None) -> None:
    motivo = sanitize_optional_text(motivo, "El motivo")

    def _cancelar(cur):
        _cita_para_cambiar(cur, id_tienda, id_sede, id_cita)
        cur.execute("UPDATE citas SET estado = 'cancelada', motivo_cancelacion = %s WHERE id_cita = %s",
                    (motivo, id_cita))

    _escribir(_cancelar)


def marcar_no_asistio(id_tienda: int, id_sede: int, id_cita: int) -> None:
    def _marcar(cur):
        cita = _cita_para_cambiar(cur, id_tienda, id_sede, id_cita)
        if cita["inicio"] > ahora_local():
            raise ErrorServicio("La cita todavía no empieza.")
        cur.execute("UPDATE citas SET estado = 'no_asistio' WHERE id_cita = %s", (id_cita,))

    _escribir(_marcar)


# ── Bloqueos ────────────────────────────────────────────────────────

def crear_bloqueo(id_tienda: int, id_sede: int, id_usuario: int, data: dict) -> int:
    """Bloquea de `desde` a `hasta` la agenda de un profesional, o la de toda
    la sede si no viene id_profesional. Si hay citas reservadas en ese rato,
    no bloquea: primero hay que moverlas o cancelarlas."""
    desde = parse_momento(data.get("desde"), "Desde")
    hasta = parse_momento(data.get("hasta"), "Hasta")
    motivo = sanitize_optional_text(data.get("motivo"), "El motivo")
    if hasta <= desde:
        raise ValueError("El bloqueo debe terminar después de empezar.")
    if hasta - desde > timedelta(days=MAX_DIAS_BLOQUEO):
        raise ValueError(f"Un bloqueo dura como maximo {MAX_DIAS_BLOQUEO} días.")
    if hasta.date() < hoy_local():
        raise ErrorServicio("Ese horario ya pasó.")

    def _crear(cur):
        _bloquear_sede(cur, id_tienda, id_sede)
        id_profesional = None
        if data.get("id_profesional") not in (None, ""):
            id_profesional = _profesional(cur, id_tienda, id_sede, data["id_profesional"])["id_usuario"]
        cita = _cruce(cur, id_tienda, id_sede, id_profesional, desde, hasta, estados=("reservada",))
        if cita:
            raise Conflicto(
                f"Hay citas reservadas en ese horario (la primera el {cita['inicio']:%d/%m a las %H:%M}). "
                "Reprográmalas o cancélalas antes de bloquear."
            )
        cur.execute(
            "INSERT INTO citas (id_tienda, id_sede, id_profesional, inicio, fin, estado, nota, id_usuario_registra) "
            "VALUES (%s, %s, %s, %s, %s, 'bloqueada', %s, %s)",
            (id_tienda, id_sede, id_profesional, desde, hasta, motivo, id_usuario),
        )
        return cur.lastrowid

    return _escribir(_crear)


def quitar_bloqueo(id_tienda: int, id_sede: int, id_cita: int) -> None:
    def _quitar(cur):
        _cita_para_cambiar(cur, id_tienda, id_sede, id_cita, estados=("bloqueada",))
        # Un bloqueo no es historia del negocio: se borra.
        cur.execute("DELETE FROM citas WHERE id_cita = %s", (id_cita,))

    _escribir(_quitar)


# ── Espacios libres ─────────────────────────────────────────────────

def disponibilidad(id_tienda: int, id_sede: int, dia: date, id_servicio, id_profesional=None,
                   solo_online: bool = False) -> dict:
    """Horas de inicio libres ese dia para el servicio, por profesional: dentro
    del horario, fuera del almuerzo, sin cruzar citas ni bloqueos y, si es
    hoy, desde ahora. Cada PASO_MIN minutos. `solo_online`: solo quienes
    reciben reservas en linea (la pagina publica, T8)."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        sql = (
            "SELECT id_usuario, nombre_completo, atiende_todos FROM usuarios "
            "WHERE id_tienda = %s AND estado_activo = 1 AND atiende = 1 AND rol <> 'Master' "
            "AND (id_sede IS NULL OR id_sede = %s)"
        )
        params: list = [id_tienda, id_sede]
        if solo_online:
            sql += " AND reserva_online = 1"
        if id_profesional not in (None, ""):
            sql += " AND id_usuario = %s"
            params.append(parse_int(id_profesional, "Profesional", min_value=1))
        cur.execute(sql + " ORDER BY nombre_completo", params)
        profesionales = cur.fetchall()
        servicio = None
        resultado = []
        horario = _horario_del_dia(cur, id_sede, dia)
        for p in profesionales:
            try:
                servicio = _servicio(cur, id_tienda, p, id_servicio)
            except ErrorServicio as exc:
                if isinstance(exc, NoEncontrado):
                    raise
                continue  # no hace ese servicio
            resultado.append({"id_profesional": p["id_usuario"], "nombre": p["nombre_completo"],
                              "horas": _horas_libres(cur, id_tienda, id_sede, p["id_usuario"], dia, horario,
                                                     int(servicio["duracion_min"]))})
    finally:
        conn.close()
    return {"fecha": dia.isoformat(), "abierto": horario is not None, "paso_min": PASO_MIN,
            "profesionales": resultado}


def _horas_libres(cur, id_tienda, id_sede, id_profesional, dia, horario, duracion: int) -> list[str]:
    if horario is None or dia < hoy_local():
        return []
    cur.execute(
        "SELECT inicio, fin FROM citas WHERE id_tienda = %s AND estado IN ('reservada', 'bloqueada') "
        "AND inicio < %s AND fin > %s AND (id_profesional = %s OR (id_profesional IS NULL AND id_sede = %s))",
        (id_tienda, horario["cierra"], horario["abre"], id_profesional, id_sede),
    )
    ocupado = [(f["inicio"], f["fin"]) for f in cur.fetchall()]
    if horario["almuerzo"]:
        ocupado.append(horario["almuerzo"])
    paso, largo = timedelta(minutes=PASO_MIN), timedelta(minutes=duracion)
    t = horario["abre"]
    if dia == hoy_local():
        ahora = ahora_local()
        while t < ahora:
            t += paso
    horas = []
    while t + largo <= horario["cierra"]:
        if not any(_se_cruzan(t, t + largo, a, b) for a, b in ocupado):
            horas.append(t.strftime("%H:%M"))
        t += paso
    return horas
