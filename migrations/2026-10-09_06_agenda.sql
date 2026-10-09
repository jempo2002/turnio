-- ============================================================
-- Migracion: agenda robusta (T6)
-- Fecha: 2026-10-09
-- ============================================================
--
-- Las citas y los bloqueos ya viven en `citas` (migracion 02). Esta migracion
-- solo agrega lo que piden cancelar y reprogramar:
--
-- 1) motivo_cancelacion: por que se cancelo (lo escribe quien cancela).
-- 2) fecha_actualizacion: ultima vez que se movio, cancelo o marco la cita.
--
-- Reglas que la app aplica (app/services/agenda_service.py), porque MySQL no
-- tiene exclusion constraints ni indices parciales:
-- - Una cita ocupa de `inicio` a `fin` (inicio + duracion del servicio): dos
--   citas vigentes del mismo profesional no se cruzan. Se valida dentro de la
--   transaccion con SELECT ... FOR UPDATE sobre la sede y el profesional.
-- - Bloqueo = fila con estado 'bloqueada'. Con id_profesional NULL bloquea a
--   toda la sede (festivo, capacitacion); con profesional, solo su agenda.
-- - `inicio` y `fin` van en hora de Colombia (la sesion MySQL usa -05:00).
--
-- Se puede correr varias veces (1060 = la columna ya existe).

SET NAMES utf8mb4;

ALTER TABLE `citas` ADD COLUMN `motivo_cancelacion` varchar(255) DEFAULT NULL AFTER `nota`;
ALTER TABLE `citas` ADD COLUMN `fecha_actualizacion` timestamp NULL DEFAULT NULL ON UPDATE current_timestamp() AFTER `fecha_creacion`;
