import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import ClassVar
from io import BytesIO

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.patch_queue import PATCH_QUEUE_NAME
from app.services.remix_proposals import apply_unified_diff_to_text

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_FILE_BYTES = 1_000_000
_MAX_TOTAL_BYTES = 4_000_000
_MAX_FILES = 6


def _git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\\0" + content,
        usedforsecurity=False,
    ).hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value or len(value) > 240 or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\\" in value or "\\0" in value
    ):
        raise ValueError("Unsafe patch path")
    return path


def build_patch_artifact(source_snapshot: dict, proposal: dict, base_commit_sha: str) -> tuple[bytes, dict]:
    """Apply only approved text diffs inside a fresh temporary workspace and zip the result."""
    if not _GIT_SHA_RE.fullmatch(base_commit_sha):
        raise ValueError("Invalid pinned commit SHA")
    if not 1 <= len(proposal.get("files", [])) <= _MAX_FILES:
        raise ValueError("Patch file count is outside the supported limit")
    if len(source_snapshot) != len(proposal["files"]):
        raise ValueError("Source snapshot does not exactly match the proposal file set")

    total = 0
    for path, item in source_snapshot.items():
        _safe_relative_path(path)
        raw = item["content"].encode("utf-8")
        total += len(raw)
        if len(raw) > _MAX_FILE_BYTES or item.get("size") != len(raw):
            raise ValueError("Source file size metadata is invalid")
        if _git_blob_sha(raw) != item.get("content_sha"):
            raise ValueError("Pinned Git blob hash verification failed")
    if total > _MAX_TOTAL_BYTES:
        raise ValueError("Combined source snapshot exceeds the processing limit")

    manifest_files = []
    with tempfile.TemporaryDirectory(prefix="vibestore-patch-") as temporary:
        root = Path(temporary).resolve()
        modified = {}
        for change in proposal["files"]:
            relative = _safe_relative_path(change["path"])
            source = source_snapshot.get(str(relative))
            if source is None:
                raise ValueError("Proposal path is absent from the verified source snapshot")
            updated = apply_unified_diff_to_text(source["content"], change["diff"], str(relative))
            updated_bytes = updated.encode("utf-8")
            if not updated_bytes or len(updated_bytes) > _MAX_FILE_BYTES:
                raise ValueError("Modified file is empty or exceeds the 1 MB limit")
            destination = root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = destination.parent.resolve()
            if root not in resolved_parent.parents and resolved_parent != root:
                raise ValueError("Patch path escaped the disposable workspace")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(updated_bytes)
                output.flush()
                os.fsync(output.fileno())
            modified[str(relative)] = updated
            manifest_files.append({
                "path": str(relative),
                "source_git_blob_sha": source["content_sha"],
                "source_sha256": hashlib.sha256(source["content"].encode("utf-8")).hexdigest(),
                "result_sha256": hashlib.sha256(updated_bytes).hexdigest(),
                "result_bytes": len(updated_bytes),
            })

        manifest = {
            "format": "vibestore-modified-source-v1",
            "base_commit_sha": base_commit_sha,
            "source_revision_preserved": True,
            "files": manifest_files,
            "limitations": [
                "Only changed files are included; this is not a complete repository checkout.",
                "No repository code, scripts, Gradle tasks or build tools were executed.",
                "The original Git revision was not modified and no GitHub write was performed.",
                "Review the artifact before any separate build or apply action.",
            ],
        }
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in modified.items():
                archive.writestr(path, content)
            archive.writestr("VIBESTORE-MANIFEST.json", json.dumps(manifest, indent=2))
        return buffer.getvalue(), manifest


