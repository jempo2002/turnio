-- Planes aprobados el 2026-10-08 (turnio/planes-y-precios.md): llega el plan
-- Multisede, con hasta 5 sedes activas (MAX_SEDES de
-- app/services/plan_service.py). Los triggers de respaldo pasan de 4 a 5.
-- El tope de cada plan lo sigue poniendo la app.
--
-- Se puede correr varias veces.

SET NAMES utf8mb4;

DROP TRIGGER IF EXISTS `bi_sedes_limite`;
DROP TRIGGER IF EXISTS `bu_sedes_limite`;

DELIMITER $$
CREATE TRIGGER `bi_sedes_limite` BEFORE INSERT ON `sedes` FOR EACH ROW
BEGIN
  DECLARE v_activas int;
  IF NEW.`estado` = 'Activa' THEN
    SELECT COUNT(*) INTO v_activas FROM `sedes` WHERE `id_tienda` = NEW.`id_tienda` AND `estado` = 'Activa';
    IF v_activas >= 5 THEN
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
    IF v_activas >= 5 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Limite de sedes alcanzado';
    END IF;
  END IF;
END$$
DELIMITER ;
