-- User Memories — Ada aprende de cada usuario
CREATE TABLE IF NOT EXISTS user_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fact TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence NUMERIC(3,2) DEFAULT 0.8,
    source TEXT DEFAULT 'conversation',
    times_reinforced INT DEFAULT 1,
    last_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_user_memories_user
    ON user_memories (empresa_id, user_id, is_active) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_memories_category
    ON user_memories (user_id, category) WHERE is_active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_memories_unique_fact
    ON user_memories (user_id, md5(fact));