async def process_approved_patch(ctx, job_id: str):
    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT artifact.id::text AS id, artifact.status, artifact.base_commit_sha,
                   artifact.source_snapshot, artifact.proposal_snapshot,
                   proposal.status AS proposal_status, proposal.validation_status,
                   apps.latest_commit_sha
            FROM remix_patch_artifacts artifact
            JOIN remix_patch_proposals proposal ON proposal.id = artifact.proposal_id
            JOIN remix_sessions rs ON rs.id = artifact.session_id
            JOIN apps ON apps.id = rs.app_id
            WHERE artifact.id = CAST(:id AS uuid)
            FOR UPDATE OF artifact
        """), {"id": job_id})
        row = result.mappings().first()
        if row is None:
            return {"status": "missing"}
        if row["status"] == "completed":
            return {"status": "completed"}
        if row["status"] not in {"queued", "running"}:
            return {"status": row["status"]}
        if (
            row["proposal_status"] != "approved"
            or row["validation_status"] != "applicable"
            or row["latest_commit_sha"] != row["base_commit_sha"]
        ):
            await session.execute(text("""
                UPDATE remix_patch_artifacts SET status = 'failed',
                    error = 'Approval, validation or pinned source revision is no longer valid',
                    source_snapshot = '{}'::jsonb, updated_at = now()
                WHERE id = CAST(:id AS uuid)
            """), {"id": job_id})
            await session.commit()
            return {"status": "failed"}
        await session.execute(text("""
            UPDATE remix_patch_artifacts SET status = 'running', error = NULL, updated_at = now()
            WHERE id = CAST(:id AS uuid)
        """), {"id": job_id})
        await session.commit()

        try:
            artifact_zip, manifest = build_patch_artifact(
                row["source_snapshot"], row["proposal_snapshot"], row["base_commit_sha"],
            )
            if len(artifact_zip) > 8_000_000:
                raise ValueError("Review artifact exceeds the 8 MB storage limit")
            # Recheck revision after processing before publishing the artifact.
            current = await session.execute(text("""
                SELECT latest_commit_sha FROM apps
                WHERE id = (SELECT app_id FROM remix_sessions WHERE id = (
                    SELECT session_id FROM remix_patch_artifacts WHERE id = CAST(:id AS uuid)
                ))
            """), {"id": job_id})
            if current.scalar_one_or_none() != row["base_commit_sha"]:
                raise ValueError("Repository revision changed while the patch was being processed")
            await session.execute(text("""
                UPDATE remix_patch_artifacts
                SET status = 'completed', artifact_zip = :artifact_zip,
                    manifest = CAST(:manifest AS jsonb), source_snapshot = '{}'::jsonb,
                    error = NULL, completed_at = now(), updated_at = now()
                WHERE id = CAST(:id AS uuid) AND status = 'running'
            """), {
                "id": job_id,
                "artifact_zip": artifact_zip,
                "manifest": json.dumps(manifest),
            })
            await session.commit()
            return {"status": "completed", "files": len(manifest["files"])}
        except Exception as exc:
            await session.rollback()
            await session.execute(text("""
                UPDATE remix_patch_artifacts SET status = 'failed',
                    error = :error, source_snapshot = '{}'::jsonb, updated_at = now()
                WHERE id = CAST(:id AS uuid)
            """), {"id": job_id, "error": str(exc)[:1000]})
            await session.commit()
            raise


async def reconcile_patch_jobs(ctx):
    from arq import create_pool

    async with SessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT id::text AS id FROM remix_patch_artifacts
            WHERE status = 'queued' ORDER BY created_at LIMIT 50
        """))).mappings().all()
    if not rows:
        return
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        for row in rows:
            await pool.enqueue_job(
                "process_approved_patch", row["id"],
                _job_id=row["id"], _queue_name=PATCH_QUEUE_NAME,
            )
    finally:
        await pool.aclose()


async def shutdown(ctx):
    await dispose_engine()


class PatchWorkerSettings:
    functions: ClassVar[list] = [process_approved_patch]
    cron_jobs: ClassVar[list] = [cron(reconcile_patch_jobs, minute=set(range(60)), run_at_startup=True)]
    queue_name = PATCH_QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_shutdown = shutdown
    max_jobs = 1
    job_timeout = 120
    max_tries = 1
    keep_result = 3600
