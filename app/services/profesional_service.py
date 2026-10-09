"""Quienes atienden en el negocio (T4): foto, si reciben reservas en linea,
que servicios hacen y cuanto ganan por cada uno.

Un profesional es cualquier usuario activo con `atiende = 1`: todo
Profesional, y el Admin o Recepcion que tambien atiende (el dueno que corta).
Con `atiende_todos = 1` hace todo el catalogo con el pago de cada servicio;
con 0, solo lo que diga profesional_servicios, donde puede tener un pago
propio (NULL = el del servicio).
"""
from __future__ import annotations

from app.services import imagen_service, plan_service
from app.services.errores import ErrorServicio, NoEncontrado
from app.utils.validation import parse_bool, parse_int
from database import get_db


def _servicios_por_profesional(cur, id_tienda: int, profesionales: list[dict]) -> None:
    cur.execute(
        "SELECT id_servicio, nombre, duracion_min, precio, pago_profesional FROM servicios "
        "WHERE id_tienda = %s AND estado_activo = 1 ORDER BY nombre",
        (id_tienda,),
    )
    catalogo = cur.fetchall()
    ids = [p["id_usuario"] for p in profesionales if not p["atiende_todos"]]
    propios: dict[int, dict[int, int | None]] = {i: {} for i in ids}
    if ids:
        marcas = ", ".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT id_usuario, id_servicio, pago_profesional FROM profesional_servicios WHERE id_usuario IN ({marcas})",
            ids,
        )
        for f in cur.fetchall():
            propios[f["id_usuario"]][f["id_servicio"]] = f["pago_profesional"]
    for p in profesionales:
        suyos = None if p["atiende_todos"] else propios[p["id_usuario"]]
        p["servicios"] = [
            {
                "id_servicio": s["id_servicio"],
                "nombre": s["nombre"],
                "duracion_min": int(s["duracion_min"]),
                "precio": int(s["precio"]),
                "pago_profesional": int(s["pago_profesional"] if not suyos or suyos[s["id_servicio"]] is None
                                        else suyos[s["id_servicio"]]),
            }
            for s in catalogo
            if suyos is None or s["id_servicio"] in suyos
        ]


def listar_profesionales(id_tienda: int, id_sede: int | None = None) -> list[dict]:
    """Quienes atienden en la sede dada (o en todas), con sus servicios. Un
    Admin sin sede fija atiende en todas."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        sql = (
            "SELECT id_usuario, nombre_completo, rol, id_sede, reserva_online, atiende_todos, id_foto "
            "FROM usuarios WHERE id_tienda = %s AND estado_activo = 1 AND atiende = 1 AND rol <> 'Master'"
        )
        params: list = [id_tienda]
        if id_sede is not None:
            sql += " AND (id_sede IS NULL OR id_sede = %s)"
            params.append(id_sede)
        cur.execute(sql + " ORDER BY nombre_completo", params)
        profesionales = cur.fetchall()
        _servicios_por_profesional(cur, id_tienda, profesionales)
    finally:
        conn.close()
    for p in profesionales:
        p["reserva_online"] = bool(p["reserva_online"])
        p["atiende_todos"] = bool(p["atiende_todos"])
        p["foto_url"] = imagen_service.url(p.pop("id_foto"))
    return profesionales


def _usuario_de_tienda(cur, id_tienda: int, id_usuario: int) -> dict:
    cur.execute(
        "SELECT id_usuario, rol, atiende, id_foto FROM usuarios "
        "WHERE id_usuario = %s AND id_tienda = %s AND estado_activo = 1 AND rol <> 'Master' FOR UPDATE",
        (id_usuario, id_tienda),
    )
    usuario = cur.fetchone()
    if not usuario:
        raise NoEncontrado("Usuario no encontrado.")
    return usuario


def _parse_servicios(cur, id_tienda: int, raw) -> list[tuple[int, int | None]]:
    """[{id_servicio, pago_profesional?}] o [id_servicio, ...] -> pares
    (id, pago propio o None), validados contra el catalogo activo."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Elige al menos un servicio.")
    pares: dict[int, int | None] = {}
    for item in raw:
        item = item if isinstance(item, dict) else {"id_servicio": item}
        id_servicio = parse_int(item.get("id_servicio"), "Servicio", min_value=1)
        pago = item.get("pago_profesional")
        pares[id_servicio] = None if pago in (None, "") else parse_int(pago, "El pago al profesional", min_value=0)
    marcas = ", ".join(["%s"] * len(pares))
    cur.execute(
        f"SELECT id_servicio, precio FROM servicios WHERE id_tienda = %s AND estado_activo = 1 "
        f"AND id_servicio IN ({marcas})",
        [id_tienda, *pares],
    )
    precios = {f["id_servicio"]: int(f["precio"]) for f in cur.fetchall()}
    if len(precios) != len(pares):
        raise ValueError("Alguno de los servicios no existe.")
    for id_servicio, pago in pares.items():
        if pago is not None and pago > precios[id_servicio]:
            raise ValueError("El pago al profesional no puede ser mayor que el precio del servicio.")
    return list(pares.items())


def actualizar_profesional(id_tienda: int, id_usuario: int, data: dict) -> None:
    """Campos opcionales: atiende, reserva_online y servicios ("todos" o la
    lista de servicios que hace, con su pago propio si lo tiene). Lanza
    LimitePlanError si prender `atiende` pasa el tope del plan."""
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_de_tienda(cur, id_tienda, id_usuario)
        cambios: dict[str, int] = {}
        if "atiende" in data:
            atiende = parse_bool(data["atiende"])
            if not atiende and usuario["rol"] == "Profesional":
                raise ErrorServicio("Un Profesional siempre atiende. Cámbiale el rol si ya no atiende.")
            if atiende and not usuario["atiende"]:
                # Tener agenda cuenta en el tope de profesionales del plan.
                plan_service.verificar_limite(cur, id_tienda, "profesionales")
            cambios["atiende"] = int(atiende)
        if "reserva_online" in data:
            cambios["reserva_online"] = int(parse_bool(data["reserva_online"]))
        if "servicios" in data:
            todos = data["servicios"] == "todos"
            pares = [] if todos else _parse_servicios(cur, id_tienda, data["servicios"])
            cambios["atiende_todos"] = int(todos)
            cur.execute("DELETE FROM profesional_servicios WHERE id_usuario = %s", (id_usuario,))
            if pares:
                cur.executemany(
                    "INSERT INTO profesional_servicios (id_usuario, id_servicio, pago_profesional) VALUES (%s, %s, %s)",
                    [(id_usuario, i, p) for i, p in pares],
                )
        if cambios:
            asignaciones = ", ".join(f"{campo} = %s" for campo in cambios)
            cur.execute(f"UPDATE usuarios SET {asignaciones} WHERE id_usuario = %s AND id_tienda = %s",
                        [*cambios.values(), id_usuario, id_tienda])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_foto(id_tienda: int, id_usuario: int, datos: bytes | None) -> str | None:
    """Pone la foto (datos) o la quita (None). Devuelve su URL."""
    tipo = imagen_service.validar(datos) if datos is not None else None
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        usuario = _usuario_de_tienda(cur, id_tienda, id_usuario)
        id_foto = imagen_service.guardar(cur, id_tienda, datos, tipo) if datos is not None else None
        cur.execute("UPDATE usuarios SET id_foto = %s WHERE id_usuario = %s AND id_tienda = %s",
                    (id_foto, id_usuario, id_tienda))
        imagen_service.borrar(cur, id_tienda, usuario["id_foto"])
        conn.commit()
        return imagen_service.url(id_foto)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
