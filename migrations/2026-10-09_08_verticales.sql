-- ============================================================
-- Migracion: tipo de negocio "independiente" (T9)
-- Fecha: 2026-10-09
-- ============================================================
--
-- El profesional que trabaja solo (a domicilio o en su casa) tiene su propio
-- tipo: el plan Basico esta pensado para el y la app le habla en singular.
-- Los textos, servicios y horario de cada tipo viven en
-- app/services/vertical_service.py; aqui solo se amplia el enum.
--
-- MODIFY con la misma lista mas el valor nuevo: se puede correr varias veces.

SET NAMES utf8mb4;

ALTER TABLE `tiendas`
  MODIFY `tipo_negocio` enum('barberia','peluqueria','unas','cejas_pestanas','estetica','independiente','otro')
  NOT NULL DEFAULT 'otro';
