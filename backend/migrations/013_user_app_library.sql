CREATE TABLE IF NOT EXISTS user_app_library (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    favorited_at TIMESTAMPTZ,
    last_opened_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, app_id),
    CONSTRAINT user_app_library_activity CHECK (
        favorited_at IS NOT NULL OR last_opened_at IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS user_app_library_recent_idx
    ON user_app_library (user_id, last_opened_at DESC NULLS LAST);
