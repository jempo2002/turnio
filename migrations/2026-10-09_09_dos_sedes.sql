-- Regla de jempo para todos sus productos (2026-10-09): hasta 2 sedes por
-- negocio, el mismo Admin las maneja y hasta 2 Admin. Multisede baja de 5 a
-- 2 sedes (MAX_SEDES de app/services/plan_service.py) y se acaban las sedes
-- extra pagas. Los triggers de respaldo pasan de 5 a 2. Un negocio que ya
-- tenga mas de 2 sedes activas las conserva; solo no puede abrir otra.
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
    IF v_activas >= 2 THEN
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
    IF v_activas >= 2 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Limite de sedes alcanzado';
    END IF;
  END IF;
END$$
DELIMITER ;
