CREATE TABLE IF NOT EXISTS remix_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    source_commit_sha TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New remix',
    status TEXT NOT NULL DEFAULT 'planning'
        CHECK (status IN ('planning', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS remix_sessions_owner_updated_idx
    ON remix_sessions(owner_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS remix_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES remix_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text'
        CHECK (message_type IN ('text', 'change_plan')),
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS remix_messages_session_created_idx
    ON remix_messages(session_id, created_at);
COMMENT ON TABLE remix_sessions IS
    'Owner-scoped prompt-first remix planning sessions pinned to an indexed source commit; no source code execution.';
COMMENT ON TABLE remix_messages IS
    'Conversation and evidence-backed change plans. Repository content is untrusted input.';
