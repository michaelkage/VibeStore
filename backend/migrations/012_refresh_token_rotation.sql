CREATE TABLE IF NOT EXISTS user_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    replaced_by_hash TEXT
);

CREATE INDEX IF NOT EXISTS user_refresh_tokens_user_active_idx
    ON user_refresh_tokens (user_id, expires_at)
    WHERE revoked_at IS NULL;
