-- Multisede sin tope de sedes (jempo, 2026-10-09): cada sede extra se cobra
-- (app/services/plan_service.py), asi que se quitan los triggers que cortaban en 5.
DROP TRIGGER IF EXISTS `bi_sedes_limite`;
DROP TRIGGER IF EXISTS `bu_sedes_limite`;
