-- Panel Master (jempo, 2026-11-06): historial de cobros de Turnio a cada
-- negocio. Cada "Registrar pago" (mensualidad por 1, 3, 6 o 12 meses) y cada
-- montaje de sede cobrado deja una fila aqui; el panel suma lo cobrado en el
-- mes y muestra el historial de cada negocio. Solo crea estructura.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `pagos_master` (
  `id_pago` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `id_tienda` bigint(20) UNSIGNED NOT NULL,
  `concepto` enum('Mensualidad','Montaje') NOT NULL,
  `plan_id` varchar(20) DEFAULT NULL,
  `meses` tinyint(3) UNSIGNED DEFAULT NULL,
  `monto` int(10) UNSIGNED NOT NULL,
  `vence_hasta` date DEFAULT NULL,
  `nota` varchar(200) DEFAULT NULL,
  `id_usuario` bigint(20) UNSIGNED DEFAULT NULL,
  `fecha` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id_pago`),
  KEY `idx_pagos_master_tienda` (`id_tienda`, `fecha`),
  KEY `idx_pagos_master_fecha` (`fecha`),
  CONSTRAINT `fk_pagos_master_tiendas` FOREIGN KEY (`id_tienda`) REFERENCES `tiendas` (`id_tienda`) ON UPDATE CASCADE,
  CONSTRAINT `fk_pagos_master_usuarios` FOREIGN KEY (`id_usuario`) REFERENCES `usuarios` (`id_usuario`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
