import io
import zipfile

import pytest

from app.patch_worker import _git_blob_sha, _safe_relative_path, build_patch_artifact


COMMIT = "a" * 40
PATH = "app/src/MainActivity.kt"
SOURCE = "class MainActivity\n"
DIFF = (
    f"--- a/{PATH}\n"
    f"+++ b/{PATH}\n"
    "@@ -1 +1 @@\n"
    "-class MainActivity\n"
    "+class MainActivityV2\n"
)


def _snapshot():
    raw = SOURCE.encode("utf-8")
    return {
        PATH: {
            "content": SOURCE,
            "content_sha": _git_blob_sha(raw),
            "size": len(raw),
        }
    }


def _proposal():
    return {"files": [{"path": PATH, "diff": DIFF}]}


def test_build_patch_artifact_contains_modified_source_and_provenance_manifest():
    archive_bytes, manifest = build_patch_artifact(_snapshot(), _proposal(), COMMIT)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.read(PATH).decode() == "class MainActivityV2\n"
        assert "VIBESTORE-MANIFEST.json" in archive.namelist()
    assert manifest["base_commit_sha"] == COMMIT
    assert manifest["source_revision_preserved"] is True
    assert manifest["files"][0]["source_git_blob_sha"] == _git_blob_sha(SOURCE.encode())
    assert manifest["files"][0]["result_sha256"]


def test_build_patch_artifact_rejects_mismatched_source_blob():
    snapshot = _snapshot()
    snapshot[PATH]["content_sha"] = "0" * 40
    with pytest.raises(ValueError, match="Git blob hash"):
        build_patch_artifact(snapshot, _proposal(), COMMIT)


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", "a\\b", "a/./b", "a/../b"])
def test_safe_relative_path_rejects_traversal(path):
    with pytest.raises(ValueError, match="Unsafe"):
        _safe_relative_path(path)


def test_build_patch_artifact_rejects_unapproved_file_set():
    proposal = {"files": [{"path": "other.kt", "diff": DIFF}]}
    with pytest.raises(ValueError):
        build_patch_artifact(_snapshot(), proposal, COMMIT)
