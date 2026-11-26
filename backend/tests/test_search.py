import math
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api import _catalog_order_by, _serialize_embedding, router
from app.auth import get_current_user
from app.db import get_session


USER_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
APP_ID = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def catalog_client():
    from unittest.mock import AsyncMock

    session = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(return_value=1),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_session():
        yield session

    async def override_user():
        return {
            "id": USER_ID,
            "email": "dev@example.com",
            "created_at": datetime.now(UTC),
        }

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as test_client:
        yield test_client, session
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("popular", "stars DESC, name ASC"),
        ("recent", "indexed_at DESC NULLS LAST, name ASC"),
        ("name", "name ASC"),
    ],
)
def test_catalog_sort_uses_fixed_sql_expressions(sort, expected):
    assert _catalog_order_by(sort) == expected


def test_catalog_sort_rejects_unrecognized_values():
    with pytest.raises(HTTPException) as error:
        _catalog_order_by("stars; DROP TABLE apps")
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_catalog_returns_apps_and_pagination_metadata(catalog_client):
    client, session = catalog_client
    session.execute.return_value = FakeResult(
        [
            {
                "id": APP_ID,
                "name": "Example app",
                "description": "A sample Android app",
                "repository_url": "https://github.com/example/app",
                "stars": 42,
                "license": "MIT",
                "latest_commit_sha": "a" * 40,
                "indexed_at": datetime.now(UTC),
            }
        ]
    )

    response = await client.get(
        "/api/v1/catalog",
        params={"sort": "popular", "limit": 10, "offset": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 10
    assert payload["offset"] == 20
    assert payload["items"][0]["id"] == APP_ID
    assert payload["items"][0]["stars"] == 42
    assert session.execute.await_count == 1
    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_catalog_rejects_unsafe_sort_before_query(catalog_client):
    client, session = catalog_client
    response = await client.get(
        "/api/v1/catalog",
        params={"sort": "stars; DROP TABLE apps"},
    )
    assert response.status_code == 422
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_rejects_one_character_search(catalog_client):
    client, session = catalog_client
    response = await client.get("/api/v1/catalog", params={"query": "x"})
    assert response.status_code == 422
    session.execute.assert_not_awaited()


def test_embedding_serializes_as_pgvector_literal():
    assert _serialize_embedding([0.25, -0.5, 1.0]) == "[0.25,-0.5,1]"


@pytest.mark.parametrize("values", [[], [math.nan], [math.inf], [-math.inf]])
def test_embedding_rejects_empty_or_non_finite_values(values):
    with pytest.raises(ValueError):
        _serialize_embedding(values)


def test_embedding_rejects_unreasonably_large_dimensions():
    with pytest.raises(ValueError):
        _serialize_embedding([0.0] * 8193)



def test_search_request_validates_catalog_filters():
    from pydantic import ValidationError

    from app.schemas import SearchRequest

    assert SearchRequest(
        query="offline notes",
        license="MIT",
        min_stars=10,
    ).min_stars == 10
    with pytest.raises(ValidationError):
        SearchRequest(query="offline notes", min_stars=-1)
    with pytest.raises(ValidationError):
        SearchRequest(query="offline notes", license="")



@pytest.mark.asyncio
async def test_repository_file_browser_returns_paths_and_pagination(catalog_client):
    client, session = catalog_client
    session.execute.return_value = FakeResult(
        [
            {
                "id": APP_ID,
                "path": "app/src/main/kotlin/MainActivity.kt",
                "language": "kotlin",
                "content_sha": "a" * 40,
                "content_excerpt": "class MainActivity",
                "indexed_at": datetime.now(UTC),
            }
        ]
    )
    response = await client.get(
        f"/api/v1/apps/{APP_ID}/files",
        params={"query": "MainActivity", "limit": 25, "offset": 5},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 25
    assert payload["offset"] == 5
    assert payload["items"][0]["path"].endswith("MainActivity.kt")
    assert session.execute.await_count == 1
    assert session.scalar.await_count == 1



def test_user_library_app_schema_exposes_favorite_and_recent_activity():
    from datetime import UTC, datetime

    from app.schemas import UserLibraryApp

    now = datetime.now(UTC)
    item = UserLibraryApp(
        id=APP_ID,
        name="Example",
        repository_url="https://github.com/example/app",
        stars=5,
        favorited_at=now,
        last_opened_at=now,
    )
    assert item.favorited_at == now
    assert item.last_opened_at == now
