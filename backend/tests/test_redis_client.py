from app.redis_client import _RATE_LIMIT_SCRIPT


def test_rate_limit_script_sets_expiry_only_for_new_counter():
    assert "redis.call('INCR'" in _RATE_LIMIT_SCRIPT
    assert "if count == 1 then" in _RATE_LIMIT_SCRIPT
    assert "redis.call('EXPIRE'" in _RATE_LIMIT_SCRIPT
