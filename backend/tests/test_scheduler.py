from unittest.mock import AsyncMock

import pytest

from app.scheduler import reconcile_catalog


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def one(self):
        if len(self.rows) != 1:
            raise AssertionError(f"Expected one row, received {len(self.rows)}")
        return self.rows[0]

    def __iter__(self):
        return iter(self.rows)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return FakeMappings(self.rows)

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar


class FakeSession:
    def __init__(self):
        self.execute = AsyncMock(side_effect=[
            FakeResult(rows=[{"id": "recovered", "repository_url": "https://github.com/a/b"}]),
            FakeResult(rows=[]),
            FakeResult(rows=[{"id": "app-1", "repository_url": "https://github.com/c/d"}]),
            FakeResult(scalar=True),
            FakeResult(scalar=None),
            FakeResult(rows=[{
                "id": "scheduled-1",
                "repository_url": "https://github.com/c/d",
                "requested_by": None,
            }]),
        ])
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_reconcile_recovers_jobs_and_schedules_stale_catalog(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("app.scheduler.SessionLocal", lambda: session)
    monkeypatch.setattr(
        "app.scheduler.get_settings",
        lambda: type("Settings", (), {
            "indexing_stale_job_minutes": 15,
            "indexing_reconcile_batch_size": 100,
            "catalog_refresh_interval_days": 7,
            "catalog_refresh_batch_size": 50,
        })(),
    )
    enqueue = AsyncMock(return_value=2)
    monkeypatch.setattr("app.scheduler.enqueue_repository_indices", enqueue)

    result = await reconcile_catalog()

    assert result == {"scheduled": 1, "recovered": 1, "enqueued": 2, "candidates": 1}
    assert enqueue.await_count == 1
    jobs = enqueue.await_args.args[0]
    assert {job["id"] for job in jobs} == {"recovered", "scheduled-1"}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_leaves_queued_jobs_for_next_tick_when_redis_is_down(monkeypatch):
    session = FakeSession()
    session.execute = AsyncMock(side_effect=[
        FakeResult(),
        FakeResult(rows=[{
            "id": "queued-1",
            "repository_url": "https://github.com/a/b",
            "requested_by": None,
        }]),
        FakeResult(),
    ])
    monkeypatch.setattr("app.scheduler.SessionLocal", lambda: session)
    monkeypatch.setattr(
        "app.scheduler.get_settings",
        lambda: type("Settings", (), {
            "indexing_stale_job_minutes": 15,
            "indexing_reconcile_batch_size": 100,
            "catalog_refresh_interval_days": 7,
            "catalog_refresh_batch_size": 50,
        })(),
    )
    enqueue = AsyncMock(side_effect=RuntimeError("Redis unavailable"))
    monkeypatch.setattr("app.scheduler.enqueue_repository_indices", enqueue)

    result = await reconcile_catalog()

    assert result == {"scheduled": 0, "recovered": 0, "enqueued": 0, "candidates": 0}
    enqueue.assert_awaited_once()
    session.commit.assert_awaited_once()
