import json

import pytest

from app.services import remix_proposals


FILES = [{"path": "app/src/MainActivity.kt", "content_sha": "abc123", "content_excerpt": "class MainActivity"}]


def _proposal(path="app/src/MainActivity.kt", diff=None):
    return json.dumps({
        "summary": "Add the requested UI behavior",
        "files": [{
            "path": path,
            "rationale": "This is the evidenced UI entry point.",
            "diff": diff or (
                f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-class MainActivity\n+class MainActivity"
            ),
        }],
        "risks": ["Existing navigation behavior may change."],
        "validation_steps": ["Run focused widget tests."],
    })


def test_validate_proposal_accepts_review_only_diff_for_indexed_path():
    result = remix_proposals.validate_proposal(_proposal(), FILES)
    assert result["files"][0]["path"] == FILES[0]["path"]
    assert result["summary"] == "Add the requested UI behavior"


@pytest.mark.parametrize("path", ["../secrets.env", "/etc/passwd", "app\\src\\Main.kt", "app//Main.kt"])
def test_validate_proposal_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        remix_proposals.validate_proposal(_proposal(path), FILES)


def test_validate_proposal_rejects_paths_outside_indexed_snapshot():
    with pytest.raises(ValueError, match="outside the indexed snapshot"):
        remix_proposals.validate_proposal(_proposal("app/src/Unindexed.kt"), FILES)


def test_validate_proposal_rejects_mismatched_or_missing_diff_headers():
    diff = "--- a/other.kt\n+++ b/other.kt\n@@ -1 +1 @@\n-old\n+new"
    with pytest.raises(ValueError, match="unified-diff"):
        remix_proposals.validate_proposal(_proposal(diff=diff), FILES)


def test_validate_proposal_rejects_empty_file_list_and_oversized_response():
    empty = json.dumps({"summary": "No evidence", "files": [], "risks": [], "validation_steps": []})
    with pytest.raises(ValueError, match="between 1 and 6"):
        remix_proposals.validate_proposal(empty, FILES)
    with pytest.raises(ValueError, match="too large"):
        remix_proposals.validate_proposal(" " * 40_001, FILES)


@pytest.mark.asyncio
async def test_generate_patch_proposal_requires_provider(monkeypatch):
    monkeypatch.setattr(remix_proposals, "get_ai_provider", lambda: None)
    with pytest.raises(RuntimeError, match="not configured"):
        await remix_proposals.generate_patch_proposal(request="Change theme", files=FILES)


@pytest.mark.asyncio
async def test_generate_patch_proposal_validates_provider_output(monkeypatch):
    class Provider:
        async def generate(self, *, system, prompt):
            assert "review-only" in system
            assert "app/src/MainActivity.kt" in prompt
            return _proposal()

    monkeypatch.setattr(remix_proposals, "get_ai_provider", lambda: Provider())
    result = await remix_proposals.generate_patch_proposal(request="Change theme", files=FILES)
    assert result["files"][0]["path"] == "app/src/MainActivity.kt"
