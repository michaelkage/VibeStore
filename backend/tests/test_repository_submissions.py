from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.api import router
from app.auth import get_current_user
from app.db import get_session


USER_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
APP_ID = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    from unittest.mock import AsyncMock

    session = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session():
        yield session

    async def override_user():
        return {"id": USER_ID, "email": "dev@example.com", "created_at": datetime.now(UTC)}

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client, session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_my_repositories_returns_only_submission_rows(client):
    test_client, session = client
    now = datetime.now(UTC)
    session.execute.return_value = FakeResult([{
        "id": APP_ID,
        "name": "Example app",
        "description": "A sample",
        "repository_url": "https://github.com/example/app",
        "default_branch": "main",
        "latest_commit_sha": "a" * 40,
        "stars": 12,
        "submitted_at": now,
        "indexed_at": now,
    }])

    response = await test_client.get("/api/v1/repositories/mine")

    assert response.status_code == 200
    assert response.json()[0]["id"] == APP_ID
    assert response.json()[0]["name"] == "Example app"
    assert response.json()[0]["stars"] == 12
    assert "user_id" not in response.json()[0]
    assert session.execute.await_args.args[0].text.count("submissions.user_id") == 1


@pytest.mark.asyncio
async def test_remove_my_repository_deletes_only_ownership_link(client):
    test_client, session = client
    session.execute.return_value = FakeResult(scalar=UUID(APP_ID))

    response = await test_client.delete(f"/api/v1/repositories/mine/{APP_ID}")

    assert response.status_code == 204
    session.commit.assert_awaited_once()
    statement = session.execute.await_args.args[0].text
    assert "DELETE FROM repository_submissions" in statement
    assert "DELETE FROM apps" not in statement


@pytest.mark.asyncio
async def test_remove_unknown_or_unowned_repository_returns_404(client):
    test_client, session = client
    session.execute.return_value = FakeResult()

    response = await test_client.delete(f"/api/v1/repositories/mine/{APP_ID}")

    assert response.status_code == 404
    session.commit.assert_not_awaited()
