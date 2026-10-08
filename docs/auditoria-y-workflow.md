# Turnio: auditoría general y workflow hasta deploy en Railway

Fecha: 8 de octubre de 2026 · Repo: [jempo2002/turnio](https://github.com/jempo2002/turnio) · Rama de trabajo: `test`

## 1. Resumen ejecutivo

Turnio hoy es un **prototipo funcional de frontend** (agenda, caja, inventario, configuración, landing y reserva pública) que guarda todo en `localStorage`, más un **backend Express + PostgreSQL bien encaminado pero incompleto** que todavía no está conectado al frontend.

Hallazgos que cambian el plan:

1. **El repositorio está atrasado respecto a tu carpeta local `agenda`.** En GitHub (`main`, 2 commits) no están `backend/` ni `reservar.html`, y 8 de los 10 archivos del frontend son versiones viejas (por ejemplo, la landing todavía dice "barbería" y no "negocios con cita"). Lo primero es subir la carpeta local a `test`.
2. **El backend asume Supabase** (`auth.jwt()` en las políticas RLS y JWT de Supabase Auth). Si la base vive en Railway Postgres, `schema.sql` falla al crear las políticas y no hay quién emita los tokens. Hay que decidir entre Supabase o Railway (abajo va mi recomendación).
3. **No existe login real ni registro de negocios.** `login.html` es una demo que elige el profesional según el correo; no hay endpoint de login, ni bcrypt, ni alta de negocio.
4. **El backend solo cubre citas y reservas públicas.** Faltan servicios, inventario, caja, configuración y profesionales (CRUD).

Lo bueno: arquitectura limpia (`routes → controllers → services → db`), consultas 100 % parametrizadas, `tenant_id` sacado del JWT y nunca del body, cobro atómico en transacción, candado de concurrencia para reservas, 6 tests de backend y 36 de cálculo pasando, `npm audit` sin vulnerabilidades.

## 2. Estado actual

| Área | Estado | Detalle |
|---|---|---|
| Frontend | Prototipo completo | 7 páginas HTML + Tailwind por CDN, JS vanilla, mobile-first, `datos.js` simula la base en `localStorage` |
| Backend | 30 % | Express 4, helmet, cors, pg, jsonwebtoken. Endpoints: citas del día, agendar, cobrar, cambiar estado, staff, 3 rutas públicas |
| Base de datos | Esquema listo | `schema.sql` (tenants, users, services, appointments, inventory, transactions) + `002_public_booking.sql` + `seed.sql` |
| Tests | Bien | `node --test` (6 pasan, con base simulada) y `test-calculo.js` (36 pasan) |
| Repo | Atrasado | Sin `backend/`, sin `.gitignore`, sin README, sin `.env.example`, sin CI |
| Deploy | Nada | Sin config de Railway, sin healthcheck, sin servir el frontend desde el backend |

## 3. Hallazgos por área

### Seguridad
- **Rate limit roto detrás del proxy de Railway.** `rateLimit.js` usa `req.ip` y no hay `app.set('trust proxy', 1)`: en Railway todos los clientes comparten la IP del proxy, así que el límite de 10 reservas/minuto sería **global para todo el país**. Corregir antes del deploy.
- **CORS abierto por defecto** (`CORS_ORIGIN || '*'`). Si el frontend se sirve desde el mismo dominio, no hace falta CORS.
- **RLS no protege nada con la conexión actual.** El backend se conecta como dueño/service role, que se salta RLS. El "doble candado" real es el filtro `tenant_id = $1` (que sí está bien). El comentario cita `src/middlewares/tenant.js`, que no existe.
- **Contraseñas**: no hay hashing implementado; el seed usa un hash falso.
- **XSS**: hay 17 `innerHTML`. `citas.html` usa `esc()`, pero cuando el nombre del cliente venga de la reserva pública (texto de cualquier persona en internet) hay que verificar que todas las vistas escapen.
- **CSP**: helmet aplica una CSP por defecto que bloqueará el Tailwind de CDN y los scripts inline cuando el backend sirva el HTML.

### Lógica de negocio
- **Zona horaria.** `listByDay` usa `scheduled_at::date` en UTC y el día por defecto sale de `toISOString()`. En Colombia (UTC−5) una cita a las 7:30 p. m. aparece en el día siguiente, y después de las 7 p. m. "hoy" ya es mañana. Hay que usar `America/Bogota`.
- **Duraciones.** El candado compara solo la hora exacta de inicio; un servicio de 60 min a las 10:00 no impide otro a las 10:30. Para salones, uñas o pestañas (servicios de 2 h) esto importa: cambiar a `exclusion constraint` con `tstzrange`.
- **Horario del negocio** (días, apertura, almuerzo) solo existe en el frontend demo.
- **Vertical**: el código y los textos dicen "barbero", "pagoBarbero", "Barbería El Cuartel" (fijo en el mensaje de WhatsApp de `citas.html`). Para salones, uñas y estética hay que generalizar a "profesional" y usar el nombre del negocio.

### Calidad y mantenimiento
- `schema.sql` no es idempotente ni versionado: falta un sistema de migraciones.
- Tailwind por CDN no es para producción (pesado en móvil, parpadeo de estilos, choca con la CSP).
- Sin README, `.env.example` ni `.gitignore` (riesgo de subir `node_modules` o `.env`).
- Sin CI que corra los tests en cada PR.

### Gaps contra el objetivo del producto
| Objetivo | ¿Cubierto? |
|---|---|
| Reemplazar la libreta (agenda por profesional) | Sí en la demo, falta persistencia real |
| Reservas 24/7 del cliente final | Demo sí; API lista, falta conectarla |
| Evitar inasistencias | Solo botón manual de WhatsApp; faltan recordatorios automáticos |
| Control del dinero (caja, comisiones) | Demo sí; API solo registra cobros de citas |
| Inventario y venta de productos | Solo demo |
| Multi-negocio (SaaS) | Esquema sí; falta registro/onboarding de negocios |
| Cobro de suscripción ($49.000 COP/mes) | No existe |

## 4. Decisión de infraestructura (recomendada)

**Recomiendo Railway para todo: un servicio Node que sirve la API y el frontend, más Railway Postgres, con autenticación propia (bcrypt + JWT firmado por el backend).**

- Un solo proveedor, una sola factura y un solo lugar para variables de entorno y backups.
- El backend ya filtra por `tenant_id` en cada query; las políticas RLS se reescriben con `current_setting('app.tenant_id')` en vez de `auth.jwt()`, o se dejan para después.
- Alternativa: mantener Supabase para base y auth, y Railway solo para el Node. Es válida, pero suma un segundo proveedor y obliga a usar el SDK de Supabase Auth en el frontend.

Esta es la primera decisión que te voy a pedir confirmar (tarea 2).

### Actualización: lo que ya existe en jemPOS

Regla para todos los hilos: **antes de crear algo, revisar jemPOS (`jempo2002/jemPOS`) y jemPOS Chef (`jempo2002/jemPOS-Chef`); si funciona y se adapta bien, se toma de allí y no se vuelve a crear.** La regla también está en `CLAUDE.md` del repo, que cada hilo lee al empezar.

Al revisarlos apareció algo que cambia la decisión de infraestructura: jemPOS y jemPOS Chef son **Flask + MySQL + Redis en Railway** y ya resuelven buena parte de lo que a Turnio le falta:

| Lo que falta en Turnio | Ya está en jemPOS / Chef |
|---|---|
| Login, recuperar contraseña, sesiones seguras | `auth_service.py`, `security.py` (Talisman, ProxyFix, Redis), plantillas `auth/` |
| Planes y suscripción ($49.000 / $69.000 / $99.000), modo solo lectura al vencer | `plan_service.py` |
| Alta de negocios, cobros de suscripción | Panel Master (`master_service.py`) |
| Multi-sede y roles | `sede_service.py`, `usuario_service.py` |
| Caja, pago mixto, comisiones | `caja_service.py`, `comisiones_service.py`, `pago-mixto.js` |
| Inventario con lector de códigos | `inventory_service.py`, `barcode-scanner.js` |
| Migraciones, CI de pruebas, deploy | `scripts/run_migration.py`, pytest, `Procfile`, `DEPLOY.md` |
| Páginas legales para Colombia, SEO | `routes/legal.py`, `routes/seo.py` |

El backend Node actual de Turnio cubre cerca del 30 % y casi todo lo demás ya existe en Flask. Por eso la recomendación pasa a ser: **construir el backend de Turnio sobre la base de jemPOS Chef (Flask + MySQL en Railway)**, igual que Chef se construyó sobre jemPOS, y portar desde el backend Node las piezas propias que sí valen: el candado de reservas por profesional, el cobro atómico y la página pública de reservas. El frontend actual de Turnio se conserva como diseño de las plantillas. Esta decisión reemplaza la de la sección 4. **Confirmada por jempo el 8 de octubre de 2026: el backend de Turnio se construye sobre la base Flask de jemPOS Chef.**

## 5. Workflow de trabajo

Igual que en jemPOS-chef: **un hilo por tarea**.

```
main   ← producción (Railway "production"). Solo se toca con tu confirmación.
 └─ test   ← integración (Railway "staging"). Rama base de todo el trabajo.
     └─ claude/<tarea>   ← una rama por hilo, PR hacia test.
```

1. Cada tarea abre un hilo; el hilo crea su rama desde `test` y abre un PR hacia `test`.
2. El PR debe pasar CI (cuando exista, tarea 10) antes de mergear a `test`.
3. Railway despliega `test` automáticamente en staging para que pruebes en el celular.
4. Cuando un bloque esté probado, se abre un PR `test → main` y **solo se mergea cuando tú lo confirmes**.

## 6. Roadmap en tareas (cada una puede ser un hilo)

### Fase 0: Ordenar la base
**T1. Sincronizar la carpeta local con el repo.** Subir `agenda/` completa (incluido `backend/` y `reservar.html`) a `test`, con estructura `frontend/` + `backend/`, `.gitignore`, `.env.example` y README con cómo correr todo.
*Listo cuando:* `test` tiene exactamente lo que hay en tu carpeta y ambos tests pasan.

**T2. Base del backend desde jemPOS Chef + migraciones.** Si confirmas la base Flask (recomendado, ver actualización de la sección 4): copiar de jemPOS Chef la app Flask (auth, seguridad, planes, Master, sedes, migraciones, Procfile) y adaptar el esquema de Turnio a MySQL. Si prefieres seguir en Node: Railway Postgres, quitar `auth.jwt()` de `schema.sql` y migraciones con `npm run migrate`. En ambos casos, las tareas T3 a T11 toman de jemPOS lo que ya exista.
*Listo cuando:* las migraciones corren de cero contra un Postgres real y el seed carga.

### Fase 1: Backend completo
**T3. Autenticación y registro de negocios.** `POST /auth/register` (crea negocio + dueño, genera slug), `POST /auth/login` (bcrypt + JWT propio), invitar profesionales, roles owner/admin/staff.
*Listo cuando:* un negocio nuevo se registra, entra y solo ve sus datos (test de aislamiento entre dos tenants).

**T4. API de catálogo y configuración.** CRUD de servicios, profesionales (foto, comisión), horario del negocio y datos del local.

**T5. API de caja e inventario.** Productos por código de barras, venta rápida, gastos, cierre de caja por día, reparto de comisiones por profesional.

**T6. Agenda robusta.** Zona horaria `America/Bogota`, duración real de cada servicio (exclusion constraint), horarios y bloqueos (almuerzo), vista por día y semana, cancelación y reprogramación.

### Fase 2: Frontend conectado
**T7. Conectar el panel a la API.** Reemplazar el `localStorage` de `datos.js` por un cliente API, sesión con JWT, estados de carga y error, sin perder la experiencia actual.

**T8. Página pública de reservas por negocio.** `turnio.app/r/<slug>` con servicios, profesional, hora disponible y confirmación por WhatsApp; protección anti-spam.

**T9. Multi-vertical y producción del frontend.** "Barbero" → "profesional", textos y nombre del negocio dinámicos, Tailwind compilado (sin CDN), CSP compatible, PWA instalable (manifest + íconos), revisión de rendimiento en celular de gama media.

### Fase 3: Calidad y deploy
**T10. Seguridad y CI.** `trust proxy`, CORS cerrado, rate limit correcto, `/health`, auditoría de `innerHTML`, GitHub Actions corriendo tests contra un Postgres real en cada PR.

**T11. Deploy en Railway.** Un servicio Node (API + estáticos), Postgres de Railway, variables de entorno (`DATABASE_URL`, `JWT_SECRET`, `NODE_ENV`), entornos **staging (rama `test`)** y **production (rama `main`)**, migraciones al desplegar, dominio propio y backups.
*Listo cuando:* staging funciona de punta a punta en tu celular y tú confirmas el primer merge `test → main`.

### Fase 4: Después del MVP (para crecer en el Valle del Cauca)
- **T12. Recordatorios automáticos por WhatsApp** (WhatsApp Cloud API) 24 h y 2 h antes, para bajar inasistencias.
- **T13. Cobro de suscripción** con Wompi o Mercado Pago (planes, prueba gratis, bloqueo por mora).
- **T14. Reportes**: ingresos por semana/mes, servicios más vendidos, clientes frecuentes, exportar a Excel.
- **T15. Multi-sede** para negocios que se expanden.

## 7. Orden sugerido y paralelismo

```
T1 → T2 → T3 → (T4 · T5 · T6 en paralelo) → T7 → (T8 · T9 en paralelo) → T10 → T11 → Fase 4
```

T10 (CI) se puede adelantar justo después de T2 para que todo lo siguiente ya se pruebe automáticamente.

## 8. Verificado en esta auditoría
- `node test-calculo.js` → `OK — 36 comprobaciones de cálculo` (carpeta local).
- `npm test` en `backend/` → 6 de 6 pasan; `npm audit --omit=dev` → 0 vulnerabilidades.
- Comparación archivo por archivo entre `main` y la carpeta local: solo `inventario.html` y `nav.js` son iguales.
- Rama `test` creada desde `main` (commit `0e3601e`) y subida a GitHub. No se tocó `main`.
