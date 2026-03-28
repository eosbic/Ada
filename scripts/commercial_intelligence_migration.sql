-- Commercial Intelligence + Agent Status

-- Prospectos con tracking de secuencia de outreach
CREATE TABLE IF NOT EXISTS prospect_intelligence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID,

    -- Datos del prospecto
    full_name TEXT NOT NULL,
    job_title TEXT DEFAULT '',
    company_name TEXT DEFAULT '',
    email TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    photo_url TEXT DEFAULT '',

    -- Como llego
    source TEXT DEFAULT 'manual',
    intent_signal TEXT DEFAULT '',
    intent_source TEXT DEFAULT '',

    -- Perfilamiento
    company_profile TEXT DEFAULT '',
    empathy_synthesis TEXT DEFAULT '',
    profile_data JSONB DEFAULT '{}',

    -- Estado de outreach
    status TEXT DEFAULT 'new',

    -- Secuencia de emails
    email_1_draft TEXT DEFAULT '',
    email_1_sent_at TIMESTAMP,
    email_2_sent_at TIMESTAMP,
    email_3_sent_at TIMESTAMP,
    response_received TEXT DEFAULT '',
    response_sentiment TEXT DEFAULT '',

    next_action_date TIMESTAMP,
    follow_up_id UUID,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prospect_empresa ON prospect_intelligence(empresa_id);
CREATE INDEX IF NOT EXISTS idx_prospect_status ON prospect_intelligence(status);

-- Configuracion de monitoreo de oportunidades por empresa
CREATE TABLE IF NOT EXISTS prospect_watch_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID,

    -- Que monitorear
    sectors JSONB DEFAULT '[]',
    regions JSONB DEFAULT '[]',
    keywords JSONB DEFAULT '[]',
    target_titles JSONB DEFAULT '[]',

    -- Configuracion
    frequency_hours INT DEFAULT 48,
    is_active BOOLEAN DEFAULT TRUE,
    max_leads_per_scan INT DEFAULT 5,

    -- Estado
    last_scan_at TIMESTAMP,
    total_leads_found INT DEFAULT 0,
    activated_at TIMESTAMP DEFAULT NOW(),
    deactivated_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_watch_per_user UNIQUE (empresa_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_watch_config_active
    ON prospect_watch_config(empresa_id, is_active) WHERE is_active = TRUE;

-- Estado de agentes por empresa (para brief + dashboard)
CREATE TABLE IF NOT EXISTS agent_status (
    id SERIAL PRIMARY KEY,
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,

    agent_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,

    -- Metadata
    last_run_at TIMESTAMP,
    last_result TEXT DEFAULT '',
    config JSONB DEFAULT '{}',

    activated_at TIMESTAMP DEFAULT NOW(),
    deactivated_at TIMESTAMP,

    UNIQUE(empresa_id, agent_name)
);

-- Insertar agentes por defecto para empresas existentes
INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
SELECT e.id, 'email_monitor', 'Monitoreo de emails', TRUE
FROM empresas e
ON CONFLICT (empresa_id, agent_name) DO NOTHING;

INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
SELECT e.id, 'meeting_intel', 'Meeting Intelligence', TRUE
FROM empresas e
ON CONFLICT (empresa_id, agent_name) DO NOTHING;

INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
SELECT e.id, 'brief', 'Brief diario', TRUE
FROM empresas e
ON CONFLICT (empresa_id, agent_name) DO NOTHING;

INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
SELECT e.id, 'follow_up', 'Follow-up automatico', TRUE
FROM empresas e
ON CONFLICT (empresa_id, agent_name) DO NOTHING;

INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
SELECT e.id, 'prospect_scout', 'Prospeccion de mercado', FALSE
FROM empresas e
ON CONFLICT (empresa_id, agent_name) DO NOTHING;
