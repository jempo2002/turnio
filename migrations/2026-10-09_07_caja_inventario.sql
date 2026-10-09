-- ============================================================
-- Migracion: caja e inventario (T5)
-- Fecha: 2026-10-09
-- ============================================================
--
-- Tomado de jemPOS Chef (stock por sede, kardex inmutable, caja con arqueo)
-- y adaptado a la caja del dia del prototipo (caja.html, citas.html).
--
-- 1) stock_sedes: el stock es de cada sede (el Multisede vende y traslada
--    por sede). productos queda como el catalogo del negocio. El stock que
--    tenia productos.stock pasa a la sede principal y la columna se borra.
-- 2) productos.codigo_barras es opcional (el prototipo lo deja vacio) y
--    stock_minimo es el umbral de la alerta de stock bajo (Pro).
-- 3) movimientos_inventario: el kardex por sede. Nunca se edita ni se borra
--    (triggers): toda correccion es un movimiento nuevo.
-- 4) ventas + venta_productos: la venta rapida. Cada venta entra a caja como
--    uno o dos movimientos (pago mixto) con su id_venta. Anular la marca
--    'anulada', devuelve el stock y saca sus movimientos de caja.
-- 5) liquidaciones: el pago de comisiones a un profesional (Pro). Los cobros
--    que cubre quedan con su id_liquidacion (no se pagan dos veces) y el
--    pago sale de caja como un movimiento 'salida' con el mismo id.
-- 6) cajas_dia: una fila por sede y dia. Guarda la base (efectivo con el que
--    arranca el cajon) y, al cerrar, el arqueo: esperado, contado y
--    diferencia. Un dia cerrado no recibe movimientos hasta que el Admin lo
--    reabra.
--
-- Se puede correr varias veces.

SET NAMES utf8mb4;

-- 1) stock por sede ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS `stock_sedes` (
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `stock` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id_sede`, `id_producto`),
  KEY `idx_stock_sedes_producto` (`id_producto`),
  CONSTRAINT `chk_stock_sedes_stock` CHECK (`stock` >= 0),
  CONSTRAINT `fk_stock_sedes_sede` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_stock_sedes_producto` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @s := IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos' AND COLUMN_NAME = 'stock'), 'INSERT IGNORE INTO `stock_sedes` (`id_sede`, `id_producto`, `stock`) SELECT s.`id_sede`, p.`id_producto`, p.`stock` FROM `productos` p JOIN `sedes` s ON s.`id_tienda` = p.`id_tienda` AND s.`es_principal` = 1 WHERE p.`stock` > 0', 'DO 0');
PREPARE st FROM @s;
EXECUTE st;
DEALLOCATE PREPARE st;

ALTER TABLE `productos` DROP CONSTRAINT `chk_productos_valores`;
ALTER TABLE `productos` DROP COLUMN `stock`;
ALTER TABLE `productos` ADD CONSTRAINT `chk_productos_montos` CHECK (`vendidos` >= 0 AND `costo` >= 0 AND `precio` >= 0);

-- 2) codigo opcional y umbral de stock bajo ---------------------------------
ALTER TABLE `productos` MODIFY `codigo_barras` varchar(64) DEFAULT NULL;
ALTER TABLE `productos` ADD COLUMN `stock_minimo` int(11) NOT NULL DEFAULT 0 AFTER `precio`;

