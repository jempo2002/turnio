"""Precios, topes y funciones por plan (sin base de datos)."""
from app.services import plan_service as ps


def test_precios_del_landing():
    assert ps.PLANES["basico"]["precio"] == 49000
    assert ps.PLANES["pro"]["precio"] == 89000
    assert set(ps.PLANES) == {"basico", "pro"}


def test_funciones_del_pro():
    for funcion in ("asistente_ia", "whatsapp_auto"):
        assert not ps.tiene_funcion("basico", funcion)
        assert ps.tiene_funcion("pro", funcion)


def test_todavia_ningun_plan_trae_varias_sedes():
    for plan in ps.PLANES:
        assert ps.tope_sedes(plan) == 1
        assert not ps.tiene_funcion(plan, "multisede")
        assert ps.mensualidad(plan, 1) == ps.PLANES[plan]["precio"]


def test_sin_tope_de_usuarios():
    assert ps.tope_usuarios("basico", 1) is None
    assert ps.tope_usuarios("pro", 3) is None


def test_plan_desconocido_se_trata_como_basico():
    assert ps.normalizar_plan(None) == "basico"
    assert ps.normalizar_plan("completo") == "basico"
    assert not ps.tiene_funcion(None, "asistente_ia")


def test_respuesta_de_limite_de_sedes():
    cuerpo, status = ps.LimitePlanError("sedes", "basico", 1).respuesta()
    assert status == 403 and cuerpo["code"] == "limite_plan"
    assert cuerpo["accion_texto"] == "Escribirnos por WhatsApp"
    assert cuerpo["accion_url"].startswith("https://wa.me/")
    assert "Turnio" in cuerpo["accion_url"]


def test_respuesta_de_limite_de_usuarios_ofrece_el_pro():
    cuerpo, _ = ps.LimitePlanError("usuarios", "basico", 5).respuesta()
    assert cuerpo["accion_texto"] == "Pasarme al Plan Pro"
    assert cuerpo["beneficios"]
