-- RBAC: Audit Log — Registra accesos a datos sensibles
-- Ejecutar: PGPASSWORD=mK9Qw2Jd5ZxT7cLp psql -h localhost -U postgres -d ada -f scripts/audit_log_migration.sql

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL,
    user_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    agent_name VARCHAR(50),
    detail JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_empresa_id ON audit_log(empresa_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_empresa_created ON audit_log(empresa_id, created_at DESC);
