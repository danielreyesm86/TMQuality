-- TMQuality 5.6.6
-- Elimina la restricción antigua que limitaba lotes_control.nivel
-- a valores fijos como Bajo/Normal/Alto.

BEGIN;

ALTER TABLE public.lotes_control
DROP CONSTRAINT IF EXISTS "lotes_control_nivel_check";

COMMIT;
