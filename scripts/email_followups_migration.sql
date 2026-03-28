-- Email Followups — tracking de emails enviados por Ada
CREATE TABLE IF NOT EXISTS email_followups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,

    -- Email que Ada envió
    to_email TEXT NOT NULL,
    to_name TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    gmail_message_id TEXT DEFAULT '',
    gmail_thread_id TEXT DEFAULT '',
    sent_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Monitoreo
    status TEXT DEFAULT 'monitoring',  -- monitoring, responded, follow_up_sent, completed, expired
    response_detected_at TIMESTAMP,
    response_snippet TEXT DEFAULT '',

    -- Follow-up configurado
    follow_up_enabled BOOLEAN DEFAULT FALSE,
    follow_up_after_hours INT DEFAULT 48,
    follow_up_message TEXT DEFAULT '',
    follow_up_sent_at TIMESTAMP,
    follow_up_count INT DEFAULT 0,
    max_follow_ups INT DEFAULT 2,

    -- Metadata
    context TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '14 days'
);

CREATE INDEX IF NOT EXISTS idx_email_followups_monitoring
    ON email_followups (empresa_id, status) WHERE status IN ('monitoring', 'follow_up_sent');

CREATE INDEX IF NOT EXISTS idx_email_followups_user
    ON email_followups (user_id, status);
