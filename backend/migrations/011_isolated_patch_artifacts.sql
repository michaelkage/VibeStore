CREATE TABLE IF NOT EXISTS remix_patch_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id UUID NOT NULL UNIQUE REFERENCES remix_patch_proposals(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES remix_sessions(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    base_commit_sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposal_snapshot JSONB NOT NULL,
    artifact_zip BYTEA,
    manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS remix_patch_artifacts_owner_created_idx
    ON remix_patch_artifacts(owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS remix_patch_artifacts_queued_idx
    ON remix_patch_artifacts(created_at) WHERE status = 'queued';
COMMENT ON TABLE remix_patch_artifacts IS
    'Owner-scoped isolated patch processing jobs and downloadable modified-source artifacts; original Git revision remains immutable.';
