"""Planes de suscripcion de Turnio (tiendas.plan_id) y sus limites.

Tomado de jemPOS Chef. Fuente unica de precios, topes y funciones por plan.
Los precios los aprobo jempo el 2026-10-08 (turnio/planes-y-precios.md) y son
los del landing (index.html, seccion #planes), en COP por mes:

  Basico     $49.000  1 sede, 3 profesionales, 1 Admin, 150 productos.
                      Agenda, caja, inventario y recordatorios manuales.
  Pro        $89.000  1 sede, 10 profesionales, 2 Admin, productos sin tope.
                      + asistente con IA y WhatsApp automatico (500 msgs/mes).
  Multisede $139.000  2 sedes incluidas y hasta 5 (cada extra $45.000/mes y
                      montaje de $79.000), 10 profesionales por sede, 2 Admin.
                      Todo lo del Pro, con 1.000 mensajes/mes.

Los topes son de profesionales (rol Profesional: quien tiene agenda) y de
administradores (rol Admin). Recepcion no tiene tope: es el encargado de
cada sede. Los productos solo topan en el Basico, igual que en jemPOS.

plan_id NULL (no deberia pasar: el Master siempre elige plan) se trata como
Basico, el plan mas restringido, para que un dato faltante nunca abra
funciones pagas.
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from flask import flash, g, jsonify, redirect, url_for

WHATSAPP = "https://wa.me/573106152268"

PLAN_POR_DEFECTO = "basico"
# Todo negocio nuevo arranca con DIAS_PRUEBA dias de este plan, sin tarjeta.
PLAN_PRUEBA = "pro"
DIAS_PRUEBA = 14

# Tope absoluto de sedes activas (lo repiten los triggers de `sedes`).
MAX_SEDES = 5
# Montaje de cada sede por encima de las incluidas en el plan.
COSTO_MONTAJE_SEDE = 79000
# Mensualidad de cada sede por encima de las incluidas (50 % del Pro).
PRECIO_SEDE_EXTRA = 45000
# Cada profesional por encima del tope del plan, al mes (lo cobra el Master).
PRECIO_PROFESIONAL_EXTRA = 9000
# Paquete de mensajes de WhatsApp automaticos extra: (mensajes, precio).
PAQUETE_WHATSAPP = (500, 15000)

_FUNCIONES_PRO = frozenset({"asistente_ia", "whatsapp_auto", "comisiones"})

PLANES: dict[str, dict] = {
    "basico": {
        "nombre": "Básico",
        "precio": 49000,
        "sedes_incluidas": 1,
        "max_sedes": 1,
        "profesionales_por_sede": 3,
        "administradores": 1,
        "productos": 150,
        "mensajes_whatsapp": 0,
        "funciones": frozenset(),
    },
    "pro": {
        "nombre": "Pro",
        "precio": 89000,
        "sedes_incluidas": 1,
        "max_sedes": 1,
        "profesionales_por_sede": 10,
        "administradores": 2,
        "productos": None,
        "mensajes_whatsapp": 500,
        "funciones": _FUNCIONES_PRO,
    },
    "multisede": {
        "nombre": "Multisede",
        "precio": 139000,
        "sedes_incluidas": 2,
        "max_sedes": MAX_SEDES,
        "profesionales_por_sede": 10,
        "administradores": 2,
        "productos": None,
        "mensajes_whatsapp": 1000,
        "funciones": _FUNCIONES_PRO | {"multisede"},
    },
}
for _plan in PLANES.values():
    _plan["sede_extra"] = PRECIO_SEDE_EXTRA if _plan["max_sedes"] > _plan["sedes_incluidas"] else None
PLANES_VALIDOS = tuple(PLANES)

# Para el mensaje de "esta funcion no viene en tu plan".
NOMBRE_FUNCION = {
    "asistente_ia": "El asistente con IA",
    "whatsapp_auto": "Los recordatorios y la confirmación automática por WhatsApp",
    "comisiones": "Las comisiones y la liquidación por profesional",
    "multisede": "Tener varias sedes",
}

# Plan al que se sube desde cada uno, y lo que se gana al llegar a cada uno:
# alimentan el aviso de upsell.
_SIGUIENTE = {"basico": "pro", "pro": "multisede"}
_BENEFICIOS = {
    "pro": (
        "Hasta 10 profesionales con agenda",
        "Recordatorios y confirmación automática por WhatsApp",
        "Comisiones y liquidación automática por profesional",
        "Asistente con IA e inventario ilimitado",
    ),
    "multisede": (
        "2 sedes incluidas y hasta 5",
        "Caja, inventario y reportes por sede y consolidados",
        "1.000 mensajes automáticos de WhatsApp al mes",
    ),
}


def plan_de(plan_id: str | None) -> dict:
    return PLANES.get(plan_id or "", PLANES[PLAN_POR_DEFECTO])


def normalizar_plan(plan_id: str | None) -> str:
    return plan_id if plan_id in PLANES else PLAN_POR_DEFECTO


def tiene_funcion(plan_id: str | None, funcion: str) -> bool:
    return funcion in plan_de(plan_id)["funciones"]


def tope_sedes(plan_id: str | None) -> int:
    """Maximo de sedes activas: 1 en Basico y Pro, MAX_SEDES en Multisede."""
    return plan_de(plan_id)["max_sedes"]


# Recursos con tope y el rol de usuario que cuenta para cada uno.
ROL_DE_RECURSO = {"profesionales": "Profesional", "administradores": "Admin"}


def tope(plan_id: str | None, recurso: str, sedes_activas: int = 1) -> int | None:
    """Cuantos `recurso` admite el plan. None = sin tope."""
    plan = plan_de(plan_id)
    if recurso == "sedes":
        return plan["max_sedes"]
    if recurso == "profesionales":
        return plan["profesionales_por_sede"] * max(1, int(sedes_activas))
    if recurso == "administradores":
        return plan["administradores"]
    if recurso == "productos":
        return plan["productos"]
    raise ValueError(f"Recurso desconocido: {recurso}")


def recurso_de_rol(rol: str) -> str | None:
    """'profesionales' o 'administradores' segun el rol; None si no tiene tope."""
    for recurso, r in ROL_DE_RECURSO.items():
        if r == rol:
            return recurso
    return None


def sedes_extra(plan_id: str | None, sedes_activas: int) -> int:
    """Sedes por encima de las incluidas en el precio del plan."""
    return max(0, int(sedes_activas) - plan_de(plan_id)["sedes_incluidas"])


def mensualidad(plan_id: str | None, sedes_activas: int) -> int:
    """Lo que paga el negocio al mes: plan + PRECIO_SEDE_EXTRA por sede extra."""
    plan = plan_de(plan_id)
    return plan["precio"] + sedes_extra(plan_id, sedes_activas) * (plan["sede_extra"] or 0)


def costo_montaje_nueva_sede(plan_id: str | None, sedes_activas: int) -> int:
    """Montaje de la proxima sede: gratis si entra en las incluidas."""
    return COSTO_MONTAJE_SEDE if sedes_extra(plan_id, int(sedes_activas) + 1) else 0


_QUE = {"profesionales": "profesionales con agenda", "administradores": "administradores",
        "productos": "productos", "sedes": "sedes"}


def _sube(antes: int | None, despues: int | None) -> bool:
    if antes is None:
        return False
    return despues is None or despues > antes


def plan_para_crecer(plan_id: str | None, recurso: str) -> str | None:
    """Plan al que hay que pasar para tener mas `recurso`, o None si ningun
    plan sube ese tope (ahi se habla por WhatsApp)."""
    if recurso == "sedes":
        return None if plan_id == "multisede" else "multisede"
    destino = _SIGUIENTE.get(plan_id or "")
    if destino and _sube(tope(plan_id, recurso), tope(destino, recurso)):
        return destino
    return None


def _mensaje(recurso: str, plan_id: str, tope_: int) -> str:
    nombre = plan_de(plan_id)["nombre"]
    destino = plan_para_crecer(plan_id, recurso)
    if recurso == "sedes":
        if destino:
            return (
                f"Tu Plan {nombre} es para una sola sede. Si tu negocio abrió otro local, "
                f"pásate al Plan {PLANES[destino]['nombre']}."
            )
        return f"Llegaste al máximo de {tope_} sedes. Para más sedes escríbenos."
    base = f"Tu Plan {nombre} permite {tope_} {_QUE[recurso]}."
    if destino:
        return f"{base} Para sumar más pásate al Plan {PLANES[destino]['nombre']}."
    if recurso == "profesionales":
        extra = f"{PRECIO_PROFESIONAL_EXTRA:,}".replace(",", ".")
        return f"{base} Escríbenos y sumamos más por ${extra} al mes cada uno."
    return f"{base} Escríbenos si necesitas más."


class LimitePlanError(Exception):
    def __init__(self, recurso: str, plan_id: str, tope: int):
        self.recurso = recurso
        self.plan_id = plan_id
        super().__init__(_mensaje(recurso, plan_id, tope))

    def respuesta(self) -> tuple[dict, int]:
        """Cuerpo JSON + 403. `code` le dice al front que muestre el aviso de
        cambio de plan en vez del error normal."""
        actual = plan_de(self.plan_id)["nombre"]
        destino = plan_para_crecer(self.plan_id, self.recurso)
        if destino:
            texto = f"Hola, tengo el Plan {actual} de Turnio y quiero pasarme al Plan {PLANES[destino]['nombre']}."
            cta = f"Pasarme al Plan {PLANES[destino]['nombre']}"
        else:
            texto = f"Hola, tengo el Plan {actual} de Turnio y necesito más {_QUE[self.recurso]}."
            cta = "Escribirnos por WhatsApp"
        return {
            "ok": False,
            "code": "limite_plan",
            "recurso": self.recurso,
            "plan": self.plan_id,
            "msg": str(self),
            "accion_url": WHATSAPP + "?text=" + quote(texto),
            "accion_texto": cta,
            "beneficios": list(_BENEFICIOS.get(destino, ())),
        }, 403


def _contar_sedes(cur, id_tienda: int) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM sedes WHERE id_tienda = %s AND estado = 'Activa'",
        (id_tienda,),
    )
    return int(cur.fetchone()["n"])


_CONTEO = {
    "profesionales": (
        "SELECT COUNT(*) AS n FROM usuarios "
        "WHERE id_tienda = %s AND estado_activo = 1 AND rol = 'Profesional'"
    ),
    "administradores": (
        "SELECT COUNT(*) AS n FROM usuarios "
        "WHERE id_tienda = %s AND estado_activo = 1 AND rol = 'Admin'"
    ),
    "productos": "SELECT COUNT(*) AS n FROM productos WHERE id_tienda = %s AND estado_activo = 1",
}


def _contar(cur, id_tienda: int, recurso: str) -> int:
    if recurso == "sedes":
        return _contar_sedes(cur, id_tienda)
    cur.execute(_CONTEO[recurso], (id_tienda,))
    return int(cur.fetchone()["n"])


def verificar_limite(cur, id_tienda: int, recurso: str) -> None:
    """Lanza LimitePlanError si agregar uno mas de `recurso` ('sedes',
    'profesionales', 'administradores' o 'productos') pasa el tope del plan.

    `cur` debe ser un cursor dictionary=True dentro de la transaccion del alta.
    El FOR UPDATE bloquea la fila de la tienda hasta el commit del llamador:
    dos altas simultaneas no pueden pasar las dos el conteo."""
    if recurso != "sedes" and recurso not in _CONTEO:
        raise ValueError(f"Recurso desconocido: {recurso}")
    cur.execute("SELECT plan_id FROM tiendas WHERE id_tienda = %s FOR UPDATE", (id_tienda,))
    plan_id = normalizar_plan((cur.fetchone() or {}).get("plan_id"))
    tope_ = tope(plan_id, recurso, _contar_sedes(cur, id_tienda))
    if tope_ is not None and _contar(cur, id_tienda, recurso) >= tope_:
        raise LimitePlanError(recurso, plan_id, tope_)


def verificar_limite_rol(cur, id_tienda: int, rol: str) -> None:
    """verificar_limite para sumar un usuario con `rol` (Recepcion no topa)."""
    recurso = recurso_de_rol(rol)
    if recurso:
        verificar_limite(cur, id_tienda, recurso)


def verificar_cambio_plan(cur, id_tienda: int, plan_nuevo: str) -> None:
    """ValueError si el negocio usa mas de lo que el plan nuevo permite.

    Bajar a un plan con menos sedes, profesionales, administradores o
    productos de los que el negocio tiene activos dejaria datos fuera de plan:
    primero hay que quitarlos. Mismo FOR UPDATE que verificar_limite.
    """
    if plan_nuevo not in PLANES:
        raise ValueError("Plan invalido.")
    cur.execute("SELECT 1 FROM tiendas WHERE id_tienda = %s FOR UPDATE", (id_tienda,))
    cur.fetchone()
    sedes = _contar_sedes(cur, id_tienda)
    nombre = PLANES[plan_nuevo]["nombre"]
    for recurso, accion in (
        ("sedes", "Elimina las sedes de sobra"),
        ("profesionales", "Desactiva profesionales"),
        ("administradores", "Cambia de rol o desactiva administradores"),
        ("productos", "Desactiva productos"),
    ):
        tope_ = tope(plan_nuevo, recurso, sedes)
        if tope_ is None:
            continue
        n = sedes if recurso == "sedes" else _contar(cur, id_tienda, recurso)
        if n > tope_:
            raise ValueError(
                f"El negocio tiene {n} {_QUE[recurso]} y el Plan {nombre} permite {tope_}. "
                f"{accion} antes de cambiar de plan."
            )


def requiere_funcion(funcion: str):
    """Decorador para rutas de funciones pagas (ej. asistente_ia). Va DESPUES de
    login_required, que deja el plan de la tienda en g.plan_id."""
    if funcion not in NOMBRE_FUNCION:
        raise ValueError(f"Funcion desconocida: {funcion}")

    def decorator(f):
        @wraps(f)
        def _inner(*args, **kwargs):
            plan_id = g.get("plan_id")
            if g.get("es_master") or tiene_funcion(plan_id, funcion):
                return f(*args, **kwargs)
            from app.utils.decorators import _is_api_request, log_seguridad

            log_seguridad("funcion_fuera_de_plan", funcion=funcion, plan=plan_id)
            msg = f"{NOMBRE_FUNCION[funcion]} no viene en tu Plan {plan_de(plan_id)['nombre']}."
            if _is_api_request():
                return jsonify({"ok": False, "code": "funcion_no_incluida", "funcion": funcion, "msg": msg}), 403
            flash(msg, "error")
            return redirect(url_for("core.inicio"))

        return _inner

    return decorator
