ALTER TABLE remix_patch_proposals
    DROP CONSTRAINT IF EXISTS remix_patch_proposals_validation_status_check;
ALTER TABLE remix_patch_proposals
    ADD CONSTRAINT remix_patch_proposals_validation_status_check
    CHECK (validation_status IN ('review_only', 'applicable', 'invalid'));
ALTER TABLE remix_patch_proposals
    ADD COLUMN IF NOT EXISTS validation_report JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN remix_patch_proposals.validation_report IS
    'Hash-verified in-memory patch applicability report; no source files are written or executed.';
