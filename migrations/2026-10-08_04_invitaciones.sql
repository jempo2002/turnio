-- ============================================================
-- Migracion: invitaciones al equipo (T3)
-- Fecha: 2026-10-08
-- ============================================================
--
-- El Admin puede sumar a alguien sin ponerle contrasena: el usuario queda con
-- una clave aleatoria que nadie conoce y `invitacion_pendiente = 1`, y recibe
-- un enlace (por WhatsApp o correo) para elegir la suya. Al usarlo la marca
-- vuelve a 0. Solo mientras esta en 1 el Admin puede generar un enlace nuevo:
-- asi no puede tomar la cuenta de alguien que ya entro.
--
-- Se puede correr varias veces (1060 = la columna ya existe).

SET NAMES utf8mb4;

ALTER TABLE `usuarios`
  ADD COLUMN `invitacion_pendiente` tinyint(1) NOT NULL DEFAULT 0 AFTER `estado_activo`;
