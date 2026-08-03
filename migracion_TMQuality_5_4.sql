-- TMQuality 5.4 - Nuevos límites de los lotes de control
-- La aplicación realiza esta migración automáticamente.
-- Este archivo se entrega como alternativa para ejecutarla manualmente en Supabase.

BEGIN;

ALTER TABLE lotes_control
    ADD COLUMN IF NOT EXISTS limite_inferior DOUBLE PRECISION;

ALTER TABLE lotes_control
    ADD COLUMN IF NOT EXISTS nivel_medio DOUBLE PRECISION;

ALTER TABLE lotes_control
    ADD COLUMN IF NOT EXISTS limite_superior DOUBLE PRECISION;

UPDATE lotes_control
SET
    nivel_medio = COALESCE(nivel_medio, media_objetivo),
    limite_inferior = COALESCE(limite_inferior, media_objetivo - 3 * de_objetivo),
    limite_superior = COALESCE(limite_superior, media_objetivo + 3 * de_objetivo)
WHERE nivel_medio IS NULL
   OR limite_inferior IS NULL
   OR limite_superior IS NULL;

COMMIT;
