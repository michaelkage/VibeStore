from fastapi import HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings

_client: Redis | None = None
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


async def init_redis() -> None:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def enforce_auth_rate_limit(request: Request) -> None:
    if _client is None:
        raise HTTPException(status_code=503, detail="Authentication rate limiter is unavailable")
    client_ip = request.client.host if request.client else "unknown"
    key = f"vibestore:auth-rate:{request.url.path}:{client_ip}"
    try:
        count = int(await _client.eval(_RATE_LIMIT_SCRIPT, 1, key, 900))
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Authentication rate limiter is unavailable") from exc
    if count > 10:
        raise HTTPException(status_code=429, detail="Too many authentication attempts; retry later")


async def redis_is_healthy() -> bool:
    if _client is None:
        return False
    try:
        return bool(await _client.ping())
    except RedisError:
        return False


async def enforce_remix_rate_limit(user_id: str) -> None:
    """Limit expensive AI planning calls to 30 per account per rolling hour."""
    if _client is None:
        raise HTTPException(status_code=503, detail="AI request rate limiter is unavailable")
    key = f"vibestore:remix-rate:{user_id}"
    try:
        count = int(await _client.eval(_RATE_LIMIT_SCRIPT, 1, key, 3600))
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="AI request rate limiter is unavailable") from exc
    if count > 30:
        raise HTTPException(status_code=429, detail="Remix planning limit reached; retry in an hour")
