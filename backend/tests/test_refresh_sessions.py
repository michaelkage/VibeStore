from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app import api, auth
from app.db import get_session


USER_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


class MappingRows:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return MappingRows(self.row)


@pytest.fixture
def auth_settings(monkeypatch):
    settings = SimpleNamespace(
        jwt_secret_key="s" * 48,
        jwt_issuer="vibestore-api",
        jwt_access_token_minutes=30,
        jwt_refresh_token_days=30,
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    return settings


@pytest.fixture
async def refresh_client(monkeypatch):
    session = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    async def override_session():
        yield session

    async def no_rate_limit():
        return None

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[api.enforce_auth_rate_limit] = no_rate_limit
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client, session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_refresh_rotates_hashed_token_and_issues_new_session(
    refresh_client,
    auth_settings,
):
    client, session = refresh_client
    session.execute.side_effect = [
        FakeResult({"user_id": USER_ID}),
        FakeResult({
            "id": USER_ID,
            "email": "user@example.com",
            "created_at": datetime.now(UTC),
        }),
        FakeResult(),
        FakeResult(),
    ]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "r" * 64},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["refresh_token"] != "r" * 64
    assert payload["user"]["id"] == USER_ID
    assert session.execute.await_count == 4
    assert session.commit.await_count == 1
    assert session.rollback.await_count == 0


@pytest.mark.asyncio
async def test_refresh_rejects_replayed_or_expired_token(refresh_client, auth_settings):
    client, session = refresh_client
    session.execute.return_value = FakeResult()

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "r" * 64},
    )

    assert response.status_code == 401
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
