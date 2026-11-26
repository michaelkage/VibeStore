import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.api import router
from app.auth import get_current_user
from app.db import get_session


USER_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
JOB_ID = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def one(self):
        return self.row

    def first(self):
        return self.row

    def scalar_one_or_none(self):
        return self.scalar


@pytest.fixture
async def job_client(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session():
        yield session

    async def override_user():
        return {"id": USER_ID, "email": "dev@example.com", "created_at": datetime.now(UTC)}

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_async_indexing_endpoint_enqueues_and_returns_job(job_client, monkeypatch):
    client, session = job_client
    session.execute.return_value = FakeResult(row={
        "id": JOB_ID, "status": "queued", "repository_url": "https://github.com/example/app",
        "attempt_count": 0, "error": None, "app_id": None,
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC), "completed_at": None,
    })
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.enqueue_repository_index", enqueue)

    response = await client.post(
        "/api/v1/repositories/index-jobs",
        json={"repository_url": "https://github.com/example/app"},
    )

    assert response.status_code == 202
    assert response.json()["id"] == JOB_ID
    assert enqueue.await_count == 1
    assert enqueue.await_args.args[1:] == ("https://github.com/example/app", USER_ID)
    assert isinstance(enqueue.await_args.args[0], str)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "repository_url",
    [
        "https://gitlab.com/group/subgroup/project",
        "https://codeberg.org/example/android-app",
    ],
)
@pytest.mark.asyncio
async def test_async_indexing_accepts_supported_repository_forges(
    job_client,
    monkeypatch,
    repository_url,
):
    client, session = job_client
    session.execute.return_value = FakeResult(row={
        "id": JOB_ID,
        "status": "queued",
        "repository_url": repository_url,
        "attempt_count": 0,
        "error": None,
        "app_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "completed_at": None,
    })
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.enqueue_repository_index", enqueue)

    response = await client.post(
        "/api/v1/repositories/index-jobs",
        json={"repository_url": repository_url},
    )

    assert response.status_code == 202
    enqueue.assert_awaited_once()
    assert enqueue.await_args.args[1:] == (repository_url, USER_ID)


@pytest.mark.asyncio
async def test_github_webhook_verifies_signature_and_enqueues_default_branch(job_client, monkeypatch):
    client, session = job_client
    monkeypatch.setattr(
        "app.api.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="webhook-secret", github_token=None),
    )
    session.execute.side_effect = [
        FakeResult(scalar="delivery-123"),
        FakeResult(),
        FakeResult(),
    ]
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.enqueue_repository_index", enqueue)
    payload = {
        "deleted": False,
        "ref": "refs/heads/main",
        "repository": {
            "html_url": "https://github.com/example/app",
            "default_branch": "main",
        },
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-123",
        },
    )

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    enqueue.assert_awaited_once_with(response.json()["job_id"], "https://github.com/example/app", None)
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_github_webhook_rejects_invalid_signature(job_client, monkeypatch):
    client, session = job_client
    monkeypatch.setattr(
        "app.api.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="webhook-secret"),
    )
    response = await client.post(
        "/api/v1/webhooks/github",
        content=b'{"ref":"refs/heads/main"}',
        headers={
            "X-Hub-Signature-256": "sha256=" + ("0" * 64),
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-invalid",
        },
    )
    assert response.status_code == 401
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_github_webhook_delivery_is_idempotent(job_client, monkeypatch):
    client, session = job_client
    monkeypatch.setattr(
        "app.api.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="webhook-secret"),
    )
    session.execute.return_value = FakeResult(scalar=None)
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.enqueue_repository_index", enqueue)
    body = json.dumps({
        "deleted": False,
        "ref": "refs/heads/main",
        "repository": {"html_url": "https://github.com/example/app", "default_branch": "main"},
    }).encode()
    signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-duplicate",
        },
    )

    assert response.status_code == 202
    assert response.json()["duplicate"] is True
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_webhook_requeues_job_after_queue_outage(job_client, monkeypatch):
    client, session = job_client
    monkeypatch.setattr(
        "app.api.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="webhook-secret"),
    )
    session.execute.side_effect = [
        FakeResult(scalar=None),
        FakeResult(row={"id": JOB_ID, "status": "failed", "error": "Queue unavailable"}),
        FakeResult(),
    ]
    enqueue = AsyncMock()
    monkeypatch.setattr("app.api.enqueue_repository_index", enqueue)
    body = json.dumps({
        "deleted": False,
        "ref": "refs/heads/main",
        "repository": {"html_url": "https://github.com/example/app", "default_branch": "main"},
    }).encode()
    signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-redis-outage",
        },
    )

    assert response.status_code == 202
    assert response.json()["requeued"] is True
    enqueue.assert_awaited_once_with(JOB_ID, "https://github.com/example/app", None)
