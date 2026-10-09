"""Sedes y usuarios segun el plan (tomado de jemPOS Chef)."""
import mysql.connector
import pytest

from conftest import entrar


def _admin(client, crear, plan="basico", sedes=("Principal",)):
    id_tienda, ids = crear.tienda(plan, sedes=sedes)
    crear.usuario("admin@turnio.co", "Admin", id_tienda)
    entrar(client, "admin@turnio.co")
    if len(ids) > 1:
        client.post("/seleccionar-sede", data={"id_sede": ids[0]})
    return id_tienda, ids


@pytest.mark.parametrize("plan", ["basico", "pro"])
def test_basico_y_pro_son_de_una_sede(client, crear, plan):
    _admin(client, crear, plan)
    r = client.post("/api/sedes", json={"nombre": "Norte"})
    assert r.status_code == 403
    assert r.get_json()["code"] == "limite_plan"
    assert r.get_json()["accion_texto"] == "Pasarme al Plan Multisede"
    assert "sola sede" in client.get("/sedes").get_data(as_text=True)


def test_multisede_incluye_dos_sedes_y_cobra_las_extra(client, crear):
    id_tienda, _ = _admin(client, crear, "multisede")
    assert "incluye 2 sedes" in client.get("/sedes").get_data(as_text=True)
    assert client.post("/api/sedes", json={"nombre": "Norte"}).status_code == 201
    assert client.post("/api/sedes", json={"nombre": "Sur"}).status_code == 201
    montajes = crear.fila(
        "SELECT GROUP_CONCAT(costo_montaje ORDER BY id_sede) AS m FROM sedes WHERE id_tienda = %s", (id_tienda,)
    )["m"]
    assert montajes == "0,0,79000"
    for nombre in ("Este", "Oeste"):
        assert client.post("/api/sedes", json={"nombre": nombre}).status_code == 201
    r = client.post("/api/sedes", json={"nombre": "Sexta"})
    assert r.status_code == 403 and "máximo de 5" in r.get_json()["msg"]
    assert "$274.000" in client.get("/sedes").get_data(as_text=True)  # 139.000 + 3 x 45.000


def test_la_base_rechaza_una_sexta_sede(crear):
    id_tienda, _ = crear.tienda("multisede", sedes=("A", "B", "C", "D", "E"))
    with pytest.raises(mysql.connector.Error) as exc:
        crear.sede(id_tienda, "F")
    assert exc.value.errno == 1644


def test_editar_sede_y_nombre_repetido(client, crear):
    _, (centro, norte) = _admin(client, crear, "pro", ("Centro", "Norte"))
    assert client.put(f"/api/sedes/{norte}", json={"nombre": "Norte 2", "telefono": "300 123 4567"}).status_code == 200
    assert crear.fila("SELECT telefono FROM sedes WHERE id_sede = %s", (norte,))["telefono"] == "3001234567"
    assert client.put(f"/api/sedes/{norte}", json={"nombre": "Centro"}).status_code == 409


def test_eliminar_sede_es_soft_delete(client, crear):
    id_tienda, (principal, norte) = _admin(client, crear, "pro", ("Centro", "Norte"))
    assert client.delete(f"/api/sedes/{principal}").status_code == 400
    crear.usuario("carlos@turnio.co", "Profesional", id_tienda, norte)
    assert client.delete(f"/api/sedes/{norte}").status_code == 409  # tiene usuarios
    crear.fila("UPDATE usuarios SET estado_activo = 0 WHERE correo = 'carlos@turnio.co'")
    assert client.delete(f"/api/sedes/{norte}").status_code == 200
    fila = crear.fila("SELECT estado, fecha_eliminacion FROM sedes WHERE id_sede = %s", (norte,))
    assert fila["estado"] == "Eliminada" and fila["fecha_eliminacion"] is not None
    # El nombre queda libre para una sede nueva.
    crear.sede(id_tienda, "Norte")


def test_sede_de_otro_negocio_no_se_toca(client, crear):
    _admin(client, crear)
    _, (ajena,) = crear.tienda(nombre="Otro")
    assert client.put(f"/api/sedes/{ajena}", json={"nombre": "Mia"}).status_code == 404
    assert client.delete(f"/api/sedes/{ajena}").status_code == 404


