-- Company DNA Migration
-- Extiende ada_company_profile con campos DNA.
-- NO crea tabla nueva — agrega columnas a la existente.

-- DNA estratégico
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS mission TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS vision TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS objectives JSONB DEFAULT '[]';
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS value_proposition TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS business_model TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS sales_cycle_days INTEGER;

-- Marca y comunicación
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS brand_voice TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS product_catalog JSONB DEFAULT '[]';
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS target_icp JSONB DEFAULT '{}';
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS success_cases TEXT;

-- Presencia digital
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS website_url TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS website_summary TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS social_urls JSONB DEFAULT '{}';
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS social_analysis TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS brand_colors JSONB DEFAULT '{}';

-- Configuración de agentes
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS agent_configs JSONB DEFAULT '{}';

-- Apps conectadas
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS productivity_suite TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS pm_tool TEXT;
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS extra_apps JSONB DEFAULT '[]';

-- Estado de onboarding
ALTER TABLE ada_company_profile ADD COLUMN IF NOT EXISTS onboarding_complete BOOLEAN DEFAULT FALSE;

-- Tracking de apps conectadas por empresa
-- service: 'email', 'calendar', 'drive', 'pm'
-- provider: 'google', 'microsoft', 'notion', 'plane', 'asana', etc.
CREATE TABLE IF NOT EXISTS tenant_app_config (
    id SERIAL PRIMARY KEY,
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    service VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    oauth_connected BOOLEAN DEFAULT FALSE,
    connected_at TIMESTAMP,
    connected_by TEXT,
    UNIQUE(empresa_id, service)
);
