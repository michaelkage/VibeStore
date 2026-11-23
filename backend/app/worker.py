from arq import Retry
from arq.connections import RedisSettings
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.services.indexing import index_repository_snapshot

MAX_ATTEMPTS = 5


async def index_repository_job(ctx, job_id: str, repository_url: str, requested_by: str | None):
    attempt = int(ctx.get("job_try", 1))
    async with SessionLocal() as session:
        await session.execute(
            text("""
                UPDATE repository_index_jobs
                SET status = 'running', attempt_count = :attempt, error = NULL, updated_at = now()
                WHERE id = CAST(:job_id AS uuid)
            """),
            {"job_id": job_id, "attempt": attempt},
        )
        await session.commit()
        try:
            result = await index_repository_snapshot(session, repository_url, requested_by)
            await session.execute(
                text("""
                    UPDATE repository_index_jobs
                    SET status = 'completed', app_id = CAST(:app_id AS uuid),
                        error = NULL, updated_at = now(), completed_at = now()
                    WHERE id = CAST(:job_id AS uuid)
                """),
                {"job_id": job_id, "app_id": result["app_id"]},
            )
            await session.commit()
            return result
        except Exception as exc:
            await session.rollback()
            await session.execute(
                text("""
                    UPDATE repository_index_jobs
                    SET status = :status, error = :error, updated_at = now()
                    WHERE id = CAST(:job_id AS uuid)
                """),
                {
                    "job_id": job_id,
                    "status": "failed" if attempt >= MAX_ATTEMPTS else "retrying",
                    "error": str(exc)[:2000],
                },
            )
            await session.commit()
            if attempt >= MAX_ATTEMPTS:
                raise
            raise Retry(defer=min(30 * (2 ** (attempt - 1)), 900)) from exc


async def startup(ctx):
    return None


async def shutdown(ctx):
    await dispose_engine()


class WorkerSettings:
    functions = [index_repository_job]
    queue_name = "vibestore:repository-index"
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 8
    job_timeout = 360
    max_tries = MAX_ATTEMPTS
    keep_result = 3600
    retry_jobs = True
