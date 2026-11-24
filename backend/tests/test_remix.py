import pytest

from app.services import remix


class FakeProvider:
    def __init__(self):
        self.prompt = None

    async def generate(self, *, system, prompt):
        self.prompt = prompt
        return "## Plan\n1. Update the evidenced UI."

    async def embed(self, texts):
        return []


@pytest.mark.asyncio
async def test_change_plan_uses_bounded_context_and_never_requests_execution(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(remix, "get_ai_provider", lambda: provider)
    files = [
        {"path": f"src/File{i}.kt", "content_excerpt": "x" * 9000}
        for i in range(20)
    ]
    history = [{"role": "user", "content": "older" * 1000}] * 20

    result = await remix.generate_change_plan(
        request="Add a biometric lock", files=files, history=history
    )

    assert result.startswith("## Plan")
    assert "src/File11.kt" in provider.prompt
    assert "src/File12.kt" not in provider.prompt
    assert "older" in provider.prompt
    assert "You produce plans only" in provider.prompt or "produce plans only" in provider.prompt
    assert "Add a biometric lock" in provider.prompt


@pytest.mark.asyncio
async def test_change_plan_requires_configured_provider(monkeypatch):
    monkeypatch.setattr(remix, "get_ai_provider", lambda: None)
    with pytest.raises(RuntimeError, match="not configured"):
        await remix.generate_change_plan(request="Change theme", files=[], history=[])
