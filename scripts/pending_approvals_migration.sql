-- Pending Approvals: persistir acciones HITL pendientes de aprobacion.
-- Reemplaza _PENDING_APPROVALS dict en RAM que se perdia al reiniciar.

CREATE TABLE IF NOT EXISTS pending_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    draft_type TEXT NOT NULL DEFAULT 'email',
    draft_content JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_lookup
    ON pending_approvals (empresa_id, user_id, status);
