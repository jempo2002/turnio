# Turnio

Agenda, reservas 24/7, caja e inventario para negocios con cita, pensada para el celular.

Reglas de trabajo y ramas: [CLAUDE.md](CLAUDE.md). Plan hasta el deploy: [docs/auditoria-y-workflow.md](docs/auditoria-y-workflow.md).

## Qué hay en el repo

- **App Flask** (`app/`, `templates/`, `static/`, `migrations/`, `scripts/`, `tests/`): el backend de Turnio, construido sobre la base de jemPOS Chef (Flask + MySQL + Redis). Hoy trae registro de negocios, login, invitaciones al equipo, recuperación de contraseña, sesiones revalidadas en cada petición, modo solo lectura al vencer la suscripción, cabeceras de seguridad, planes, panel Master, sedes y equipo, catálogo y configuración (T4), caja e inventario (T5) y agenda (T6).
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
- **Agenda** (T6, `app/routes/agenda.py`): todo en hora de Colombia; si llega una hora con zona (`...Z`), se convierte. Admin y Recepción manejan la agenda de todos; un Profesional ve la de su sede pero solo toca lo suyo.
  - `GET /api/citas?fecha=` (por defecto hoy) o `?desde=&hasta=` (semana, hasta 42 días), opcional `&id_profesional=`. `GET /api/citas/<id>`.
  - `POST /api/citas`: profesional, servicio, `inicio`, cliente. Ocupa la duración real del servicio (o `duracion_min` propia), así que bloquea los huecos siguientes; tiene que caber en el horario de la sede y fuera del almuerzo. Dos reservas a la vez en la misma sede se atienden en fila (`FOR UPDATE`): solo entra una.
  - `PUT /api/citas/<id>`: reprogramar (hora, profesional o servicio). `POST /api/citas/<id>/cancelar` (`motivo` opcional) libera el horario. `POST /api/citas/<id>/no-asistio`. Cobrar la cita es de la caja (T5).
  - `POST /api/bloqueos` (`desde`, `hasta`, `motivo`, `id_profesional` opcional: sin él bloquea toda la sede; hasta 31 días) y `DELETE /api/bloqueos/<id>`. No se bloquea encima de citas reservadas.
  - `GET /api/agenda/disponibilidad?id_servicio=&fecha=`: horas libres de cada profesional que hace ese servicio, cada 15 minutos.
- **Caja e inventario** (T5, `app/routes/caja.py`). Montos en pesos enteros; métodos `efectivo` y `transferencia`; pago mixto con `"pagos": [{"metodo", "monto"}, ...]` que debe sumar el total.
  - Caja del día por sede (`cajas_dia`): no se abre, nace sola con el primer movimiento. `GET /api/caja` (`?fecha=`, y para el Admin `?id_sede=` o `todas` para la consolidada): ingresos, salidas, efectivo esperado en el cajón (base + efectivo que entró − el que salió), transferencias, desglose por profesional, lo que queda para el local y los movimientos. `PUT /api/caja/base`, `POST /api/caja/gastos`, `DELETE /api/caja/movimientos/<id>` (solo gastos), `POST /api/caja/cierre` (`contado`: guarda el arqueo y la diferencia) y `POST /api/caja/reabrir` (Admin). Un día cerrado no recibe cobros, ventas ni gastos.
  - Cobro de citas: `POST /api/citas/<id>/cobrar` cobra, guarda lo que gana el profesional (su pago propio o el del servicio, nunca más que lo cobrado) y deja la cita completada, todo o nada. `precio` opcional para descuentos. El Profesional cobra solo sus citas; una cita sin profesional queda a nombre de quien la cobra si atiende. `DELETE /api/citas/<id>/cobro` lo deshace mientras el día siga abierto y la comisión no se haya pagado.
  - Venta rápida: `POST /api/ventas` con `items` por `id_producto` o `codigo_barras` (lector del celular). Precios del catálogo, stock de la sede, todo en una transacción. `DELETE /api/ventas/<id>` la anula (Admin y Recepción) y devuelve el stock.
  - Productos (`/api/productos`, catálogo del Admin; `GET /api/productos/codigo/<codigo>` para el lector): el stock es de cada sede (`stock_sedes`) y cada cambio queda en el kardex (`movimientos_inventario`, no se edita ni se borra). `POST /api/productos/<id>/movimientos` para Entrada, Salida o Ajuste. El Básico topa en 150 productos. Pro: `GET /api/inventario/alertas` (stock en el mínimo). Multisede: `POST /api/inventario/traslados`.
  - Gastos y ganancia real: `GET /api/caja/mes?mes=AAAA-MM` (Admin): servicios − comisiones + productos − su costo − gastos.
  - Comisiones (Pro): `GET /api/comisiones` (lo ganado en el periodo, lo pendiente y los pagos; el Profesional ve solo lo suyo) y `POST /api/comisiones/liquidar` (Admin): paga lo pendiente hasta una fecha desde la caja de hoy y marca esos cobros para no pagarlos dos veces.
- **Negocios**: cada uno tiene `slug` (su página pública de reservas, `/r/<slug>`, en T8) y `tipo_negocio` (barbería, peluquería, uñas, cejas y pestañas, estética).
- **Esquema** (`migrations/`): negocios, sedes y usuarios; horario por sede; servicios con duración, precio y pago al profesional; citas con candado por profesional y hora; productos con código de barras y stock por sede con kardex; ventas; movimientos de caja con la comisión de cada cobro; caja del día con arqueo; liquidaciones de comisiones.

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

### CI y seguridad (T10)

En cada PR hacia `test` o `main` corren en GitHub Actions (`.github/workflows/`):

- **CI**: `pytest` contra MariaDB 10.11 y Redis 7 (si la base no responde, falla en vez de saltarse), `node test-calculo.js` y `pip-audit` sobre `requirements.txt`.
- **CodeQL**: análisis de seguridad de Python y JavaScript; los hallazgos salen en la pestaña Security.
- **Dependabot**: PR semanales hacia `test` con dependencias y acciones al día.

`tests/test_seguridad.py` cuida lo de producción detrás del proxy de Railway: el límite de intentos cuenta por la IP real del cliente (ProxyFix) y no se burla con un `X-Forwarded-For` inventado, HTTP redirige a HTTPS con HSTS, la API no abre CORS a otros orígenes, `/health` responde sin sesión, y ni las plantillas (`|safe`, `Markup`) ni el JS de `static/` meten HTML sin escapar. El prototipo de la raíz usa `innerHTML`, pero cada dato del usuario pasa por `esc()` (revisado en T10; el único que faltaba, el teléfono del enlace de WhatsApp en `citas.html`, ahora se limpia a solo dígitos); al pasarlo a plantillas (T7/T9) queda cubierto por esa prueba.