-- 4) ventas (antes del kardex, que las referencia) ---------------------------
CREATE TABLE IF NOT EXISTS `ventas` (
  `id_venta` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `total` decimal(12,0) NOT NULL,
  `estado` enum('pagada','anulada') NOT NULL DEFAULT 'pagada',
  `id_usuario_registra` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha` datetime NOT NULL,
  `id_usuario_anula` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha_anulacion` datetime DEFAULT NULL,
  PRIMARY KEY (`id_venta`),
  KEY `idx_ventas_dia` (`id_tienda`, `id_sede`, `fecha`),
  CONSTRAINT `chk_ventas_total` CHECK (`total` > 0),
  CONSTRAINT `fk_ventas_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_ventas_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON UPDATE CASCADE,
  CONSTRAINT `fk_ventas_registra` FOREIGN KEY (`id_usuario_registra`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ventas_anula` FOREIGN KEY (`id_usuario_anula`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `venta_productos` (
  `id_venta` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `cantidad` int(11) NOT NULL,
  `precio` decimal(12,0) NOT NULL,
  `costo` decimal(12,0) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id_venta`, `id_producto`),
  KEY `idx_venta_productos_producto` (`id_producto`),
  CONSTRAINT `chk_venta_productos_valores` CHECK (`cantidad` > 0 AND `precio` >= 0 AND `costo` >= 0),
  CONSTRAINT `fk_venta_productos_venta` FOREIGN KEY (`id_venta`) REFERENCES `ventas` (`id_venta`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_venta_productos_producto` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3) kardex por sede ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `movimientos_inventario` (
  `id_movimiento` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `id_producto` bigint(20) UNSIGNED NOT NULL,
  `id_venta` bigint(20) UNSIGNED DEFAULT NULL,
  `id_usuario` bigint(20) UNSIGNED DEFAULT NULL,
  `tipo` enum('Entrada','Salida','Ajuste','Venta','Anulacion','Traslado') NOT NULL,
  `cantidad` int(11) NOT NULL,
  `stock_anterior` int(11) NOT NULL,
  `stock_posterior` int(11) NOT NULL,
  `motivo` varchar(255) DEFAULT NULL,
  `fecha` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_movimiento`),
  KEY `idx_kardex_producto` (`id_producto`, `id_sede`, `fecha`),
  KEY `idx_kardex_sede_fecha` (`id_sede`, `fecha`),
  KEY `idx_kardex_venta` (`id_venta`),
  CONSTRAINT `chk_kardex_valores` CHECK (`cantidad` >= 0 AND `stock_anterior` >= 0 AND `stock_posterior` >= 0),
  CONSTRAINT `fk_kardex_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kardex_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kardex_productos` FOREIGN KEY (`id_producto`) REFERENCES `productos` (`id_producto`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kardex_ventas` FOREIGN KEY (`id_venta`) REFERENCES `ventas` (`id_venta`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kardex_usuarios` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TRIGGER IF EXISTS `bu_kardex_inmutable`;
DROP TRIGGER IF EXISTS `bd_kardex_inmutable`;

DELIMITER $$
CREATE TRIGGER `bu_kardex_inmutable` BEFORE UPDATE ON `movimientos_inventario` FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Los movimientos de inventario no se editan: registra un ajuste';
END$$

CREATE TRIGGER `bd_kardex_inmutable` BEFORE DELETE ON `movimientos_inventario` FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Los movimientos de inventario no se borran: registra un ajuste';
END$$
DELIMITER ;

-- 5) liquidaciones de comisiones ----------------------------------------------
CREATE TABLE IF NOT EXISTS `liquidaciones` (
  `id_liquidacion` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_profesional` bigint(20) UNSIGNED DEFAULT NULL,
  `hasta` date NOT NULL,
  `cobros` int(11) NOT NULL,
  `total` decimal(12,0) NOT NULL,
  `metodo` enum('efectivo','transferencia') NOT NULL,
  `id_usuario_registra` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha` datetime NOT NULL,
  PRIMARY KEY (`id_liquidacion`),
  KEY `idx_liquidaciones_profesional` (`id_tienda`, `id_profesional`, `fecha`),
  CONSTRAINT `chk_liquidaciones_total` CHECK (`total` > 0 AND `cobros` > 0),
  CONSTRAINT `fk_liquidaciones_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_liquidaciones_profesional` FOREIGN KEY (`id_profesional`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_liquidaciones_registra` FOREIGN KEY (`id_usuario_registra`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `movimientos_caja` ADD COLUMN `id_venta` bigint(20) UNSIGNED DEFAULT NULL AFTER `id_cita`;
ALTER TABLE `movimientos_caja` ADD COLUMN `id_liquidacion` bigint(20) UNSIGNED DEFAULT NULL AFTER `pago_profesional`;
ALTER TABLE `movimientos_caja` ADD KEY `idx_caja_venta` (`id_venta`);
ALTER TABLE `movimientos_caja` ADD KEY `idx_caja_comisiones` (`id_tienda`, `id_profesional`, `id_liquidacion`);
ALTER TABLE `movimientos_caja` ADD CONSTRAINT `fk_caja_ventas` FOREIGN KEY (`id_venta`) REFERENCES `ventas` (`id_venta`) ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE `movimientos_caja` ADD CONSTRAINT `fk_caja_liquidaciones` FOREIGN KEY (`id_liquidacion`) REFERENCES `liquidaciones` (`id_liquidacion`) ON DELETE SET NULL ON UPDATE CASCADE;

-- 6) caja del dia por sede ----------------------------------------------------
CREATE TABLE IF NOT EXISTS `cajas_dia` (
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `fecha` date NOT NULL,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `estado` enum('abierta','cerrada') NOT NULL DEFAULT 'abierta',
  `base` decimal(12,0) NOT NULL DEFAULT 0,
  `ingresos` decimal(12,0) DEFAULT NULL,
  `salidas` decimal(12,0) DEFAULT NULL,
  `transferencias` decimal(12,0) DEFAULT NULL,
  `efectivo_esperado` decimal(12,0) DEFAULT NULL,
  `contado` decimal(12,0) DEFAULT NULL,
  `diferencia` decimal(12,0) DEFAULT NULL,
  `observaciones` varchar(255) DEFAULT NULL,
  `id_usuario_cierre` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha_cierre` datetime DEFAULT NULL,
  PRIMARY KEY (`id_sede`, `fecha`),
  KEY `idx_cajas_dia_tienda` (`id_tienda`, `fecha`),
  CONSTRAINT `chk_cajas_dia_base` CHECK (`base` >= 0 AND (`contado` IS NULL OR `contado` >= 0)),
  CONSTRAINT `fk_cajas_dia_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_cajas_dia_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_cajas_dia_cierre` FOREIGN KEY (`id_usuario_cierre`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
