from app.redis_client import _RATE_LIMIT_SCRIPT


def test_rate_limit_script_sets_expiry_only_for_new_counter():
    assert "redis.call('INCR'" in _RATE_LIMIT_SCRIPT
    assert "if count == 1 then" in _RATE_LIMIT_SCRIPT
    assert "redis.call('EXPIRE'" in _RATE_LIMIT_SCRIPT



class FakeRedis:
    def __init__(self, count):
        self.count = count
        self.calls = []

    async def eval(self, script, key_count, key, expiry):
        self.calls.append((script, key_count, key, expiry))
        return self.count


async def test_remix_rate_limit_uses_user_scoped_hour_window(monkeypatch):
    import app.redis_client as redis_client

    fake = FakeRedis(12)
    monkeypatch.setattr(redis_client, "_client", fake)
    await redis_client.enforce_remix_rate_limit("user-123")
    assert fake.calls[0][2:] == ("vibestore:remix-rate:user-123", 3600)


async def test_remix_rate_limit_rejects_excessive_requests(monkeypatch):
    import pytest
    from fastapi import HTTPException
    import app.redis_client as redis_client

    monkeypatch.setattr(redis_client, "_client", FakeRedis(31))
    with pytest.raises(HTTPException) as error:
        await redis_client.enforce_remix_rate_limit("user-123")
    assert error.value.status_code == 429
