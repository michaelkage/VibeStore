-- Scheduled refreshes need efficient stale-catalog scans and job recovery.
CREATE INDEX IF NOT EXISTS apps_indexed_at_idx
    ON apps(indexed_at ASC NULLS FIRST);

CREATE INDEX IF NOT EXISTS repository_index_jobs_queued_idx
    ON repository_index_jobs(created_at ASC)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS repository_index_jobs_running_idx
    ON repository_index_jobs(updated_at ASC)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS repository_index_jobs_repository_active_idx
    ON repository_index_jobs(repository_url, status)
    WHERE status IN ('queued', 'running', 'retrying');

COMMENT ON TABLE repository_index_jobs IS
    'Durable PostgreSQL job ledger for user, webhook, and scheduled repository indexing.';
