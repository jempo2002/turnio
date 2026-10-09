"""Tipos de negocio (T9): como habla la app y con que arranca cada uno.

Turnio sirve a barberias, salones, estudios de unas, cejas y pestanas,
estetica y profesionales independientes. Lo que cambia entre ellos no es la
logica (agenda, caja e inventario son iguales) sino:

  - El vocabulario: "barbero" en una barberia, "manicurista" en un estudio de
    unas. Sale en el panel y en la pagina publica de reservas.
  - Los ejemplos de los formularios (placeholders).
  - Los servicios con los que arranca el catalogo al crear el negocio, para
    que el link de reservas sirva desde el primer dia. Son de referencia: el
    dueno los edita o desactiva en Inventario. Precios del Valle del Cauca
    inferidos, no medidos, y pago al profesional en 0 (el dueno que empieza
    trabaja solo; la comision la pone cuando sume equipo).
  - El horario de la sede principal: el de fabrica (lunes a sabado de 8 a 7)
    salvo la barberia, que suele abrir hasta las 8 p. m. y el domingo en la
    manana.

La clave es tiendas.tipo_negocio (enum en migrations/). Un tipo desconocido
cae en "otro", que habla de "profesional" y arranca sin servicios.
"""
from __future__ import annotations

# (abierto, abre, cierra) por dia: 0 = lunes ... 6 = domingo.
_SEMANA = tuple((True, "08:00", "19:00") for _ in range(6)) + ((False, "08:00", "19:00"),)
_BARBERIA = tuple((True, "09:00", "20:00") for _ in range(6)) + ((True, "09:00", "14:00"),)

VERTICALES: dict[str, dict] = {
    "barberia": {
        "nombre": "Barbería",
        "profesional": "barbero",
        "profesionales": "barberos",
        "ejemplo_servicio": "Corte + barba",
        "ejemplo_producto": "Cera para peinar",
        "ejemplo_gasto": "Cuchillas y talco",
        "servicios": (
            ("Corte de cabello", 30, 20000),
            ("Corte + barba", 45, 28000),
            ("Arreglo de barba", 20, 12000),
            ("Cejas con navaja", 10, 5000),
        ),
        "horario": _BARBERIA,
    },
    "peluqueria": {
        "nombre": "Peluquería o salón de belleza",
        "profesional": "estilista",
        "profesionales": "estilistas",
        "ejemplo_servicio": "Corte y cepillado",
        "ejemplo_producto": "Shampoo sin sal",
        "ejemplo_gasto": "Tinte y peróxido",
        "servicios": (
            ("Corte de dama", 45, 35000),
            ("Cepillado", 45, 30000),
            ("Tinte completo", 120, 120000),
            ("Keratina", 180, 150000),
        ),
        "horario": _SEMANA,
    },
    "unas": {
        "nombre": "Estudio de uñas",
        "profesional": "manicurista",
        "profesionales": "manicuristas",
        "ejemplo_servicio": "Semipermanente en manos",
        "ejemplo_producto": "Esmalte semipermanente",
        "ejemplo_gasto": "Limas y algodón",
        "servicios": (
            ("Manicure tradicional", 45, 20000),
            ("Pedicure tradicional", 60, 25000),
            ("Semipermanente en manos", 60, 35000),
            ("Uñas acrílicas", 120, 80000),
        ),
        "horario": _SEMANA,
    },
    "cejas_pestanas": {
        "nombre": "Cejas y pestañas",
        "profesional": "especialista",
        "profesionales": "especialistas",
        "ejemplo_servicio": "Lifting de pestañas",
        "ejemplo_producto": "Sérum para pestañas",
        "ejemplo_gasto": "Pegante y parches",
        "servicios": (
            ("Diseño de cejas", 30, 20000),
            ("Laminado de cejas", 45, 50000),
            ("Lifting de pestañas", 60, 60000),
            ("Extensiones pelo a pelo", 120, 120000),
        ),
        "horario": _SEMANA,
    },
    "estetica": {
        "nombre": "Estética",
        "profesional": "esteticista",
        "profesionales": "esteticistas",
        "ejemplo_servicio": "Limpieza facial",
        "ejemplo_producto": "Protector solar",
        "ejemplo_gasto": "Cera y espátulas",
        "servicios": (
            ("Limpieza facial profunda", 60, 70000),
            ("Hidratación facial", 45, 55000),
            ("Masaje relajante", 60, 80000),
            ("Depilación con cera", 30, 25000),
        ),
        "horario": _SEMANA,
    },
    "independiente": {
        "nombre": "Profesional independiente",
        "profesional": "profesional",
        "profesionales": "profesionales",
        "ejemplo_servicio": "Corte de cabello",
        "ejemplo_producto": "Shampoo",
        "ejemplo_gasto": "Transporte",
        "servicios": (),
        "horario": _SEMANA,
    },
    "otro": {
        "nombre": "Otro",
        "profesional": "profesional",
        "profesionales": "profesionales",
        "ejemplo_servicio": "Corte de cabello",
        "ejemplo_producto": "Shampoo",
        "ejemplo_gasto": "Insumos",
        "servicios": (),
        "horario": _SEMANA,
    },
}

# Lo que muestran los <select> de registro, Ajustes y el panel Master.
TIPOS_NEGOCIO: dict[str, str] = {clave: v["nombre"] for clave, v in VERTICALES.items()}


def vertical(tipo: str | None) -> dict:
    return VERTICALES.get(tipo or "", VERTICALES["otro"])


def vocabulario(tipo: str | None) -> dict:
    """Textos para plantillas y JS: {profesional, Profesional, profesionales,
    Profesionales, ejemplo_*}. Las mayusculas van ya hechas para no repetir
    |capitalize en cada plantilla."""
    v = vertical(tipo)
    voc = {k: v[k] for k in ("profesional", "profesionales", "ejemplo_servicio", "ejemplo_producto", "ejemplo_gasto")}
    voc["Profesional"] = v["profesional"][:1].upper() + v["profesional"][1:]
    voc["Profesionales"] = v["profesionales"][:1].upper() + v["profesionales"][1:]
    return voc


def sembrar_servicios(cur, id_tienda: int, tipo: str | None) -> int:
    """Catalogo inicial del negocio (misma transaccion que lo crea). Devuelve
    cuantos servicios quedaron."""
    servicios = vertical(tipo)["servicios"]
    if not servicios:
        return 0
    cur.executemany(
        "INSERT INTO servicios (id_tienda, nombre, duracion_min, precio, pago_profesional) VALUES (%s, %s, %s, %s, 0)",
        [(id_tienda, nombre, minutos, precio) for nombre, minutos, precio in servicios],
    )
    return len(servicios)


def horario(tipo: str | None) -> tuple[tuple[bool, str, str], ...]:
    return vertical(tipo)["horario"]
