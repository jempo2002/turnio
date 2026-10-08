# Turnio backend — seguridad y aislamiento multi-tenant

## Aislamiento por tenant (doble candado)
1. **RLS en Postgres** (`db/schema.sql`): cada tabla operativa filtra por `tenant_id` leído del JWT (`app_metadata.tenant_id`). Ni con acceso directo a la DB se cruzan datos entre negocios.
2. **Filtro en cada query del backend**: todo `select/update/delete` lleva `tenant_id = $1` tomado de `req.auth.tenantId` (middleware `auth.js`), nunca de `body`/`query` del cliente. Así un usuario no puede pedir citas de otro local cambiando un parámetro.

## Inyección SQL
Todas las queries usan parámetros posicionales (`$1, $2...`) vía `pg`. Nunca se concatena input de usuario en el string SQL.

## Datos sensibles
`users.password_hash` nunca se incluye en un `select *`; los services que exponen usuarios listan columnas explícitas (ver `users.service.js`). Las contraseñas se guardan hasheadas (bcrypt/argon2 en el paso de registro, fuera del alcance de este bootstrap).

## Roles y permisos
`requireRole(...)` en `middlewares/auth.js` restringe rutas sensibles (ej. borrar servicios, ver caja) a `owner`/`admin`. El rol viene firmado en el JWT, no es editable por el cliente.

## Quién cobra una cita
`POST /api/appointments/:id/complete` toma el trabajador de `req.auth.userId` (JWT verificado, HS256). Cualquier `staffId` o `tenantId` en el body se ignora. Cita, movimientos de caja y comisión se escriben en una sola transacción SQL. `PATCH /:id/status` no acepta `completed`, para que no exista un camino sin caja.

## Rutas públicas (`/api/public/:slug`)
Sin autenticación, para la página de reservas. Devuelven solo: nombre del negocio, servicios (nombre, duración, precio) y por profesional `id`, `name`, `photo_url`, `available`. Nunca correo, rol, comisiones ni caja. Al reservar, el precio se copia del servicio en la base de datos y el índice único `uq_appointments_staff_slot` (`db/002_public_booking.sql`) impide que dos clientes tomen al mismo profesional a la misma hora (respuesta 409). Límite de solicitudes por IP en memoria.

## Integridad referencial
FKs con `on delete cascade` en `tenant_id` (si se borra un tenant, se borra toda su data) y `on delete set null` en relaciones opcionales (`staff_id`, `service_id`) para no dejar filas huérfanas bloqueando borrados.

## Checklist (Fase 3)
- [x] Estructura modular escalable: `routes -> controllers -> services -> db`, una carpeta por responsabilidad.
- [x] `tenant_id` en appointments, services, inventory, transactions, users.
- [x] FKs correctas (tenants -> users/services -> appointments/inventory -> transactions), sin orfandad.
- [x] Queries parametrizadas + RLS documentadas arriba.
