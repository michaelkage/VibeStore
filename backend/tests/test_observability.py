import httpx
import pytest
from fastapi import FastAPI

from app.observability import HTTP_REQUESTS, RequestObservabilityMiddleware


@pytest.mark.asyncio
async def test_request_middleware_echoes_safe_request_id_and_records_metrics():
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe", headers={"X-Request-ID": "trace-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace-123"
    assert HTTP_REQUESTS.labels("GET", "/probe", "200")._value.get() >= 1


@pytest.mark.asyncio
async def test_request_middleware_replaces_invalid_request_id():
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe", headers={"X-Request-ID": "bad\r\nid"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad\r\nid"
    assert 1 <= len(response.headers["x-request-id"]) <= 64
