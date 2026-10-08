"""Planes de suscripcion de Turnio (tiendas.plan_id) y sus limites.

Tomado de jemPOS Chef. Fuente unica de precios, topes y funciones por plan.
Los precios son los del landing (index.html, seccion #planes), en COP por mes:

  Basico  $49.000  agenda, caja con desglose por profesional, inventario,
                   venta rapida y recordatorios manuales por WhatsApp
  Pro     $89.000  + asistente con IA y confirmacion automatica por WhatsApp

Topes: el landing no limita usuarios, asi que `usuarios_por_sede` es None
(sin tope) hasta que jempo fije uno. Ningun plan trae multisede todavia
(llega con T15): todos quedan en una sede. La maquinaria de Chef para varias
sedes (tope, sede extra al 50 %, montaje) se conserva para entonces.

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

MAX_SEDES = 4
COSTO_MONTAJE_SEDE = 79000
# Mensualidad de cada sede extra como fraccion del precio del plan.
FRACCION_SEDE_EXTRA = 0.5

PLANES: dict[str, dict] = {
    "basico": {
        "nombre": "Básico",
        "precio": 49000,
        "usuarios_por_sede": None,
        "funciones": frozenset(),
    },
    "pro": {
        "nombre": "Pro",
        "precio": 89000,
        "usuarios_por_sede": None,
        "funciones": frozenset({"asistente_ia", "whatsapp_auto"}),
    },
}
for _plan in PLANES.values():
    _multisede = "multisede" in _plan["funciones"]
    _plan["max_sedes"] = MAX_SEDES if _multisede else 1
    _plan["sede_extra"] = round(_plan["precio"] * FRACCION_SEDE_EXTRA) if _multisede else None
PLANES_VALIDOS = tuple(PLANES)

# Para el mensaje de "esta funcion no viene en tu plan".
NOMBRE_FUNCION = {
    "asistente_ia": "El asistente con IA",
    "whatsapp_auto": "La confirmación y reprogramación automática por WhatsApp",
    "multisede": "Tener varias sedes",
}

# Plan al que se sube desde cada uno y lo que gana: alimenta el aviso de upsell.
_SIGUIENTE = {
    "basico": ("pro", (
        "Asistente con IA que responde y gestiona por ti",
        "Reportes de caja e inventario conversando",
        "Confirmación y reprogramación automática por WhatsApp",
    )),
}


def plan_de(plan_id: str | None) -> dict:
    return PLANES.get(plan_id or "", PLANES[PLAN_POR_DEFECTO])


def normalizar_plan(plan_id: str | None) -> str:
    return plan_id if plan_id in PLANES else PLAN_POR_DEFECTO


def tiene_funcion(plan_id: str | None, funcion: str) -> bool:
    return funcion in plan_de(plan_id)["funciones"]


def tope_sedes(plan_id: str | None) -> int:
    """Maximo de sedes activas: 1 en Basico, MAX_SEDES con multisede."""
    return plan_de(plan_id)["max_sedes"]


def tope_usuarios(plan_id: str | None, sedes_activas: int) -> int | None:
    """Usuarios activos (sin contar Master) que admite el plan. None = sin tope."""
    por_sede = plan_de(plan_id)["usuarios_por_sede"]
    return None if por_sede is None else por_sede * max(1, int(sedes_activas))


def sedes_extra(plan_id: str | None, sedes_activas: int) -> int:
    """Sedes por encima de la principal (la unica incluida en el precio)."""
    return max(0, int(sedes_activas) - 1)


def mensualidad(plan_id: str | None, sedes_activas: int) -> int:
    """Lo que paga el negocio al mes: plan + 50 % del plan por sede extra."""
    plan = plan_de(plan_id)
    return plan["precio"] + sedes_extra(plan_id, sedes_activas) * (plan["sede_extra"] or 0)


def _mensaje(recurso: str, plan_id: str, tope: int) -> str:
    nombre = plan_de(plan_id)["nombre"]
    if recurso == "sedes":
        if tope >= MAX_SEDES:
            return f"Llegaste al máximo de {MAX_SEDES} sedes. Para más sedes escríbenos."
        return (
            f"Tu Plan {nombre} es para una sola sede. Si tu negocio abrió otro local, "
            "escríbenos y lo habilitamos."
        )
    base = f"Tu Plan {nombre} permite {tope} usuarios activos."
    siguiente = _SIGUIENTE.get(plan_id)
    if siguiente:
        return f"{base} Para sumar más personas pásate al Plan {PLANES[siguiente[0]]['nombre']}."
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
        # Sedes: ningun plan las suma todavia, se habla por WhatsApp.
        destino = None if self.recurso == "sedes" else (_SIGUIENTE.get(self.plan_id) or (None,))[0]
        if destino:
            texto = f"Hola, tengo el Plan {actual} de Turnio y quiero pasarme al Plan {PLANES[destino]['nombre']}."
            cta = f"Pasarme al Plan {PLANES[destino]['nombre']}"
        else:
            falta = "más sedes" if self.recurso == "sedes" else "más usuarios"
            texto = f"Hola, tengo el Plan {actual} de Turnio y necesito {falta}."
            cta = "Escribirnos por WhatsApp"
        return {
            "ok": False,
            "code": "limite_plan",
            "recurso": self.recurso,
            "plan": self.plan_id,
            "msg": str(self),
            "accion_url": WHATSAPP + "?text=" + quote(texto),
            "accion_texto": cta,
            "beneficios": list(_SIGUIENTE.get(self.plan_id, (None, ()))[1]),
        }, 403


def _contar_sedes(cur, id_tienda: int) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM sedes WHERE id_tienda = %s AND estado = 'Activa'",
        (id_tienda,),
    )
    return int(cur.fetchone()["n"])


def _contar_usuarios(cur, id_tienda: int) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM usuarios "
        "WHERE id_tienda = %s AND estado_activo = 1 AND rol <> 'Master'",
        (id_tienda,),
    )
    return int(cur.fetchone()["n"])


def verificar_limite(cur, id_tienda: int, recurso: str) -> None:
    """Lanza LimitePlanError si agregar uno mas de `recurso` ('sedes' o
    'usuarios') pasa el tope del plan.

    `cur` debe ser un cursor dictionary=True dentro de la transaccion del alta.
    El FOR UPDATE bloquea la fila de la tienda hasta el commit del llamador:
    dos altas simultaneas no pueden pasar las dos el conteo."""
    cur.execute("SELECT plan_id FROM tiendas WHERE id_tienda = %s FOR UPDATE", (id_tienda,))
    plan_id = normalizar_plan((cur.fetchone() or {}).get("plan_id"))
    sedes = _contar_sedes(cur, id_tienda)
    if recurso == "sedes":
        tope = tope_sedes(plan_id)
        if sedes >= tope:
            raise LimitePlanError("sedes", plan_id, tope)
        return
    if recurso == "usuarios":
        tope = tope_usuarios(plan_id, sedes)
        if tope is not None and _contar_usuarios(cur, id_tienda) >= tope:
            raise LimitePlanError("usuarios", plan_id, tope)
        return
    raise ValueError(f"Recurso desconocido: {recurso}")


def verificar_cambio_plan(cur, id_tienda: int, plan_nuevo: str) -> None:
    """ValueError si el negocio usa mas de lo que el plan nuevo permite.

    Bajar a un plan con menos sedes o usuarios de los que el negocio tiene
    activos dejaria datos fuera de plan: primero hay que quitarlos. Mismo
    FOR UPDATE que verificar_limite.
    """
    if plan_nuevo not in PLANES:
        raise ValueError("Plan invalido.")
    cur.execute("SELECT 1 FROM tiendas WHERE id_tienda = %s FOR UPDATE", (id_tienda,))
    cur.fetchone()
    sedes = _contar_sedes(cur, id_tienda)
    tope = tope_sedes(plan_nuevo)
    nombre = PLANES[plan_nuevo]["nombre"]
    if sedes > tope:
        raise ValueError(
            f"El negocio tiene {sedes} sedes activas y el Plan {nombre} permite {tope}. "
            "Elimina las sedes de sobra antes de cambiar de plan."
        )
    usuarios = _contar_usuarios(cur, id_tienda)
    tope_u = tope_usuarios(plan_nuevo, sedes)
    if tope_u is not None and usuarios > tope_u:
        raise ValueError(
            f"El negocio tiene {usuarios} usuarios activos y el Plan {nombre} permite {tope_u}. "
            "Desactiva usuarios antes de cambiar de plan."
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
