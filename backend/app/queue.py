from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings


async def enqueue_repository_index(
    job_id: str,
    repository_url: str,
    requested_by: str | None,
):
    settings = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        return await pool.enqueue_job(
            "index_repository_job",
            job_id,
            repository_url,
            requested_by,
            _job_id=job_id,
            _queue_name="vibestore:repository-index",
        )
    finally:
        await pool.aclose()
