"""Precios, topes y funciones por plan (sin base de datos).

Los valores son los aprobados el 2026-10-08 (turnio/planes-y-precios.md)."""
from app.services import plan_service as ps


def test_precios_aprobados():
    assert {p: ps.PLANES[p]["precio"] for p in ps.PLANES} == {
        "basico": 49000, "pro": 89000, "multisede": 139000,
    }


def test_funciones_por_plan():
    for funcion in ("asistente_ia", "whatsapp_auto", "comisiones"):
        assert not ps.tiene_funcion("basico", funcion)
        assert ps.tiene_funcion("pro", funcion)
        assert ps.tiene_funcion("multisede", funcion)
    assert ps.tiene_funcion("multisede", "multisede")
    assert not ps.tiene_funcion("pro", "multisede")


def test_topes_por_plan():
    assert ps.tope("basico", "profesionales") == 3
    assert ps.tope("pro", "profesionales") == 10
    assert ps.tope("multisede", "profesionales", 3) == 30
    assert [ps.tope(p, "administradores") for p in ("basico", "pro", "multisede")] == [1, 2, 2]
    assert ps.tope("basico", "productos") == 150
    assert ps.tope("pro", "productos") is None
    assert [ps.PLANES[p]["mensajes_whatsapp"] for p in ("basico", "pro", "multisede")] == [0, 500, 1000]
    assert ps.recurso_de_rol("Profesional") == "profesionales"
    assert ps.recurso_de_rol("Recepcion") is None


def test_sedes_y_mensualidad():
    for plan in ("basico", "pro"):
        assert ps.tope_sedes(plan) == 1
        assert ps.mensualidad(plan, 1) == ps.PLANES[plan]["precio"]
    assert ps.tope_sedes("multisede") is None
    # 2 sedes incluidas; de la 3.a a la 5.a, $45.000 al mes; desde la 6.a, $35.000.
    assert ps.mensualidad("multisede", 2) == 139000
    assert ps.mensualidad("multisede", 5) == 139000 + 3 * 45000
    assert ps.mensualidad("multisede", 7) == 139000 + 3 * 45000 + 2 * 35000
    assert ps.costo_montaje_nueva_sede("multisede", 9) == 79000
    assert ps.costo_montaje_nueva_sede("multisede", 1) == 0
    assert ps.costo_montaje_nueva_sede("multisede", 2) == 79000


def test_prueba_gratis_es_del_pro():
    assert ps.PLAN_PRUEBA == "pro" and ps.DIAS_PRUEBA == 14


def test_plan_desconocido_se_trata_como_basico():
    assert ps.normalizar_plan(None) == "basico"
    assert ps.normalizar_plan("completo") == "basico"
    assert not ps.tiene_funcion(None, "asistente_ia")


def test_limite_de_sedes_ofrece_multisede():
    cuerpo, status = ps.LimitePlanError("sedes", "pro", 1).respuesta()
    assert status == 403 and cuerpo["code"] == "limite_plan"
    assert cuerpo["accion_texto"] == "Pasarme al Plan Multisede"
    assert cuerpo["accion_url"].startswith("https://wa.me/") and "Turnio" in cuerpo["accion_url"]


def test_limite_de_profesionales():
    cuerpo, _ = ps.LimitePlanError("profesionales", "basico", 3).respuesta()
    assert cuerpo["accion_texto"] == "Pasarme al Plan Pro" and cuerpo["beneficios"]
    # Multisede no sube el tope por sede: se venden profesionales extra.
    cuerpo, _ = ps.LimitePlanError("profesionales", "pro", 10).respuesta()
    assert cuerpo["accion_texto"] == "Escribirnos por WhatsApp"
    assert "$9.000" in cuerpo["msg"]
