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



def test_apply_unified_diff_checks_context_and_produces_expected_source():
    source = 'class MainActivity {\n    fun title() = "Old"\n}\n'
    diff = (
        "--- a/app/src/MainActivity.kt\n"
        "+++ b/app/src/MainActivity.kt\n"
        "@@ -1,3 +1,3 @@\n"
        " class MainActivity {\n"
        '-    fun title() = "Old"\n'
        '+    fun title() = "New"\n'
        " }\n"
    )
    updated = remix_proposals.apply_unified_diff_to_text(
        source, diff, "app/src/MainActivity.kt",
    )
    assert updated == 'class MainActivity {\n    fun title() = "New"\n}\n'


def test_apply_unified_diff_rejects_context_that_does_not_match_pinned_source():
    source = 'class MainActivity {\n    fun title() = "Old"\n}\n'
    diff = (
        "--- a/app/src/MainActivity.kt\n"
        "+++ b/app/src/MainActivity.kt\n"
        "@@ -1,3 +1,3 @@\n"
        " class MainActivity {\n"
        '-    fun title() = "Different"\n'
        '+    fun title() = "New"\n'
        " }\n"
    )
    with pytest.raises(ValueError, match="context does not match"):
        remix_proposals.apply_unified_diff_to_text(
            source, diff, "app/src/MainActivity.kt",
        )


def test_apply_unified_diff_supports_insertions_at_start():
    diff = (
        "--- a/app/src/MainActivity.kt\n"
        "+++ b/app/src/MainActivity.kt\n"
        "@@ -0,0 +1 @@\n"
        "+// reviewed addition\n"
    )
    assert remix_proposals.apply_unified_diff_to_text(
        "class MainActivity\n", diff, "app/src/MainActivity.kt",
    ) == "// reviewed addition\nclass MainActivity\n"


def test_validate_patch_against_sources_reports_hashes_without_writing_files():
    path = FILES[0]["path"]
    proposal = remix_proposals.validate_proposal(
        _proposal(diff=(
            f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n"
            "-class MainActivity\n+class MainActivityV2\n"
        )),
        FILES,
    )
    source = "class MainActivity\n"
    report = remix_proposals.validate_patch_against_sources(
        proposal,
        {
            FILES[0]["path"]: {
                "content": source,
                "content_sha": "verified-git-blob",
                "size": len(source.encode("utf-8")),
            },
        },
    )
    assert report["status"] == "applicable"
    assert report["files"][0]["source_blob_sha"] == "verified-git-blob"
    assert len(report["files"][0]["result_sha256"]) == 64
    assert "No files were written" in report["message"]


def test_validate_patch_against_sources_rejects_missing_complete_source():
    proposal = remix_proposals.validate_proposal(_proposal(), FILES)
    with pytest.raises(ValueError, match="Complete pinned source is missing"):
        remix_proposals.validate_patch_against_sources(proposal, {})



def test_validate_patch_against_sources_rejects_noop_diffs():
    proposal = remix_proposals.validate_proposal(_proposal(), FILES)
    with pytest.raises(ValueError, match="does not change the source"):
        remix_proposals.validate_patch_against_sources(
            proposal,
            {
                FILES[0]["path"]: {
                    "content": "class MainActivity",
                    "content_sha": "verified-git-blob",
                    "size": len("class MainActivity"),
                },
            },
        )
