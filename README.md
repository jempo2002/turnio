# Turnio

Agenda, reservas 24/7, caja e inventario para negocios con cita, pensada para el celular.

Reglas de trabajo y ramas: [CLAUDE.md](CLAUDE.md). Plan hasta el deploy: [docs/auditoria-y-workflow.md](docs/auditoria-y-workflow.md).

## Qué hay en el repo

- **App Flask** (`app/`, `templates/`, `static/`, `migrations/`, `scripts/`, `tests/`): el backend de Turnio, construido sobre la base de jemPOS Chef (Flask + MySQL + Redis). Hoy trae registro de negocios, login, invitaciones al equipo, recuperación de contraseña, sesiones revalidadas en cada petición, modo solo lectura al vencer la suscripción, cabeceras de seguridad, planes, panel Master, sedes y equipo. La agenda, la caja y el inventario van encima en las tareas T3 a T6.
- **Prototipo del frontend** (`index.html`, `login.html`, `citas.html`, `caja.html`, `inventario.html`, `configuracion.html`, `reservar.html`): datos en `localStorage`, es el diseño de referencia de las pantallas. Para verlo: `python3 -m http.server 8000`.
- **Backend Node** (`backend/`): el primer backend (Express + PostgreSQL). Ya no se desarrolla; queda como referencia hasta portar sus piezas (candado de reservas, cobro atómico, reservas públicas) en T6 y T8, y entonces se borra.

## App Flask

Tomado de jemPOS Chef (que no se modifica):

| Pieza | Archivo |
|---|---|
| Login, logout, recuperar contraseña, elegir sede | `app/routes/auth.py`, `app/services/auth_service.py` |
| Sesión revalidada en la base, roles, solo lectura al vencer | `app/utils/decorators.py` |
| HTTPS, HSTS, CSP, cookies seguras, ProxyFix | `app/security.py` |
| Planes y límites | `app/services/plan_service.py` |
| Panel Master: alta de negocios, plan, pagos, baja | `app/services/master_service.py`, `/panel-master` |
| Sedes y equipo | `app/services/sede_service.py`, `app/services/usuario_service.py`, `/sedes`, `/equipo` |
| Pool MySQL con zona horaria de Colombia | `database.py`, `app/utils/helpers.py` |

Lo propio de Turnio:

- **Registro abierto** (`/registro` y `POST /api/auth/register`, T3): el dueño crea su negocio, su sede principal y su cuenta de Admin en un paso y entra de una vez, con la prueba gratis. Límite de 5 registros por hora por IP y campo trampa contra bots. El Master también puede crear negocios desde su panel (misma función, `crear_negocio`).
- **Invitaciones al equipo** (T3): en `/equipo`, si el Admin deja la contraseña vacía, la persona queda invitada y el Admin recibe un enlace con botón de WhatsApp (también sale por correo si hay SMTP). Con el enlace (`/invitacion/<token>`, 7 días, un solo uso) elige su contraseña y entra. Mientras no la acepte, el Admin puede sacar un enlace nuevo; después ya no (usa "Olvidé mi contraseña").
- **Roles**: Master (administra los negocios), Admin (dueño o encargado: configura el negocio y ve todo), Recepción (agenda y caja de todos) y Profesional (quien atiende; sus citas y comisiones van a su nombre). Cada negocio solo ve lo suyo: los servicios filtran por `id_tienda` de la sesión, y un ID de otro negocio responde 404 (`tests/test_registro.py`).
- **Planes** (aprobados el 2026-10-08, los mismos del landing; fuente única en `app/services/plan_service.py`):
  - Básico $49.000/mes: 1 sede, hasta 3 profesionales con agenda, 1 Admin y 150 productos.
  - Pro $89.000/mes: 1 sede, hasta 10 profesionales, 2 Admin, productos sin tope, asistente con IA, comisiones y recordatorios automáticos por WhatsApp (500 mensajes al mes).
  - Multisede $139.000/mes: todo lo del Pro con 2 sedes incluidas y hasta 5 (cada sede extra suma $45.000/mes y $79.000 de montaje), 10 profesionales por sede y 1.000 mensajes.
  - Todo negocio nuevo arranca con 14 días gratis del Pro; al registrar el primer pago el Master le pone el plan elegido. Recepción no tiene tope. Profesional extra $9.000/mes y paquete de 500 mensajes $15.000 (los cobra el Master por ahora).
- **Catálogo y configuración** (T4, `app/routes/catalogo.py`): leer es para todo el equipo; cambiar, del Admin.
  - `GET/POST /api/servicios`, `PUT/DELETE /api/servicios/<id>`: nombre, duración, precio y lo que gana quien lo hace. Eliminar es soft delete.
  - `GET /api/profesionales` (quienes atienden en la sede, con sus servicios) y `PUT /api/profesionales/<id>`: `atiende`, `reserva_online` y `servicios` (`"todos"` o la lista, cada uno con su pago propio opcional). Todo Profesional atiende; el Admin o Recepción que también atiende tiene agenda y cuenta en el tope del plan. El dueño que se registra empieza atendiendo.
  - `POST/DELETE /api/usuarios/<id>/foto` y `/api/negocio/logo` (multipart, campo `imagen`): PNG, JPG o WebP de hasta 2 MB, guardados en la base y servidos en `/img/<id>`.
  - `GET/PUT /api/negocio`: nombre, tipo de negocio, WhatsApp y enlace de reservas (`slug`). La dirección es de cada sede.
  - `GET/PUT /api/horario` (`?id_sede=` para otra sede): los 7 días con apertura, cierre y almuerzo. Toda sede nueva nace con lunes a sábado de 8 a. m. a 7 p. m.
- **Negocios**: cada uno tiene `slug` (su página pública de reservas, `/r/<slug>`, en T8) y `tipo_negocio` (barbería, peluquería, uñas, cejas y pestañas, estética).
- **Esquema** (`migrations/`): negocios, sedes y usuarios; horario por sede; servicios con duración, precio y pago al profesional; citas con candado por profesional y hora; productos con código de barras; movimientos de caja con la comisión de cada cobro.

### Arrancar en local

Necesitas MariaDB 10.6+ o MySQL 8 y, opcionalmente, Redis.

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env              # FLASK_ENV=development y datos de la base
python scripts/migrar.py          # aplica las migraciones pendientes
python scripts/crear_master.py "Tu nombre" tu@correo.com
python scripts/crear_demo.py      # opcional: barbería demo con citas de hoy
python run.py                     # http://127.0.0.1:5000
```

`crear_demo.py` crea "Barbería Turnio Demo" con los datos del prototipo y los usuarios `admin@`, `recepcion@`, `carlos@` y `junior@turnio.demo` (misma contraseña, que pide por consola o toma de `DEMO_CLAVE`).

### Migraciones

- Cada cambio de la base es un archivo nuevo en `migrations/`, con la fecha al inicio del nombre (el orden alfabético es el de aplicación) y escrito para poder repetirse (`IF NOT EXISTS`).
- `python scripts/migrar.py` aplica las pendientes y las anota en `schema_migraciones`. `--estado` lista aplicadas y pendientes.
- Una migración aplicada no se edita: `migrar.py` se detiene si su contenido cambió. Se escribe una nueva.

### Pruebas

Necesitan una base MariaDB/MySQL (se borran y se crean `turnio_pytest` y `turnio_pytest_migrar`) y, opcionalmente, Redis:

```bash
TEST_DB_USER=usuario TEST_DB_PASSWORD=clave TEST_REDIS_URL=redis://localhost:6379/15 pytest
```

Sin base, solo corren las de planes. El prototipo tiene las suyas: `node test-calculo.js`.
