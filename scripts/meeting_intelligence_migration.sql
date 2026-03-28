CREATE TABLE IF NOT EXISTS meeting_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID REFERENCES empresas(id) ON DELETE CASCADE,
    user_id UUID REFERENCES usuarios(id),

    -- Datos de la reunión
    event_title TEXT DEFAULT '',
    event_date TIMESTAMP,
    meet_link TEXT DEFAULT '',
    participants JSONB DEFAULT '[]',

    -- Transcript
    gmail_message_id TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    transcript_speakers JSONB DEFAULT '[]',

    -- Resultados del procesamiento
    summary TEXT DEFAULT '',
    tasks JSONB DEFAULT '[]',
    risks JSONB DEFAULT '[]',
    decisions JSONB DEFAULT '[]',
    next_meeting TEXT DEFAULT '',

    -- Estado
    status TEXT DEFAULT 'processed',
    report_id UUID,
    tasks_created_in_pm BOOLEAN DEFAULT FALSE,
    summary_sent_to_participants BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meeting_events_empresa
    ON meeting_events(empresa_id);
CREATE INDEX IF NOT EXISTS idx_meeting_events_date
    ON meeting_events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_meeting_events_gmail_msg
    ON meeting_events(gmail_message_id);
