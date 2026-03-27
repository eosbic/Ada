-- Pricing Model V2 — Per-user + quality-based plans
-- Ejecutar una sola vez en produccion.

-- Nuevas columnas en budget_limits
ALTER TABLE budget_limits
    ADD COLUMN IF NOT EXISTS base_users INT DEFAULT 3,
    ADD COLUMN IF NOT EXISTS extra_users INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS price_per_extra_user NUMERIC(10,2) DEFAULT 16.67,
    ADD COLUMN IF NOT EXISTS monthly_analyses_limit INT DEFAULT 30,
    ADD COLUMN IF NOT EXISTS analyses_used_this_month INT DEFAULT 0;

-- Actualizar planes existentes con los nuevos valores
UPDATE budget_limits SET
    base_users = 3,
    monthly_analyses_limit = 30,
    price_per_extra_user = 16.67,
    monthly_limit = 50
WHERE plan_type = 'start';

UPDATE budget_limits SET
    base_users = 3,
    monthly_analyses_limit = 50,
    price_per_extra_user = 23.00,
    monthly_limit = 70
WHERE plan_type = 'premium';

-- Migrar plan "pro" a "premium"
UPDATE budget_limits SET
    plan_type = 'premium',
    base_users = 3,
    monthly_analyses_limit = 50,
    price_per_extra_user = 23.00,
    monthly_limit = 70
WHERE plan_type = 'pro';

UPDATE budget_limits SET
    base_users = 3,
    monthly_analyses_limit = 80,
    price_per_extra_user = 30.00,
    monthly_limit = 90
WHERE plan_type = 'enterprise';

-- Recalcular max_users = base_users + extra_users para empresas existentes
UPDATE budget_limits SET max_users = base_users + extra_users;
