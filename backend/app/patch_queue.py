from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings

PATCH_QUEUE_NAME = "vibestore:patch-processing"


async def enqueue_patch_job(job_id: str) -> bool:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        result = await pool.enqueue_job(
            "process_approved_patch",
            job_id,
            _job_id=job_id,
            _queue_name=PATCH_QUEUE_NAME,
        )
        return result is not None
    finally:
        await pool.aclose()
