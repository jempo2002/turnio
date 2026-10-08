-- ============================================================
-- Migracion: base de negocios, sedes y usuarios
-- Fecha: 2026-10-08
-- Motor: MariaDB 10.6+ y MySQL 8
-- ============================================================
--
-- Tomado de jemPOS Chef (db/schema.sql + migrations/2026-10-07_sedes_planes_
-- roles.sql) sin lo de restaurante ni lo de jemPOS que Turnio no usa (Alegra,
-- promotoras, cartera). Los nombres se conservan (`tiendas`, `id_tienda`) para
-- que las piezas de jemPOS que se porten despues (caja, inventario,
-- comisiones) encajen sin renombrar.
--
-- 1) tiendas: cada negocio cliente (multi-tenant por id_tienda). Lo nuevo de
--    Turnio: `slug` (la pagina publica de reservas, turnio.app/r/<slug>) y
--    `tipo_negocio` (textos por vertical).
-- 2) usuarios: Master (sin negocio), Admin (dueno o encargado), Recepcion y
--    Profesional (quien atiende; las citas y comisiones van a su nombre).
-- 3) sedes: cada local fisico. Todo negocio tiene al menos una (la
--    principal). Soft delete con `nombre_vivo` para poder reusar el nombre.
-- 4) Triggers de respaldo: la base rechaza una sede activa por encima de 4
--    (MAX_SEDES de app/services/plan_service.py) si algo escribe directo en
--    la base. El tope de cada plan lo pone la app: hoy ningun plan de Turnio
--    trae multisede (llega con T15), asi que la app deja una sola. En Chef
--    el trigger tambien miraba el plan; aqui no, para que T15 solo tenga que
--    cambiar plan_service.py.
--
-- Se puede correr varias veces.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `tiendas` (
  `id_tienda` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `nombre_negocio` varchar(150) NOT NULL,
  `slug` varchar(80) NOT NULL,
  `tipo_negocio` enum('barberia','peluqueria','unas','cejas_pestanas','estetica','otro') NOT NULL DEFAULT 'otro',
  `nit` varchar(50) DEFAULT NULL,
  `telefono` varchar(20) DEFAULT NULL,
  `estado` enum('Activo','Suspendido','Eliminado') NOT NULL DEFAULT 'Activo',
  `estado_suscripcion` varchar(20) NOT NULL DEFAULT 'activa',
  `plan_id` varchar(20) DEFAULT NULL,
  `trial_ends_at` date DEFAULT NULL,
  `fecha_inicio_suscripcion` date DEFAULT NULL,
  `fecha_fin_suscripcion` date DEFAULT NULL,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_tienda`),
  UNIQUE KEY `uq_tiendas_slug` (`slug`),
  UNIQUE KEY `uq_tiendas_nit` (`nit`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sedes` (
  `id_sede` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(120) NOT NULL,
  `direccion` varchar(200) DEFAULT NULL,
  `telefono` varchar(20) DEFAULT NULL,
  `es_principal` tinyint(1) NOT NULL DEFAULT 0,
  `costo_montaje` decimal(12,0) NOT NULL DEFAULT 0,
  `montaje_pagado` tinyint(1) NOT NULL DEFAULT 0,
  `fecha_pago_montaje` datetime DEFAULT NULL,
  `estado` enum('Activa','Eliminada') NOT NULL DEFAULT 'Activa',
  `nombre_vivo` varchar(120) GENERATED ALWAYS AS (IF(`estado` = 'Activa', `nombre`, NULL)) STORED,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  `fecha_eliminacion` datetime DEFAULT NULL,
  PRIMARY KEY (`id_sede`),
  UNIQUE KEY `uq_sedes_nombre_vivo` (`id_tienda`, `nombre_vivo`),
  KEY `idx_sedes_tienda_estado` (`id_tienda`, `estado`),
  CONSTRAINT `fk_sedes_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- id_tienda NULL: el Master no tiene negocio. id_sede NULL: todas las sedes
-- (lo normal en un Admin); Recepcion y Profesional siempre tienen una.
CREATE TABLE IF NOT EXISTS `usuarios` (
  `id_usuario` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED DEFAULT NULL,
  `id_sede` bigint(20) UNSIGNED DEFAULT NULL,
  `nombre_completo` varchar(150) NOT NULL,
  `correo` varchar(191) NOT NULL,
  `clave_hash` varchar(255) NOT NULL,
  `rol` enum('Master','Admin','Recepcion','Profesional') NOT NULL DEFAULT 'Profesional',
  `cc` varchar(50) DEFAULT NULL,
  `telefono` varchar(20) DEFAULT NULL,
  `foto_url` varchar(500) DEFAULT NULL,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_usuario`),
  UNIQUE KEY `uq_usuarios_correo` (`correo`),
  UNIQUE KEY `uq_usuarios_cc` (`cc`),
  KEY `idx_usuarios_tienda` (`id_tienda`),
  KEY `idx_usuarios_sede` (`id_sede`),
  CONSTRAINT `fk_usuarios_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_usuarios_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TRIGGER IF EXISTS `bi_sedes_limite`;
DROP TRIGGER IF EXISTS `bu_sedes_limite`;

DELIMITER $$
CREATE TRIGGER `bi_sedes_limite` BEFORE INSERT ON `sedes` FOR EACH ROW
BEGIN
  DECLARE v_activas int;
  IF NEW.`estado` = 'Activa' THEN
    SELECT COUNT(*) INTO v_activas FROM `sedes` WHERE `id_tienda` = NEW.`id_tienda` AND `estado` = 'Activa';
    IF v_activas >= 4 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Limite de sedes alcanzado';
    END IF;
  END IF;
END$$

CREATE TRIGGER `bu_sedes_limite` BEFORE UPDATE ON `sedes` FOR EACH ROW
BEGIN
  DECLARE v_activas int;
  IF NEW.`estado` = 'Activa' AND (OLD.`estado` <> 'Activa' OR NEW.`id_tienda` <> OLD.`id_tienda`) THEN
    SELECT COUNT(*) INTO v_activas FROM `sedes`
      WHERE `id_tienda` = NEW.`id_tienda` AND `estado` = 'Activa' AND `id_sede` <> NEW.`id_sede`;
    IF v_activas >= 4 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Limite de sedes alcanzado';
    END IF;
  END IF;
END$$
DELIMITER ;
