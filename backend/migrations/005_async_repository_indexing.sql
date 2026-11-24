CREATE TABLE IF NOT EXISTS repository_index_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_url TEXT NOT NULL,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'api',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'retrying', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error TEXT,
    app_id UUID REFERENCES apps(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS repository_index_jobs_owner_idx
    ON repository_index_jobs(requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS repository_index_jobs_status_idx
    ON repository_index_jobs(status, updated_at);

CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    repository_url TEXT,
    job_id UUID REFERENCES repository_index_jobs(id) ON DELETE SET NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
