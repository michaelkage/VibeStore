import json
import logging
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from redis.exceptions import RedisError

from app.auth import get_current_user
from app.db import get_session
from app.services.github import fetch_repository_files_at_commit
from app.services.remix_proposals import validate_patch_against_sources
from app.patch_queue import enqueue_patch_job

router = APIRouter()


@router.post(
    "/remixes/{remix_id}/proposals/{proposal_id}/process",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["remix"],
)
async def process_approved_patch(
    remix_id: UUID,
    proposal_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Queue an approved diff for isolated, disposable source materialization."""
    result = await session.execute(text("""
        SELECT p.id::text AS proposal_id, p.status, p.base_commit_sha,
               p.proposal, p.source_files, p.validation_report, p.validation_status,
               rs.owner_id::text AS owner_id, rs.source_commit_sha,
               a.latest_commit_sha, a.repository_url
        FROM remix_patch_proposals p
        JOIN remix_sessions rs ON rs.id = p.session_id
        JOIN apps a ON a.id = rs.app_id
        WHERE p.id = CAST(:proposal_id AS uuid)
          AND p.session_id = CAST(:session_id AS uuid)
          AND rs.owner_id = CAST(:owner_id AS uuid)
    """), {
        "proposal_id": str(proposal_id),
        "session_id": str(remix_id),
        "owner_id": user["id"],
    })
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    if row["status"] != "approved" or row["validation_status"] != "applicable":
        raise HTTPException(status_code=409, detail="Only explicitly approved, verified proposals can be processed")
    if row["base_commit_sha"] != row["source_commit_sha"] or row["base_commit_sha"] != row["latest_commit_sha"]:
        raise HTTPException(status_code=409, detail="The original repository revision is no longer current")

    existing = await session.execute(text("""
        SELECT id::text AS id, status, error, created_at, completed_at
        FROM remix_patch_artifacts WHERE proposal_id = CAST(:proposal_id AS uuid)
    """), {"proposal_id": str(proposal_id)})
    existing_row = existing.mappings().first()
    if existing_row is not None:
        return dict(existing_row)

    try:
        sources = await fetch_repository_files_at_commit(
            row["repository_url"], row["base_commit_sha"], row["source_files"],
        )
        report = validate_patch_against_sources(row["proposal"], sources)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Pinned source could not be retrieved") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"Source verification failed: {str(exc)[:300]}") from exc

    expected = {item["path"]: item["result_sha256"] for item in row["validation_report"].get("files", [])}
    actual = {item["path"]: item["result_sha256"] for item in report["files"]}
    if not expected or expected != actual:
        raise HTTPException(status_code=409, detail="The source or resulting patch hashes differ from the approved validation")

    total_bytes = sum(item["size"] for item in sources.values())
    if total_bytes > 4_000_000:
        raise HTTPException(status_code=413, detail="Combined source snapshot exceeds the 4 MB processing limit")

    # Recheck the catalog commit after network retrieval to close the refresh race.
    latest = await session.execute(text("""
        SELECT a.latest_commit_sha
        FROM remix_sessions rs JOIN apps a ON a.id = rs.app_id
        WHERE rs.id = CAST(:session_id AS uuid)
          AND rs.owner_id = CAST(:owner_id AS uuid)
    """), {"session_id": str(remix_id), "owner_id": user["id"]})
    if latest.scalar_one_or_none() != row["base_commit_sha"]:
        raise HTTPException(status_code=409, detail="Repository changed while retrieving the pinned source")

    job_id = str(uuid4())
    await session.execute(text("""
        INSERT INTO remix_patch_artifacts (
            id, proposal_id, session_id, owner_id, base_commit_sha,
            status, source_snapshot, proposal_snapshot
        ) VALUES (
            CAST(:id AS uuid), CAST(:proposal_id AS uuid), CAST(:session_id AS uuid),
            CAST(:owner_id AS uuid), :commit_sha, 'queued',
            CAST(:sources AS jsonb), CAST(:proposal AS jsonb)
        )
        ON CONFLICT (proposal_id) DO NOTHING
    """), {
        "id": job_id,
        "proposal_id": str(proposal_id),
        "session_id": str(remix_id),
        "owner_id": user["id"],
        "commit_sha": row["base_commit_sha"],
        "sources": json.dumps(sources),
        "proposal": json.dumps(row["proposal"]),
    })
    await session.commit()

    saved = await session.execute(text("""
        SELECT id::text AS id, status, error, created_at, completed_at
        FROM remix_patch_artifacts WHERE proposal_id = CAST(:proposal_id AS uuid)
    """), {"proposal_id": str(proposal_id)})
    job = dict(saved.mappings().one())
    try:
        await enqueue_patch_job(job["id"])
    except RedisError:
        logging.getLogger(__name__).exception("Patch job enqueue failed; worker reconciliation will recover it")
    return job


@router.get(
    "/remixes/{remix_id}/proposals/{proposal_id}/artifact",
    tags=["remix"],
)
async def get_approved_patch_artifact(
    remix_id: UUID,
    proposal_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(text("""
        SELECT artifact.status, artifact.artifact_zip, artifact.error,
               artifact.manifest, artifact.base_commit_sha
        FROM remix_patch_artifacts artifact
        JOIN remix_sessions rs ON rs.id = artifact.session_id
        WHERE artifact.proposal_id = CAST(:proposal_id AS uuid)
          AND artifact.session_id = CAST(:session_id AS uuid)
          AND rs.owner_id = CAST(:owner_id AS uuid)
    """), {
        "proposal_id": str(proposal_id),
        "session_id": str(remix_id),
        "owner_id": user["id"],
    })
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Patch processing job not found")
    if row["status"] != "completed" or row["artifact_zip"] is None:
        return {
            "status": row["status"],
            "error": row["error"],
            "base_commit_sha": row["base_commit_sha"],
            "manifest": row["manifest"] or {},
        }
    return Response(
        content=bytes(row["artifact_zip"]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="vibestore-patch-{proposal_id}.zip"'},
    )
