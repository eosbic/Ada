-- ========================================
-- ADA V5.0 - SCHEMA BASE MULTI-TENANT
-- ========================================

-- =========================
-- EMPRESAS
-- =========================    

CREATE EXTENSION IF NOT EXISTS "pgcrypto";


CREATE TABLE IF NOT EXISTS empresas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    sector TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- USUARIOS
-- =========================
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    nombre TEXT,
    password TEXT NOT NULL,
    rol TEXT DEFAULT 'member',
    created_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- BUDGET LIMITS
-- =========================
CREATE TABLE IF NOT EXISTS budget_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    monthly_limit NUMERIC DEFAULT 100,
    used_this_month NUMERIC DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- TENANT CREDENTIALS
-- =========================
CREATE TABLE IF NOT EXISTS tenant_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    encrypted_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =========================
-- EVENTS
-- =========================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSON,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id),
    service VARCHAR(100),
    key TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    actions JSONB NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);


-- =========================
-- PERFIL DE EMPRESA (ONBOARDING)
-- =========================
CREATE TABLE IF NOT EXISTS ada_company_profile (
    empresa_id UUID PRIMARY KEY REFERENCES empresas(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    industry_type TEXT DEFAULT 'generic',
    business_description TEXT,
    main_products JSONB DEFAULT '[]',
    main_services JSONB DEFAULT '[]',
    company_size TEXT DEFAULT 'small',
    num_employees INTEGER,
    city TEXT,
    country TEXT DEFAULT 'Colombia',
    currency TEXT DEFAULT 'COP',
    ada_custom_name TEXT DEFAULT 'Ada',
    ada_personality TEXT DEFAULT 'directo',
    admin_interests JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    configured_by UUID
);

-- =========================
-- MIEMBROS DEL EQUIPO (PERMISOS)
-- =========================
CREATE TABLE IF NOT EXISTS team_members (
    id SERIAL PRIMARY KEY,
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    department TEXT,
    permissions JSONB NOT NULL DEFAULT '{
        "can_view_sales": false,
        "can_view_finance": false,
        "can_view_inventory": false,
        "can_view_clients": false,
        "can_view_projects": false,
        "can_view_hr": false,
        "can_send_email": false,
        "can_manage_calendar": false,
        "can_upload_files": false,
        "can_use_voice": false,
        "can_prospect": false
    }',
    access_collections JSONB DEFAULT '["knowledge"]',
    is_active BOOLEAN DEFAULT TRUE,
    added_by UUID,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(empresa_id, user_id)
);

-- =========================
-- PREFERENCIAS DE USUARIO
-- =========================
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id UUID PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    preferences JSONB DEFAULT '{}',
    onboarding_completed BOOLEAN DEFAULT FALSE,
    onboarding_completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reportes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID REFERENCES usuarios(id),
    file_name TEXT NOT NULL,
    analysis TEXT NOT NULL,
    calculations JSONB DEFAULT '{}',
    statistical_profile JSONB DEFAULT '{}',
    alerts JSONB DEFAULT '[]',
    industry_type TEXT DEFAULT 'generic',
    model_used TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reportes_empresa ON reportes(empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reportes_filename ON reportes(empresa_id, file_name);


ALTER TABLE tenant_credentials 
    ADD COLUMN IF NOT EXISTS oauth2_refresh_token_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS oauth2_expiry TIMESTAMP,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- Crear constraint UNIQUE si no existe
-- (empresa_id + provider debe ser único)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'tenant_credentials_empresa_provider_unique'
    ) THEN
        ALTER TABLE tenant_credentials 
            ADD CONSTRAINT tenant_credentials_empresa_provider_unique 
            UNIQUE (empresa_id, provider);
    END IF;
EXCEPTION WHEN duplicate_table THEN
    -- Ya existe, ignorar
    NULL;
END $$;

-- =============================================
-- ADA V5.0 — MIGRACIÓN: ada_reports (Contrato de Datos)
-- Ejecutar en PostgreSQL
-- =============================================

-- 1. Crear tabla ada_reports con esquema completo
CREATE TABLE IF NOT EXISTS ada_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    thread_id VARCHAR(100),

    -- Metadatos del artefacto
    title VARCHAR(200) NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    source_file VARCHAR(255),

    -- Contrato Dual (Markdown + JSON)
    markdown_content TEXT NOT NULL,
    metrics_summary JSONB DEFAULT '{}',
    alerts JSONB DEFAULT '[]',

    -- Trazabilidad
    generated_by VARCHAR(50) NOT NULL,
    is_archived BOOLEAN DEFAULT FALSE,
    requires_action BOOLEAN DEFAULT FALSE,

    -- RBAC
    allowed_roles TEXT[] DEFAULT '{}',
    access_level VARCHAR(20) DEFAULT 'company',

    -- Versionado
    version INTEGER DEFAULT 1,
    parent_report_id UUID REFERENCES ada_reports(id),

    -- Full-text search
    search_vector tsvector,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Índices
CREATE INDEX IF NOT EXISTS idx_reports_empresa_date ON ada_reports(empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_type ON ada_reports(empresa_id, report_type);
CREATE INDEX IF NOT EXISTS idx_reports_search ON ada_reports USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_reports_thread ON ada_reports(thread_id);

-- 3. Trigger para actualizar search_vector automáticamente
CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('pg_catalog.spanish',
        COALESCE(NEW.title, '') || ' ' ||
        COALESCE(NEW.markdown_content, '') || ' ' ||
        COALESCE(NEW.source_file, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_search_vector_update ON ada_reports;
CREATE TRIGGER trg_search_vector_update
    BEFORE INSERT OR UPDATE ON ada_reports
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

-- 4. Tabla de links entre reportes (Knowledge Graph)
CREATE TABLE IF NOT EXISTS report_links (
    source_report_id UUID REFERENCES ada_reports(id) ON DELETE CASCADE,
    target_report_id UUID REFERENCES ada_reports(id) ON DELETE CASCADE,
    link_type VARCHAR(50) DEFAULT 'related',
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (source_report_id, target_report_id)
);

-- 5. Si tenías tabla reportes vieja, migrar datos
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'reportes') THEN
        INSERT INTO ada_reports (empresa_id, title, report_type, markdown_content, metrics_summary, alerts, generated_by, source_file, created_at)
        SELECT
            empresa_id,
            'Análisis: ' || file_name,
            'excel_analysis',
            analysis,
            COALESCE(calculations, '{}')::jsonb,
            COALESCE(alerts, '[]')::jsonb,
            COALESCE(model_used, 'unknown'),
            file_name,
            created_at
        FROM reportes;

        RAISE NOTICE 'Datos migrados de reportes → ada_reports';
    END IF;
END $$;


-- 1. Columna telegram_id en usuarios
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telegram_id TEXT UNIQUE;

-- 2. Columnas extra en ada_company_profile que usa el Context Builder
ALTER TABLE ada_company_profile 
    ADD COLUMN IF NOT EXISTS fiscal_year_start INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS target_market TEXT,
    ADD COLUMN IF NOT EXISTS main_competitors JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS key_metrics JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS kpi_targets JSONB DEFAULT '{}';