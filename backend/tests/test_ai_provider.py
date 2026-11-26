from unittest.mock import AsyncMock

import pytest

from app.ai import openai_compatible


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", "https://ai.example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class FakeClient:
    responses = []
    calls = 0

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        return type(self).responses.pop(0)


def _provider():
    provider = openai_compatible.OpenAICompatibleProvider.__new__(
        openai_compatible.OpenAICompatibleProvider
    )
    provider.base_url = "https://ai.example.test/v1"
    provider.api_key = "secret"
    provider.model = "chat-model"
    provider.embedding_model = "embedding-model"
    provider.timeout = 30
    provider.max_retries = 2
    return provider


@pytest.mark.asyncio
async def test_generate_retries_transient_status_and_returns_validated_content(monkeypatch):
    FakeClient.responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "0"}),
        FakeResponse({"choices": [{"message": {"content": "  Plan ready  "}}]}),
    ]
    FakeClient.calls = 0
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", FakeClient)
    sleep = AsyncMock()
    monkeypatch.setattr(openai_compatible.asyncio, "sleep", sleep)

    result = await _provider().generate(system="system", prompt="prompt")

    assert result == "Plan ready"
    assert FakeClient.calls == 2
    sleep.assert_awaited_once_with(0.1)


@pytest.mark.asyncio
async def test_embed_sorts_results_and_rejects_inconsistent_vectors(monkeypatch):
    FakeClient.responses = [
        FakeResponse({
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        })
    ]
    FakeClient.calls = 0
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", FakeClient)

    assert await _provider().embed(["first", "second"]) == [
        [0.1, 0.2],
        [0.3, 0.4],
    ]


@pytest.mark.asyncio
async def test_embed_rejects_invalid_provider_dimensions(monkeypatch):
    FakeClient.responses = [
        FakeResponse({
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3]},
            ]
        })
    ]
    FakeClient.calls = 0
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="inconsistent embedding dimensions"):
        await _provider().embed(["first", "second"])


@pytest.mark.asyncio
async def test_generate_rejects_empty_completion(monkeypatch):
    FakeClient.responses = [FakeResponse({"choices": [{"message": {"content": " "}}]})]
    FakeClient.calls = 0
    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="empty chat completion"):
        await _provider().generate(system="system", prompt="prompt")
