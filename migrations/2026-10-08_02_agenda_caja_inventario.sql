-- ============================================================
-- Migracion: agenda, caja e inventario de Turnio
-- Fecha: 2026-10-08
-- Motor: MariaDB 10.6+ y MySQL 8
-- ============================================================
--
-- El esquema del backend Node (backend/db/schema.sql + 002_public_booking.sql,
-- PostgreSQL) pasado a MySQL con las convenciones de jemPOS: nombres en
-- espanol, pesos enteros en decimal(12,0) (COP no usa centavos), soft delete
-- con columnas `*_vivo` para los UNIQUE y todo filtrado por id_tienda.
--
-- 1) horarios_sede: el horario por dia de cada sede (configuracion.html).
--    dia 0 = lunes ... 6 = domingo. Sin fila o abierto = 0: cerrado ese dia.
-- 2) servicios: catalogo con duracion, precio y lo que gana el profesional
--    por cada uno (`pago_profesional`, el pagoBarbero de datos.js).
-- 3) citas: una fila por cita reservada o franja bloqueada. Los espacios
--    libres no se guardan: se calculan con el horario y las citas (T6).
--    Candado de reservas (portado de uq_appointments_staff_slot): dos citas
--    vigentes no pueden tener el mismo profesional a la misma hora de inicio.
--    `franja_viva` es NULL al completar, cancelar o marcar inasistencia, asi
--    el profesional queda libre otra vez (MySQL no tiene indices parciales).
--    ponytail: compara la hora de inicio exacta; los cruces por duracion
--    (servicio de 60 min a las 10:00 contra otro a las 10:30) los valida T6
--    dentro de la transaccion con SELECT ... FOR UPDATE sobre el profesional.
-- 4) productos: inventario por negocio con codigo de barras.
-- 5) movimientos_caja: ingresos y salidas. Un cobro con pago mixto son dos
--    filas; `pago_profesional` va solo en la primera.
--
-- Se puede correr varias veces.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `horarios_sede` (
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `dia` tinyint(1) UNSIGNED NOT NULL,
  `abierto` tinyint(1) NOT NULL DEFAULT 1,
  `abre` time NOT NULL DEFAULT '08:00:00',
  `cierra` time NOT NULL DEFAULT '19:00:00',
  `almuerzo_desde` time DEFAULT NULL,
  `almuerzo_hasta` time DEFAULT NULL,
  PRIMARY KEY (`id_sede`, `dia`),
  CONSTRAINT `chk_horarios_dia` CHECK (`dia` <= 6),
  CONSTRAINT `chk_horarios_rango` CHECK (`cierra` > `abre`),
  CONSTRAINT `chk_horarios_almuerzo` CHECK (
    (`almuerzo_desde` IS NULL AND `almuerzo_hasta` IS NULL)
    OR (`almuerzo_hasta` > `almuerzo_desde` AND `almuerzo_desde` >= `abre` AND `almuerzo_hasta` <= `cierra`)
  ),
  CONSTRAINT `fk_horarios_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `servicios` (
  `id_servicio` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `nombre` varchar(120) NOT NULL,
  `duracion_min` smallint(5) UNSIGNED NOT NULL,
  `precio` decimal(12,0) NOT NULL,
  `pago_profesional` decimal(12,0) NOT NULL DEFAULT 0,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `nombre_vivo` varchar(120) GENERATED ALWAYS AS (IF(`estado_activo` = 1, `nombre`, NULL)) STORED,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_servicio`),
  UNIQUE KEY `uq_servicios_nombre_vivo` (`id_tienda`, `nombre_vivo`),
  CONSTRAINT `chk_servicios_duracion` CHECK (`duracion_min` BETWEEN 5 AND 720),
  CONSTRAINT `chk_servicios_precio` CHECK (`precio` >= 0 AND `pago_profesional` >= 0 AND `pago_profesional` <= `precio`),
  CONSTRAINT `fk_servicios_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `citas` (
  `id_cita` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `id_servicio` bigint(20) UNSIGNED DEFAULT NULL,
  `id_profesional` bigint(20) UNSIGNED DEFAULT NULL,
  `cliente_nombre` varchar(120) DEFAULT NULL,
  `cliente_telefono` varchar(20) DEFAULT NULL,
  `inicio` datetime NOT NULL,
  `fin` datetime NOT NULL,
  `estado` enum('reservada','bloqueada','completada','cancelada','no_asistio') NOT NULL DEFAULT 'reservada',
  `precio` decimal(12,0) NOT NULL DEFAULT 0,
  `origen` enum('panel','publica') NOT NULL DEFAULT 'panel',
  `nota` varchar(255) DEFAULT NULL,
  `id_usuario_registra` bigint(20) UNSIGNED DEFAULT NULL,
  `franja_viva` datetime GENERATED ALWAYS AS (IF(`estado` IN ('reservada', 'bloqueada'), `inicio`, NULL)) STORED,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_cita`),
  UNIQUE KEY `uq_citas_profesional_franja` (`id_profesional`, `franja_viva`),
  KEY `idx_citas_agenda` (`id_tienda`, `id_sede`, `inicio`),
  KEY `idx_citas_profesional_inicio` (`id_profesional`, `inicio`),
  CONSTRAINT `chk_citas_rango` CHECK (`fin` > `inicio`),
  CONSTRAINT `chk_citas_precio` CHECK (`precio` >= 0),
  CONSTRAINT `fk_citas_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_citas_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON UPDATE CASCADE,
  CONSTRAINT `fk_citas_servicios` FOREIGN KEY (`id_servicio`) REFERENCES `servicios` (`id_servicio`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_citas_profesional` FOREIGN KEY (`id_profesional`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_citas_registra` FOREIGN KEY (`id_usuario_registra`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `productos` (
  `id_producto` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `codigo_barras` varchar(64) NOT NULL,
  `emoji` varchar(16) DEFAULT NULL,
  `nombre` varchar(120) NOT NULL,
  `stock` int(11) NOT NULL DEFAULT 0,
  `costo` decimal(12,0) NOT NULL DEFAULT 0,
  `precio` decimal(12,0) NOT NULL,
  `vendidos` int(11) NOT NULL DEFAULT 0,
  `estado_activo` tinyint(1) NOT NULL DEFAULT 1,
  `codigo_vivo` varchar(64) GENERATED ALWAYS AS (IF(`estado_activo` = 1, `codigo_barras`, NULL)) STORED,
  `fecha_creacion` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_producto`),
  UNIQUE KEY `uq_productos_codigo_vivo` (`id_tienda`, `codigo_vivo`),
  CONSTRAINT `chk_productos_valores` CHECK (`stock` >= 0 AND `vendidos` >= 0 AND `costo` >= 0 AND `precio` >= 0),
  CONSTRAINT `fk_productos_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `movimientos_caja` (
  `id_movimiento` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `id_sede` bigint(20) UNSIGNED NOT NULL,
  `tipo` enum('ingreso','salida') NOT NULL,
  `concepto` varchar(200) NOT NULL,
  `monto` decimal(12,0) NOT NULL,
  `metodo` enum('efectivo','transferencia') NOT NULL,
  `id_profesional` bigint(20) UNSIGNED DEFAULT NULL,
  `id_cita` bigint(20) UNSIGNED DEFAULT NULL,
  `pago_profesional` decimal(12,0) DEFAULT NULL,
  `id_usuario_registra` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_movimiento`),
  KEY `idx_caja_dia` (`id_tienda`, `id_sede`, `fecha`),
  KEY `idx_caja_cita` (`id_cita`),
  CONSTRAINT `chk_caja_monto` CHECK (`monto` > 0 AND (`pago_profesional` IS NULL OR `pago_profesional` >= 0)),
  CONSTRAINT `fk_caja_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_caja_sedes` FOREIGN KEY (`id_sede`) REFERENCES `sedes` (`id_sede`) ON UPDATE CASCADE,
  CONSTRAINT `fk_caja_profesional` FOREIGN KEY (`id_profesional`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_caja_citas` FOREIGN KEY (`id_cita`) REFERENCES `citas` (`id_cita`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_caja_registra` FOREIGN KEY (`id_usuario_registra`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
