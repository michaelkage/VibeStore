import asyncio
import math

import httpx

from app.ai.base import AIProvider
from app.config import get_settings

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class OpenAICompatibleProvider(AIProvider):
    """Adapter for OpenAI-compatible hosted and self-hosted inference endpoints."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ai_base_url or not settings.ai_api_key or not settings.ai_model:
            raise RuntimeError("AI_BASE_URL, AI_API_KEY and AI_MODEL are required")
        self.base_url = settings.ai_base_url.rstrip("/")
        self.api_key = settings.ai_api_key
        self.model = settings.ai_model
        self.embedding_model = settings.ai_embedding_model
        self.timeout = httpx.Timeout(
            settings.ai_request_timeout_seconds,
            connect=min(10, settings.ai_request_timeout_seconds),
        )
        self.max_retries = settings.ai_max_retries

    async def _post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, json=payload)
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(10.0, max(0.1, float(retry_after))) if retry_after else 0.5 * (2**attempt)
                    except ValueError:
                        delay = 0.5 * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError("AI provider returned invalid JSON") from exc
                if not isinstance(data, dict):
                    raise TypeError("AI provider returned an unexpected response shape")
                return data
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError("AI provider request exhausted its retry budget")

    async def generate(self, *, system: str, prompt: str) -> str:
        data = await self._post_json(
            "chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("AI provider returned no chat completion choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("AI provider returned an empty chat completion")
        return content.strip()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_model:
            raise RuntimeError("AI_EMBEDDING_MODEL is not configured")
        if not texts or len(texts) > 64:
            raise ValueError("Embedding batch size must be between 1 and 64")
        data = await self._post_json(
            "embeddings",
            {"model": self.embedding_model, "input": texts},
        )
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise RuntimeError("AI provider returned an unexpected embedding count")
        if any(
            not isinstance(item, dict) or not isinstance(item.get("index"), int)
            for item in items
        ):
            raise RuntimeError("AI provider returned invalid embedding indexes")
        ordered = sorted(items, key=lambda item: item["index"])
        if [item["index"] for item in ordered] != list(range(len(texts))):
            raise RuntimeError("AI provider returned duplicate or missing embedding indexes")

        embeddings = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector or len(vector) > 8192:
                raise RuntimeError("AI provider returned an invalid embedding vector")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in vector
            ):
                raise RuntimeError("AI provider returned a non-finite embedding value")
            embeddings.append([float(value) for value in vector])
        dimensions = {len(vector) for vector in embeddings}
        if len(dimensions) != 1:
            raise RuntimeError("AI provider returned inconsistent embedding dimensions")
        return embeddings


def get_ai_provider() -> AIProvider | None:
    settings = get_settings()
    if settings.ai_provider == "none":
        return None
    if settings.ai_provider in {"openai-compatible", "openai"}:
        return OpenAICompatibleProvider()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
