-- Admin Portal: tablas para autenticacion 2FA y auditoria.
-- Ejecutar una sola vez en produccion.

-- Tabla de usuarios admin del portal EOS IA
CREATE TABLE IF NOT EXISTS admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login TIMESTAMP,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Codigos OTP para 2FA
CREATE TABLE IF NOT EXISTS admin_otp_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    code VARCHAR(6) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    ip_address TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Log de auditoria de acciones admin
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES admin_users(id),
    action TEXT NOT NULL,
    target_type TEXT,
    target_id UUID,
    details JSONB DEFAULT '{}',
    ip_address TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_admin_otp_lookup
    ON admin_otp_codes (admin_user_id, used, expires_at);

CREATE INDEX IF NOT EXISTS idx_admin_audit_user_time
    ON admin_audit_log (admin_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_target
    ON admin_audit_log (target_type, target_id);
