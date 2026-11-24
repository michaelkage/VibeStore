CREATE TABLE IF NOT EXISTS remix_patch_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES remix_sessions(id) ON DELETE CASCADE,
    base_commit_sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
    summary TEXT NOT NULL,
    proposal JSONB NOT NULL,
    source_files JSONB NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'review_only' CHECK (validation_status IN ('review_only')),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS remix_patch_proposals_session_created_idx
    ON remix_patch_proposals(session_id, created_at DESC);
COMMENT ON TABLE remix_patch_proposals IS
    'Owner-scoped review-only patch drafts pinned to source commit and indexed file hashes. Approval never applies code.';
