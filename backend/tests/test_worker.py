from unittest.mock import AsyncMock

import pytest
from arq import Retry

from app.worker import MAX_ATTEMPTS, index_repository_job


class FakeSession:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_index_worker_marks_transient_failure_retrying(monkeypatch):
    session = FakeSession()

    def session_factory():
        return session

    monkeypatch.setattr("app.worker.SessionLocal", session_factory)

    async def fail_index(*args, **kwargs):
        raise RuntimeError("temporary GitHub outage")

    monkeypatch.setattr("app.worker.index_repository_snapshot", fail_index)

    with pytest.raises(Retry):
        await index_repository_job(
            {"job_try": 1}, "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12",
            "https://github.com/example/app", None,
        )

    assert session.rollback.await_count == 1
    assert session.commit.await_count == 2
    retry_update = session.execute.await_args_list[1].args[1]
    assert retry_update["status"] == "retrying"


@pytest.mark.asyncio
async def test_index_worker_stops_retrying_after_max_attempts(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("app.worker.SessionLocal", lambda: session)

    async def fail_index(*args, **kwargs):
        raise RuntimeError("permanent repository error")

    monkeypatch.setattr("app.worker.index_repository_snapshot", fail_index)

    with pytest.raises(RuntimeError, match="permanent repository error"):
        await index_repository_job(
            {"job_try": MAX_ATTEMPTS}, "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12",
            "https://github.com/example/app", None,
        )

    assert session.execute.await_count == 2
    assert session.commit.await_count == 2
    final_update = session.execute.await_args_list[1].args[1]
    assert final_update["status"] == "failed"
