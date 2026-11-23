CREATE TABLE IF NOT EXISTS repository_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, app_id)
);
CREATE INDEX IF NOT EXISTS repository_submissions_app_idx ON repository_submissions(app_id);
CREATE INDEX IF NOT EXISTS repository_submissions_user_idx ON repository_submissions(user_id, submitted_at DESC);
