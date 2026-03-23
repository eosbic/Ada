-- Conversation History: persistir historial de chat en PostgreSQL
-- Reemplaza _CONVERSATION_HISTORY en RAM que se perdia al reiniciar.

CREATE TABLE IF NOT EXISTS conversation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    messages JSONB NOT NULL DEFAULT '[]',
    max_turns INTEGER DEFAULT 8,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(empresa_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_history_lookup
    ON conversation_history (empresa_id, user_id);