def _nuevo(n, rol="Profesional", **extra):
    return {
        "nombre": f"Persona {n}", "cc": f"10000{n:03d}", "correo": f"p{n}@turnio.co", "rol": rol,
        "password": "Clave123", "confirm_password": "Clave123", **extra,
    }


def test_tope_de_profesionales_en_basico(client, crear):
    _admin(client, crear)
    for n in range(3):
        assert client.post("/api/usuarios", json=_nuevo(n)).status_code == 201
    r = client.post("/api/usuarios", json=_nuevo(3))
    assert r.status_code == 403
    assert r.get_json()["recurso"] == "profesionales"
    assert r.get_json()["accion_texto"] == "Pasarme al Plan Pro"
    # Recepcion no topa; un Admin mas si (Basico trae 1).
    assert client.post("/api/usuarios", json=_nuevo(4, rol="Recepcion")).status_code == 201
    assert client.post("/api/usuarios", json=_nuevo(5, rol="Admin")).status_code == 403
    # Cambiar de rol a Profesional tambien cuenta.
    recepcion = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'p4@turnio.co'")["id_usuario"]
    r = client.put(f"/api/usuarios/{recepcion}", json={"nombre": "Persona 4", "rol": "Profesional"})
    assert r.status_code == 403


def test_bajar_de_plan_con_profesionales_de_sobra_se_bloquea(crear):
    from app.services import master_service

    id_tienda, (sede,) = crear.tienda("pro")
    for n in range(4):
        crear.usuario(f"p{n}@turnio.co", "Profesional", id_tienda, sede)
    with pytest.raises(ValueError, match="4 profesionales"):
        master_service.cambiar_plan(id_tienda, "basico")


def test_roles_del_negocio(client, crear):
    _admin(client, crear)
    assert client.post("/api/usuarios", json=_nuevo(1, rol="recepcion")).status_code == 201
    assert client.post("/api/usuarios", json=_nuevo(2, rol="Mesero")).status_code == 400
    assert client.post("/api/usuarios", json=_nuevo(3, rol="Master")).status_code == 400
    pagina = client.get("/equipo").get_data(as_text=True)
    assert "Recepcion" in pagina and "Persona 1" in pagina


def test_usuario_sin_sede_en_negocio_de_varias_sedes(client, crear):
    id_tienda, (centro, norte) = _admin(client, crear, "pro", ("Centro", "Norte"))
    assert client.post("/api/usuarios", json=_nuevo(1)).status_code == 400
    assert client.post("/api/usuarios", json=_nuevo(1, id_sede=norte)).status_code == 201
    fila = crear.fila("SELECT id_sede, rol FROM usuarios WHERE correo = 'p1@turnio.co'")
    assert fila == {"id_sede": norte, "rol": "Profesional"}


def test_desactivar_libera_correo_y_no_deja_sin_admin(client, crear):
    _admin(client, crear)
    yo = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'admin@turnio.co'")["id_usuario"]
    assert client.delete(f"/api/usuarios/{yo}").status_code == 400
    client.post("/api/usuarios", json=_nuevo(1))
    otro = crear.fila("SELECT id_usuario FROM usuarios WHERE correo = 'p1@turnio.co'")["id_usuario"]
    assert client.delete(f"/api/usuarios/{otro}").status_code == 200
    assert crear.fila("SELECT correo FROM usuarios WHERE id_usuario = %s", (otro,))["correo"].startswith("deleted_")
    assert client.post("/api/usuarios", json=_nuevo(1)).status_code == 201  # correo libre otra vez
    r = client.put(f"/api/usuarios/{yo}", json={"nombre": "Yo", "rol": "Recepcion"})
    assert r.status_code == 400


def test_asistente_ia_requiere_plan_pro(app, crear):
    from flask import Blueprint, jsonify

    from app.services.plan_service import requiere_funcion
    from app.utils.decorators import login_required

    bp = Blueprint("prueba", __name__)

    @bp.get("/api/asistente-prueba")
    @login_required
    @requiere_funcion("asistente_ia")
    def asistente():
        return jsonify({"ok": True})

    app.register_blueprint(bp)
    for plan, esperado in (("basico", 403), ("pro", 200)):
        id_tienda, _ = crear.tienda(plan, nombre=plan)
        crear.usuario(f"{plan}@turnio.co", "Admin", id_tienda)
        c = app.test_client()
        entrar(c, f"{plan}@turnio.co")
        assert c.get("/api/asistente-prueba").status_code == esperado, plan
