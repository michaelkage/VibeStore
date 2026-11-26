import pytest
from pydantic import ValidationError

from app.auth import create_refresh_token, hash_refresh_token
from app.schemas import RefreshTokenRequest


def test_refresh_tokens_are_random_and_stored_as_sha256_hashes():
    token, token_hash = create_refresh_token()
    another_token, another_hash = create_refresh_token()

    assert len(token) >= 64
    assert token_hash == hash_refresh_token(token)
    assert token_hash != token
    assert another_token != token
    assert another_hash != token_hash
    assert len(token_hash) == 64


def test_refresh_request_rejects_short_tokens():
    with pytest.raises(ValidationError):
        RefreshTokenRequest(refresh_token="too-short")
