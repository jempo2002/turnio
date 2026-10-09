-- ============================================================
-- Migracion: catalogo, profesionales y datos del local (T4)
-- Fecha: 2026-10-09
-- ============================================================
--
-- 1) imagenes: logo del negocio y fotos de los profesionales, guardadas en la
--    base (el disco de Railway se borra en cada despliegue). Solo PNG, JPEG y
--    WebP de hasta 2 MB (app/services/imagen_service.py). Se sirven publicas
--    en /img/<id> porque salen en la pagina de reservas.
-- 2) tiendas.id_logo y usuarios.id_foto apuntan a imagenes. Sin llave
--    foranea a proposito: imagenes ya cuelga de tiendas, y la app borra la
--    imagen vieja al cambiarla.
-- 3) usuarios.atiende: la persona tiene agenda y recibe citas. Todo
--    Profesional atiende; un Admin o Recepcion tambien puede (el dueno que
--    corta). reserva_online: aparece en la pagina publica de reservas (T8).
-- 4) Que servicios hace cada profesional: atiende_todos = 1 (lo normal) hace
--    todo el catalogo; con 0, solo los de profesional_servicios.
--    profesional_servicios.pago_profesional: lo que gana esa persona por ese
--    servicio; NULL = el pago_profesional del servicio.
-- 5) Toda sede sin horario recibe el de fabrica: lunes a sabado de 8 a. m. a
--    7 p. m., domingo cerrado (dia 0 = lunes ... 6 = domingo).
--
-- Se puede correr varias veces (1060 = la columna ya existe).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `imagenes` (
  `id_imagen` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `tipo` varchar(20) NOT NULL,
  `datos` mediumblob NOT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_imagen`),
  KEY `idx_imagenes_tienda` (`id_tienda`),
  CONSTRAINT `fk_imagenes_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `tiendas` ADD COLUMN `id_logo` bigint(20) UNSIGNED DEFAULT NULL AFTER `telefono`;

ALTER TABLE `usuarios` ADD COLUMN `atiende` tinyint(1) NOT NULL DEFAULT 0 AFTER `rol`;
ALTER TABLE `usuarios` ADD COLUMN `reserva_online` tinyint(1) NOT NULL DEFAULT 1 AFTER `atiende`;
ALTER TABLE `usuarios` ADD COLUMN `atiende_todos` tinyint(1) NOT NULL DEFAULT 1 AFTER `reserva_online`;
ALTER TABLE `usuarios` ADD COLUMN `id_foto` bigint(20) UNSIGNED DEFAULT NULL AFTER `foto_url`;

UPDATE `usuarios` SET `atiende` = 1 WHERE `rol` = 'Profesional';

CREATE TABLE IF NOT EXISTS `profesional_servicios` (
  `id_usuario` bigint(20) UNSIGNED NOT NULL,
  `id_servicio` bigint(20) UNSIGNED NOT NULL,
  `pago_profesional` decimal(12,0) DEFAULT NULL,
  PRIMARY KEY (`id_usuario`, `id_servicio`),
  KEY `idx_profesional_servicios_servicio` (`id_servicio`),
  CONSTRAINT `chk_profesional_servicios_pago` CHECK (`pago_profesional` IS NULL OR `pago_profesional` >= 0),
  CONSTRAINT `fk_profesional_servicios_usuario` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_profesional_servicios_servicio` FOREIGN KEY (`id_servicio`) REFERENCES `servicios` (`id_servicio`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO `horarios_sede` (`id_sede`, `dia`, `abierto`, `abre`, `cierra`)
SELECT s.`id_sede`, d.`dia`, d.`dia` < 6, '08:00:00', '19:00:00'
FROM `sedes` s
CROSS JOIN (SELECT 0 AS dia UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
            UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6) d;
