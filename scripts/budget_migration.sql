-- Budget Migration: token_usage_log + budget_limits columns + budget_topups
-- Ejecutar una sola vez en produccion.

-- 1) Tabla de log granular de consumo de tokens
CREATE TABLE IF NOT EXISTS token_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id),
    user_id UUID REFERENCES usuarios(id),
    agent TEXT NOT NULL,
    model_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
    was_downgraded BOOLEAN NOT NULL DEFAULT FALSE,
    original_model TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 2) Columnas adicionales en budget_limits
ALTER TABLE budget_limits
    ADD COLUMN IF NOT EXISTS plan_type TEXT DEFAULT 'start',
    ADD COLUMN IF NOT EXISTS alert_threshold NUMERIC DEFAULT 0.8,
    ADD COLUMN IF NOT EXISTS alert_sent_this_month BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS total_tokens_this_month BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS topup_balance NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS period_start DATE DEFAULT DATE_TRUNC('month', NOW());

-- 3) Tabla de compras de topup
CREATE TABLE IF NOT EXISTS budget_topups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) NOT NULL,
    amount NUMERIC NOT NULL,
    purchased_by UUID REFERENCES usuarios(id),
    purchased_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 4) Indices para token_usage_log
CREATE INDEX IF NOT EXISTS idx_token_usage_empresa_created
    ON token_usage_log (empresa_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_token_usage_empresa_month
    ON token_usage_log (empresa_id, (DATE_TRUNC('month', created_at)));

-- 5) UNIQUE constraint en budget_limits
ALTER TABLE budget_limits
    ADD CONSTRAINT IF NOT EXISTS budget_limits_empresa_id_unique
    UNIQUE (empresa_id);

-- 6) Funcion de reset mensual
CREATE OR REPLACE FUNCTION reset_monthly_budgets()
RETURNS void AS $$
BEGIN
    UPDATE budget_limits
    SET used_this_month = 0,
        total_tokens_this_month = 0,
        topup_balance = 0,
        alert_sent_this_month = FALSE,
        period_start = DATE_TRUNC('month', NOW());

    RAISE NOTICE 'Monthly budget reset completed for all empresas';
END;
$$ LANGUAGE plpgsql;
