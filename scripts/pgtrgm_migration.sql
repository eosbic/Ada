-- pg_trgm: habilita busqueda fuzzy tolerante a typos en reportes.
-- Permite encontrar "ventas" cuando el usuario escribe "bentaz" o "vntas".
-- Ejecutar una sola vez en produccion.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Indices GIN para busqueda fuzzy por trigrama en titulo y archivo fuente
CREATE INDEX IF NOT EXISTS idx_reports_title_trgm
    ON ada_reports USING GIN (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_reports_source_trgm
    ON ada_reports USING GIN (source_file gin_trgm_ops);
