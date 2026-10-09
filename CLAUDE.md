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
- Cambios de la base: un archivo nuevo en `migrations/` (nunca editar uno aplicado) y `python scripts/migrar.py`.

## Pruebas
- Backend: `pytest` (necesita MariaDB/MySQL; ver README)
- Fórmulas del panel y avisos: `node test-calculo.js`

## Panel
- Pantallas en `templates/panel/` y su JS en `static/js/panel/` (sin JS ni estilos inline: la CSP los bloquea). Al cambiar clases de Tailwind: `cd frontend && npm run css` y subir `static/css/panel.css` y `static/css/landing.css`.
- Textos que dependen del tipo de negocio (barbero, estilista, manicurista...): `app/services/vertical_service.py`, en plantillas como `negocio.voc` y en JS como `T.voc`.
- Avisos, errores, confirmaciones y guías: siguen `docs/ux-avisos.md` y usan la utilidad compartida (`Turnio.aviso`, `T.fallo`, `T.confirmar`, `T.guia` en `static/js/panel/turnio.js`, estilos en `static/css/avisos.css`). Nada de `alert()`, `confirm()` ni mensajes como "inválido" o "error 500".
- Iconos de la app: `python scripts/generar_iconos.py` (necesita Pillow, que no va en requirements).
