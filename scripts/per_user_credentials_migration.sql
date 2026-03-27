-- Per-User Credentials + Shared Drive separation
-- Ejecutar una sola vez en producción.

-- Agregar user_id a tenant_credentials (NULL = credencial de empresa)
ALTER TABLE tenant_credentials
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES usuarios(id) ON DELETE CASCADE;

-- Eliminar el constraint viejo
ALTER TABLE tenant_credentials
    DROP CONSTRAINT IF EXISTS tenant_credentials_empresa_provider_unique;

-- Nuevo unique index con COALESCE para NULLs
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_creds_empresa_provider_user
    ON tenant_credentials (empresa_id, provider, COALESCE(user_id, '00000000-0000-0000-0000-000000000000'));

-- Index para búsquedas por user_id
CREATE INDEX IF NOT EXISTS idx_tenant_creds_user
    ON tenant_credentials (user_id) WHERE user_id IS NOT NULL;

-- Migrar credenciales de google_drive existentes a google_shared_drive (eran de empresa)
UPDATE tenant_credentials
    SET provider = 'google_shared_drive'
    WHERE provider = 'google_drive' AND user_id IS NULL;

-- Migrar onedrive existentes a sharepoint (eran de empresa)
UPDATE tenant_credentials
    SET provider = 'sharepoint'
    WHERE provider = 'onedrive' AND user_id IS NULL;
