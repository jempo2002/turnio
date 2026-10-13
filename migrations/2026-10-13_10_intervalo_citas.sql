-- Cada negocio decide cada cuanto ofrece una hora para agendar (jempo,
-- 2026-10-13): cada 30 min (2 citas por hora como maximo) o cada 60 min.
-- Antes era cada 15 min para todos. Por defecto, cada 30 min.
ALTER TABLE `tiendas`
  ADD COLUMN `intervalo_citas_min` smallint(5) UNSIGNED NOT NULL DEFAULT 30 AFTER `telefono`;
