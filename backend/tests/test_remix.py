import pytest

from app.services import remix


class FakeProvider:
    def __init__(self):
        self.prompt = None
        self.system = None

    async def generate(self, *, system, prompt):
        self.prompt = prompt
        self.system = system
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
    assert "src/File19.kt" in provider.prompt
    assert "src/File20.kt" not in provider.prompt
    assert "older" in provider.prompt
    assert "produce plans only" in provider.system
    assert "Add a biometric lock" in provider.prompt


@pytest.mark.asyncio
async def test_change_plan_requires_configured_provider(monkeypatch):
    monkeypatch.setattr(remix, "get_ai_provider", lambda: None)
    with pytest.raises(RuntimeError, match="not configured"):
        await remix.generate_change_plan(request="Change theme", files=[], history=[])



def test_remix_requests_bound_selected_source_context():
    from pydantic import ValidationError

    from app.schemas import RemixMessageCreateRequest, RemixPatchProposalCreateRequest

    message = RemixMessageCreateRequest(
        content="Add a settings screen",
        context_paths=["app/src/main/kotlin/MainActivity.kt"],
    )
    assert message.context_paths == ["app/src/main/kotlin/MainActivity.kt"]
    proposal = RemixPatchProposalCreateRequest(
        content="Add a settings screen",
        context_paths=["app/src/main/kotlin/MainActivity.kt"],
    )
    assert proposal.context_paths == message.context_paths
    with pytest.raises(ValidationError):
        RemixMessageCreateRequest(
            content="Add a settings screen",
            context_paths=["source.kt"] * 21,
        )
