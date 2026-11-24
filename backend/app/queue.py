from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings

QUEUE_NAME = "vibestore:repository-index"


async def enqueue_repository_indices(jobs: list[dict]) -> int:
    if not jobs:
        return 0
    settings = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    enqueued = 0
    try:
        for job in jobs:
            result = await pool.enqueue_job(
                "index_repository_job",
                job["id"],
                job["repository_url"],
                job.get("requested_by"),
                _job_id=job["id"],
                _queue_name=QUEUE_NAME,
            )
            enqueued += result is not None
        return enqueued
    finally:
        await pool.aclose()


async def enqueue_repository_index(
    job_id: str,
    repository_url: str,
    requested_by: str | None,
):
    await enqueue_repository_indices([{
        "id": job_id,
        "repository_url": repository_url,
        "requested_by": requested_by,
    }])
