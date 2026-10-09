# Turnio: reglas para trabajar en este repo

Turnio es una agenda y caja mobile-first para negocios con cita (barberías, salones, uñas, cejas y pestañas, estética) en el Valle del Cauca.

## Base: jemPOS
- Antes de crear algo, revisa si ya existe en **jemPOS** (`jempo2002/jemPOS`) o **jemPOS Chef** (`jempo2002/jemPOS-Chef`): login, recuperación de contraseña, sesiones, seguridad, planes y suscripción, panel Master, sedes, caja, inventario con lector de códigos, pago mixto, comisiones, páginas legales, SEO y despliegue en Railway (`DEPLOY.md` de jemPOS).
- Si funciona y se adapta bien a Turnio, tómalo de allí y adáptalo. No lo vuelvas a crear.
- jemPOS y jemPOS Chef no se modifican desde este proyecto: solo se copian piezas.

## Ramas
- `main`: producción. Nada llega a `main` sin la confirmación explícita de jempo.
- `test`: integración. Cada tarea sale de `test` en su propia rama y vuelve con un PR hacia `test`.

## Roadmap
La auditoría y las tareas (T1 a T15) están en `docs/auditoria-y-workflow.md`.

## Backend
- El backend es la app Flask de la raíz (`app/`), construida sobre jemPOS Chef. Se conservan sus nombres (`tiendas`, `id_tienda`) para que las piezas de jemPOS se porten sin renombrar.
- `backend/` (Node) ya no se desarrolla: solo se consulta para portar sus piezas y se borra al terminar T8.
- Cambios de la base: un archivo nuevo en `migrations/` (nunca editar uno aplicado) y `python scripts/migrar.py`.

## Pruebas
- Backend: `pytest` (necesita MariaDB/MySQL; ver README)
- Prototipo del frontend: `node test-calculo.js`
