# Turnio

Agenda, reservas 24/7, caja e inventario para negocios con cita, pensada para el celular.

Reglas de trabajo y ramas: [CLAUDE.md](CLAUDE.md). Plan hasta el deploy: [docs/auditoria-y-workflow.md](docs/auditoria-y-workflow.md).

## Qué hay en el repo

- **App Flask** (`app/`, `templates/`, `static/`, `migrations/`, `scripts/`, `tests/`): el backend de Turnio, construido sobre la base de jemPOS Chef (Flask + MySQL + Redis). Hoy trae login, recuperación de contraseña, sesiones revalidadas en cada petición, modo solo lectura al vencer la suscripción, cabeceras de seguridad, planes, panel Master, sedes y equipo. La agenda, la caja y el inventario van encima en las tareas T3 a T6.
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

- **Roles**: Master (administra los negocios), Admin (dueño o encargado), Recepción y Profesional (quien atiende; sus citas y comisiones van a su nombre).
- **Planes** (los del landing): Básico $49.000 y Pro $89.000 al mes. Pro suma el asistente con IA y la confirmación automática por WhatsApp (`requiere_funcion("asistente_ia")`). Sin tope de usuarios y una sola sede por ahora (varias sedes llegan con T15).
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
