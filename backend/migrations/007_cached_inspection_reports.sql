-- Inspection reports are immutable per app commit and can be fetched without re-running analysis.
CREATE INDEX IF NOT EXISTS inspections_app_created_idx
    ON inspections(app_id, created_at DESC);

COMMENT ON TABLE inspections IS
    'Evidence-backed static inspection reports cached by app and source commit SHA.';
