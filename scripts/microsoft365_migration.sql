-- Microsoft 365 Provider Support
-- No requiere cambios de schema: tenant_credentials ya soporta providers arbitrarios.
-- Solo verificar que el constraint UNIQUE (empresa_id, provider) existe.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'tenant_credentials_empresa_id_provider_key'
    ) THEN
        ALTER TABLE tenant_credentials
            ADD CONSTRAINT tenant_credentials_empresa_id_provider_key
            UNIQUE (empresa_id, provider);
    END IF;
END
$$;

-- Providers válidos en tenant_credentials:
-- Google:    gmail, google_calendar, google_drive
-- Microsoft: outlook_email, outlook_calendar, onedrive
-- Otros:     notion, plane
