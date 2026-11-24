import logging

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.queue import enqueue_repository_indices

logger = logging.getLogger(__name__)


async def reconcile_catalog(ctx=None) -> dict[str, int]:
    """Refresh stale catalog entries and repair jobs stranded by worker/queue failures."""
    settings = get_settings()
    pending_jobs: list[dict[str, str | None]] = []
    created = 0
    recovered = 0

    async with SessionLocal() as session:
        # Arq's hard timeout is six minutes. Recover running jobs after the configured
        # grace period and delayed retry jobs only after their maximum backoff window.
        result = await session.execute(
            text("""
                UPDATE repository_index_jobs
                SET status = 'queued',
                    error = COALESCE(error, 'Recovered after worker interruption'),
                    updated_at = now()
                WHERE (status = 'running'
                       AND updated_at < now() - make_interval(mins => :stale_minutes))
                   OR (status = 'retrying'
                       AND updated_at < now() - make_interval(mins => GREATEST(:stale_minutes, 20)))
                RETURNING id::text AS id, repository_url, requested_by::text AS requested_by
            """),
            {"stale_minutes": settings.indexing_stale_job_minutes},
        )
        recovered += len(result.mappings().all())

        # Re-enqueue deterministic Arq IDs to repair the DB-commit/Redis-enqueue gap.
        result = await session.execute(
            text("""
                SELECT id::text AS id, repository_url, requested_by::text AS requested_by
                FROM repository_index_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"limit": settings.indexing_reconcile_batch_size},
        )
        pending_jobs.extend(dict(row) for row in result.mappings())

        # Each shared catalog app is refreshed once, independent of user submissions.
        # Advisory locks prevent duplicate scheduled jobs across scheduler replicas.
        result = await session.execute(
            text("""
                SELECT id::text AS id, repository_url
                FROM apps
                WHERE (apps.indexed_at IS NULL
                       OR apps.indexed_at < now() - make_interval(days => :stale_days))
                  AND NOT EXISTS (
                      SELECT 1 FROM repository_index_jobs AS jobs
                      WHERE jobs.repository_url = apps.repository_url
                        AND (
                            jobs.status IN ('queued', 'running', 'retrying')
                            OR (jobs.source = 'scheduled' AND jobs.status = 'failed'
                                AND jobs.updated_at > now() - interval '24 hours')
                        )
                  )
                ORDER BY apps.indexed_at ASC NULLS FIRST, apps.id ASC
                LIMIT :limit
            """),
            {
                "stale_days": settings.catalog_refresh_interval_days,
                "limit": settings.catalog_refresh_batch_size,
            },
        )
        stale_apps = [dict(row) for row in result.mappings()]

        for app in stale_apps:
            lock = await session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:repository_url))"),
                {"repository_url": app["repository_url"]},
            )
            if not lock.scalar_one():
                continue
            active = await session.execute(
                text("""
                    SELECT 1 FROM repository_index_jobs
                    WHERE repository_url = :repository_url
                      AND (
                          status IN ('queued', 'running', 'retrying')
                          OR (source = 'scheduled' AND status = 'failed'
                              AND updated_at > now() - interval '24 hours')
                      )
                    LIMIT 1
                """),
                {"repository_url": app["repository_url"]},
            )
            if active.scalar_one_or_none() is not None:
                continue
            inserted = await session.execute(
                text("""
                    INSERT INTO repository_index_jobs (repository_url, source)
                    VALUES (:repository_url, 'scheduled')
                    RETURNING id::text AS id, repository_url,
                              requested_by::text AS requested_by
                """),
                {"repository_url": app["repository_url"]},
            )
            pending_jobs.append(dict(inserted.mappings().one()))
            created += 1

        await session.commit()

    enqueued = 0
    if pending_jobs:
        try:
            enqueued = await enqueue_repository_indices(pending_jobs)
        except Exception:
            # Leave durable rows queued; the next 15-minute tick retries them.
            logger.exception("Catalog reconciliation could not reach Redis")

    summary = {
        "scheduled": created,
        "recovered": recovered,
        "enqueued": enqueued,
        "candidates": len(stale_apps),
    }
    logger.info("Catalog reconciliation completed: %s", summary)
    return summary
