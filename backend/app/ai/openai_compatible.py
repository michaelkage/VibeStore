import httpx
from app.ai.base import AIProvider
from app.config import get_settings

class OpenAICompatibleProvider(AIProvider):
    """Adapter for OpenAI-compatible hosted and self-hosted inference endpoints."""
    def __init__(self) -> None:
        s = get_settings()
        if not s.ai_base_url or not s.ai_api_key or not s.ai_model:
            raise RuntimeError("AI_BASE_URL, AI_API_KEY and AI_MODEL are required")
        self.base_url, self.api_key, self.model = s.ai_base_url.rstrip("/"), s.ai_api_key, s.ai_model
        self.embedding_model = s.ai_embedding_model

    async def generate(self, *, system: str, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_model:
            raise RuntimeError("AI_EMBEDDING_MODEL is not configured")
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.embedding_model, "input": texts})
            r.raise_for_status()
            return [v["embedding"] for v in sorted(r.json()["data"], key=lambda x: x["index"])]

def get_ai_provider() -> AIProvider | None:
    s = get_settings()
    if s.ai_provider == "none":
        return None
    if s.ai_provider in {"openai-compatible", "openai"}:
        return OpenAICompatibleProvider()
    raise RuntimeError(f"Unsupported AI_PROVIDER: {s.ai_provider}")
