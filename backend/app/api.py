import asyncio
import hashlib
import hmac
import json
import math
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_compatible import get_ai_provider
from app.auth import (
    _DUMMY_PASSWORD_HASH,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.db import get_session
from app.redis_client import enforce_auth_rate_limit, enforce_remix_rate_limit
from app.queue import enqueue_repository_index
from app.schemas import (
    InspectionResponse,
    IndexRepositoryResponse,
    LoginRequest,
    ManifestFinding,
    RegisterRequest,
    RepositoryRequest,
    RepositorySubmissionResponse,
    RepositoryIndexJobResponse,
    SearchRequest,
    SearchResult,
    TokenResponse,
    UserResponse,
    RemixSessionCreateRequest,
    RemixMessageCreateRequest,
    RemixSessionResponse,
    RemixMessageResponse,
)
from app.services.architecture import detect_declared_sdks, inspect_manifest_flags
from app.services.github import fetch_repository_files, fetch_repository_snapshot, parse_github_url
from app.services.manifest import inspect_manifest
from app.services.remix import generate_change_plan

router = APIRouter()


def _serialize_embedding(values: list[float]) -> str:
    if not values or len(values) > 8192:
        raise ValueError("Embedding dimensions are outside the supported range")
    normalized = [float(value) for value in values]
    if not all(math.isfinite(value) for value in normalized):
        raise ValueError("Embedding contains a non-finite value")
    return "[" + ",".join(format(value, ".9g") for value in normalized) + "]"


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["authentication"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    email = payload.email.strip().lower()
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        result = await session.execute(
            text("""
                INSERT INTO users (email, password_hash)
                VALUES (:email, :password_hash)
                RETURNING id::text AS id, email, created_at
            """),
            {"email": email, "password_hash": password_hash},
        )
        user = result.mappings().one()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from None
    user_response = UserResponse(**dict(user))
    return TokenResponse(
        access_token=create_access_token(user_response.id),
        expires_in=settings.jwt_access_token_minutes * 60,
        user=user_response,
    )


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["authentication"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    result = await session.execute(
        text("""
            SELECT id::text AS id, email, password_hash, created_at
            FROM users WHERE email = :email AND disabled = false
        """),
        {"email": payload.email.strip().lower()},
    )
    user = result.mappings().first()
    candidate_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = await asyncio.to_thread(verify_password, payload.password, candidate_hash)
    if user is None or not password_valid:
        raise HTTPException(status_code=401, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    user_response = UserResponse(id=user["id"], email=user["email"], created_at=user["created_at"])
    return TokenResponse(
        access_token=create_access_token(user_response.id),
        expires_in=settings.jwt_access_token_minutes * 60,
        user=user_response,
    )


@router.get("/auth/me", response_model=UserResponse, tags=["authentication"])
async def get_me(user=Depends(get_current_user)):
    return UserResponse(**user)


@router.post(
    "/repositories/index",
    response_model=IndexRepositoryResponse,
    status_code=status.HTTP_200_OK,
    tags=["discovery"],
)
async def index_repository(
    payload: RepositoryRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        snapshot = await fetch_repository_snapshot(str(payload.repository_url))
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=f"Repository could not be indexed: {exc}") from exc

    readme = next(
        (item["content"] for item in snapshot["files"] if item["path"].lower() in {"readme.md", "readme"}),
        None,
    )
    description = snapshot["description"] or (readme[:500] if readme else None)
    manifest_xml = next(
        (item["content"] for item in snapshot["files"] if item["path"].endswith("AndroidManifest.xml")),
        None,
    )
    package_name = None
    if manifest_xml is not None:
        try:
            package_name = inspect_manifest(manifest_xml)["package_name"]
        except ValueError:
            package_name = None
    embedding_literal = None
    embedding_model = None
    settings = get_settings()
    if settings.ai_provider != "none" and settings.ai_embedding_model:
        try:
            provider = get_ai_provider()
            if provider is not None:
                source_text = " ".join(
                    [snapshot["name"], description or "", *(item["content"] for item in snapshot["files"])]
                )[:12_000]
                vectors = await provider.embed([source_text])
                if len(vectors) != 1:
                    raise ValueError("Embedding provider returned an unexpected result count")
                embedding_literal = _serialize_embedding(vectors[0])
                embedding_model = settings.ai_embedding_model
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Repository embedding is temporarily unavailable") from exc

    result = await session.execute(
        text("""
            INSERT INTO apps (
                package_name, name, description, repository_url, default_branch, stars,
                license, latest_commit_sha, indexed_at, embedding, embedding_model
            )
            VALUES (
                :package_name, :name, :description, :repository_url, :default_branch, :stars,
                :license, :commit_sha, now(), CAST(:embedding AS vector), :embedding_model
            )
            ON CONFLICT (repository_url) DO UPDATE SET
                package_name = COALESCE(EXCLUDED.package_name, apps.package_name),
                name = EXCLUDED.name,
                description = COALESCE(EXCLUDED.description, apps.description),
                default_branch = EXCLUDED.default_branch,
                stars = EXCLUDED.stars,
                license = EXCLUDED.license,
                latest_commit_sha = EXCLUDED.latest_commit_sha,
                indexed_at = now(),
                updated_at = now(),
                embedding = COALESCE(EXCLUDED.embedding, apps.embedding),
                embedding_model = COALESCE(EXCLUDED.embedding_model, apps.embedding_model)
            RETURNING id::text AS id
        """),
        {
            "package_name": package_name,
            "name": snapshot["name"],
            "description": description,
            "repository_url": snapshot["repository_url"],
            "default_branch": snapshot["default_branch"],
            "stars": snapshot["stars"],
            "license": snapshot["license"],
            "commit_sha": snapshot["commit_sha"],
            "embedding": embedding_literal,
            "embedding_model": embedding_model,
        },
    )
    app_id = result.scalar_one()

    # A refresh represents the current bounded snapshot; remove stale paths/hashes first.
    await session.execute(
        text("DELETE FROM repository_files WHERE app_id = CAST(:app_id AS uuid)"),
        {"app_id": app_id},
    )

    for item in snapshot["files"]:
        suffix = item["path"].rsplit(".", 1)[-1].lower() if "." in item["path"] else ""
        language = {
            "xml": "xml",
            "md": "markdown",
            "gradle": "gradle",
            "kts": "kotlin",
        }.get(suffix)
        await session.execute(
            text("""
                INSERT INTO repository_files (
                    app_id, path, content_sha, language, content_excerpt, indexed_at
                )
                VALUES (
                    CAST(:app_id AS uuid), :path, :content_sha, :language, :content_excerpt, now()
                )
                ON CONFLICT (app_id, path, content_sha) DO UPDATE SET
                    content_excerpt = EXCLUDED.content_excerpt,
                    indexed_at = now()
            """),
            {
                "app_id": app_id,
                "path": item["path"],
                "content_sha": item["content_sha"],
                "language": language,
                "content_excerpt": item["content"][:20_000],
            },
        )

    await session.execute(
        text("""
            INSERT INTO repository_submissions (user_id, app_id)
            VALUES (CAST(:user_id AS uuid), CAST(:app_id AS uuid))
            ON CONFLICT (user_id, app_id) DO UPDATE SET submitted_at = now()
        """),
        {"user_id": user["id"], "app_id": app_id},
    )
    await session.commit()
    return IndexRepositoryResponse(
        id=app_id,
        name=snapshot["name"],
        repository_url=snapshot["repository_url"],
        default_branch=snapshot["default_branch"],
        latest_commit_sha=snapshot["commit_sha"],
        stars=snapshot["stars"],
        indexed_files=len(snapshot["files"]),
    )


@router.post(
    "/repositories/index-jobs",
    response_model=RepositoryIndexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["discovery"],
)
async def enqueue_repository_index_job(
    payload: RepositoryRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repository_url = str(payload.repository_url)
    try:
        parse_github_url(repository_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = str(uuid4())
    result = await session.execute(
        text("""
            INSERT INTO repository_index_jobs (id, repository_url, requested_by, source)
            VALUES (CAST(:id AS uuid), :repository_url, CAST(:user_id AS uuid), 'api')
            RETURNING id::text AS id, status, repository_url, attempt_count, error,
                      app_id::text AS app_id, created_at, updated_at, completed_at
        """),
        {"id": job_id, "repository_url": repository_url, "user_id": user["id"]},
    )
    job = dict(result.mappings().one())
    await session.commit()
    try:
        await enqueue_repository_index(job_id, repository_url, user["id"])
    except Exception as exc:
        await session.execute(
            text("""
                UPDATE repository_index_jobs
                SET status = 'failed', error = 'Queue unavailable', updated_at = now()
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": job_id},
        )
        await session.commit()
        raise HTTPException(status_code=503, detail="Repository indexing queue is unavailable") from exc
    return RepositoryIndexJobResponse(**job)


@router.get(
    "/repositories/jobs/{job_id}",
    response_model=RepositoryIndexJobResponse,
    tags=["discovery"],
)
async def get_repository_index_job(
    job_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            SELECT id::text AS id, status, repository_url, attempt_count, error,
                   app_id::text AS app_id, created_at, updated_at, completed_at
            FROM repository_index_jobs
            WHERE id = CAST(:job_id AS uuid)
              AND requested_by = CAST(:user_id AS uuid)
        """),
        {"job_id": str(job_id), "user_id": user["id"]},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Repository indexing job not found")
    return RepositoryIndexJobResponse(**dict(row))


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED, tags=["integrations"])
async def github_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    event: str | None = Header(default=None, alias="X-GitHub-Event"),
    delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    session: AsyncSession = Depends(get_session),
):
    secret = get_settings().github_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub webhook integration is not configured")
    if not signature or not delivery or len(delivery) > 100:
        raise HTTPException(status_code=400, detail="Missing GitHub webhook signature or delivery ID")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="GitHub webhook payload is too large")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid GitHub webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="GitHub webhook payload must be a JSON object")

    if event != "push" or payload.get("deleted") is True:
        return {"accepted": True, "ignored": True, "reason": "event_not_indexable"}
    repository = payload.get("repository") or {}
    repository_url = repository.get("html_url")
    default_branch = repository.get("default_branch")
    pushed_ref = payload.get("ref")
    if not repository_url or not default_branch or pushed_ref != f"refs/heads/{default_branch}":
        return {"accepted": True, "ignored": True, "reason": "not_default_branch"}
    try:
        parse_github_url(repository_url)
    except ValueError:
        raise HTTPException(status_code=422, detail="Webhook repository URL is not a supported GitHub URL") from None

    duplicate = await session.execute(
        text("""
            INSERT INTO github_webhook_deliveries (delivery_id, event, repository_url)
            VALUES (:delivery, :event, :repository_url)
            ON CONFLICT (delivery_id) DO NOTHING
            RETURNING delivery_id
        """),
        {"delivery": delivery, "event": event, "repository_url": repository_url},
    )
    if duplicate.scalar_one_or_none() is None:
        existing = await session.execute(
            text("""
                SELECT jobs.id::text AS id, jobs.status, jobs.error
                FROM github_webhook_deliveries AS deliveries
                JOIN repository_index_jobs AS jobs ON jobs.id = deliveries.job_id
                WHERE deliveries.delivery_id = :delivery
            """),
            {"delivery": delivery},
        )
        prior_job = existing.mappings().first()
        if prior_job and prior_job["status"] == "failed" and prior_job["error"] == "Queue unavailable":
            await session.execute(
                text("""
                    UPDATE repository_index_jobs
                    SET status = 'queued', error = NULL, updated_at = now()
                    WHERE id = CAST(:id AS uuid)
                """),
                {"id": prior_job["id"]},
            )
            await session.commit()
            try:
                await enqueue_repository_index(prior_job["id"], repository_url, None)
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Repository indexing queue is unavailable") from exc
            return {"accepted": True, "duplicate": True, "job_id": prior_job["id"], "requeued": True}
        return {"accepted": True, "duplicate": True}

    job_id = str(uuid4())
    await session.execute(
        text("""
            INSERT INTO repository_index_jobs (id, repository_url, source)
            VALUES (CAST(:id AS uuid), :repository_url, 'github_webhook')
        """),
        {"id": job_id, "repository_url": repository_url},
    )
    await session.execute(
        text("""
            UPDATE github_webhook_deliveries SET job_id = CAST(:job_id AS uuid)
            WHERE delivery_id = :delivery
        """),
        {"job_id": job_id, "delivery": delivery},
    )
    await session.commit()
    try:
        await enqueue_repository_index(job_id, repository_url, None)
    except Exception as exc:
        await session.execute(
            text("""
                UPDATE repository_index_jobs
                SET status = 'failed', error = 'Queue unavailable', updated_at = now()
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": job_id},
        )
        await session.commit()
        raise HTTPException(status_code=503, detail="Repository indexing queue is unavailable") from exc
    return {"accepted": True, "job_id": job_id}


@router.get(
    "/repositories/mine",
    response_model=list[RepositorySubmissionResponse],
    tags=["discovery"],
)
async def list_my_repositories(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            SELECT
                apps.id::text AS id,
                apps.name,
                apps.description,
                apps.repository_url,
                apps.default_branch,
                apps.latest_commit_sha,
                apps.stars,
                submissions.submitted_at,
                apps.indexed_at
            FROM repository_submissions AS submissions
            JOIN apps ON apps.id = submissions.app_id
            WHERE submissions.user_id = CAST(:user_id AS uuid)
            ORDER BY submissions.submitted_at DESC, apps.name ASC
        """),
        {"user_id": user["id"]},
    )
    return [RepositorySubmissionResponse(**dict(row)) for row in result.mappings()]


@router.delete(
    "/repositories/mine/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["discovery"],
)
async def remove_my_repository(
    app_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            DELETE FROM repository_submissions
            WHERE user_id = CAST(:user_id AS uuid)
              AND app_id = CAST(:app_id AS uuid)
            RETURNING app_id
        """),
        {"user_id": user["id"], "app_id": str(app_id)},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Repository submission not found")
    await session.commit()


@router.post("/search", response_model=list[SearchResult], tags=["discovery"])
async def search_apps(payload: SearchRequest, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    embedding_literal = None
    if settings.ai_provider != "none" and settings.ai_embedding_model:
        try:
            provider = get_ai_provider()
            if provider is not None:
                vectors = await provider.embed([payload.query])
                if len(vectors) != 1:
                    raise ValueError("Embedding provider returned an unexpected result count")
                embedding_literal = _serialize_embedding(vectors[0])
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Semantic search is temporarily unavailable") from exc

    if embedding_literal is not None:
        statement = text("""
            WITH lexical AS (
                SELECT id, ts_rank(search_document, websearch_to_tsquery('english', :query))::float AS score
                FROM apps
                WHERE search_document @@ websearch_to_tsquery('english', :query)
            ),
            semantic AS (
                SELECT id, GREATEST(0, 1 - (embedding <=> CAST(:embedding AS vector)))::float AS score
                FROM apps
                WHERE embedding IS NOT NULL AND embedding_model = :embedding_model
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            ),
            ranked AS (
                SELECT id, score * 0.65 AS score FROM lexical
                UNION ALL
                SELECT id, score * 0.35 AS score FROM semantic
            )
            SELECT apps.id::text AS id, apps.name, apps.description, apps.repository_url,
                   SUM(ranked.score)::float AS score
            FROM ranked JOIN apps ON apps.id = ranked.id
            GROUP BY apps.id, apps.name, apps.description, apps.repository_url
            ORDER BY score DESC
            LIMIT :limit
        """)
        params = {
            "query": payload.query,
            "embedding": embedding_literal,
            "embedding_model": settings.ai_embedding_model,
            "limit": payload.limit,
        }
    else:
        statement = text("""
            SELECT id::text, name, description, repository_url,
                   ts_rank(search_document, websearch_to_tsquery('english', :query)) AS score
            FROM apps
            WHERE search_document @@ websearch_to_tsquery('english', :query)
            ORDER BY score DESC, stars DESC
            LIMIT :limit
        """)
        params = {"query": payload.query, "limit": payload.limit}

    try:
        rows = (await session.execute(statement, params)).mappings()
        return [SearchResult(**dict(row)) for row in rows]
    except Exception as exc:
        if "apps" in str(exc).lower() or "relation" in str(exc).lower():
            raise HTTPException(
                status_code=503,
                detail="Catalog schema is not initialized; apply the backend migrations",
            ) from exc
        raise

@router.get(
    "/apps/{app_id}/inspection",
    response_model=dict,
    tags=["inspection"],
)
async def get_cached_inspection(
    app_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            SELECT inspections.commit_sha, inspections.report, inspections.created_at
            FROM inspections
            JOIN apps ON apps.id = inspections.app_id
            WHERE apps.id = CAST(:app_id AS uuid)
            ORDER BY inspections.created_at DESC
            LIMIT 1
        """),
        {"app_id": str(app_id)},
    )
    inspection = result.mappings().first()
    if inspection is None:
        raise HTTPException(status_code=404, detail="No cached inspection is available")
    return {
        "app_id": str(app_id),
        "commit_sha": inspection["commit_sha"],
        "cached_at": inspection["created_at"],
        "report": inspection["report"],
    }


@router.post("/repositories/inspect", response_model=InspectionResponse, tags=["inspection"])
async def inspect_repository(payload: RepositoryRequest):
    try:
        files = await fetch_repository_files(str(payload.repository_url))
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=f"Repository could not be inspected: {exc}") from exc
    sdk_detections = detect_declared_sdks(files)
    manifest_path, manifest = next(
        ((path, value) for path, value in files.items() if path.endswith("AndroidManifest.xml")),
        (None, None),
    )
    if manifest is None:
        return InspectionResponse(
            repository=str(payload.repository_url),
            manifest_found=False,
            permissions=[],
            sdk_detections=sdk_detections,
            manifest_warnings=[],
            limitations=[
                "AndroidManifest.xml was not found in common repository paths.",
                "SDK matches are dependency declarations only; they do not prove SDK initialization or data transmission.",
                "Only static source inspection is performed; no APK or runtime behavior was executed.",
            ],
        )
    try:
        parsed = inspect_manifest(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InspectionResponse(
        repository=str(payload.repository_url),
        manifest_found=True,
        package_name=parsed["package_name"],
        permissions=[ManifestFinding(**finding) for finding in parsed["permissions"]],
        sdk_detections=sdk_detections,
        manifest_warnings=inspect_manifest_flags(manifest, manifest_path),
        limitations=[
            "Permission declarations do not prove a permission is used at runtime.",
            "SDK matches are dependency declarations only; they do not prove SDK initialization or data transmission.",
            "Manifest warnings use line-level static heuristics and require manual review.",
            "Runtime behavior, dynamic code loading and full architecture analysis are not assessed.",
        ],
    )


@router.post("/remixes", response_model=RemixSessionResponse, status_code=status.HTTP_201_CREATED, tags=["remix"])
async def create_remix_session(
    payload: RemixSessionCreateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            SELECT id::text AS app_id, name AS app_name, repository_url, latest_commit_sha
            FROM apps WHERE id = CAST(:app_id AS uuid) AND latest_commit_sha IS NOT NULL
        """),
        {"app_id": payload.app_id},
    )
    app = result.mappings().first()
    if app is None:
        raise HTTPException(status_code=404, detail="Indexed app with a source commit not found")
    created = await session.execute(
        text("""
            INSERT INTO remix_sessions (owner_id, app_id, source_commit_sha, title)
            VALUES (CAST(:owner_id AS uuid), CAST(:app_id AS uuid), :commit_sha, :title)
            RETURNING id::text AS id, status, title, created_at, updated_at
        """),
        {
            "owner_id": user["id"], "app_id": str(payload.app_id),
            "commit_sha": app["latest_commit_sha"], "title": payload.title.strip(),
        },
    )
    row = dict(created.mappings().one())
    await session.commit()
    return RemixSessionResponse(
        **row, app_id=app["app_id"], app_name=app["app_name"],
        repository_url=app["repository_url"], source_commit_sha=app["latest_commit_sha"],
    )


@router.get("/remixes", response_model=list[RemixSessionResponse], tags=["remix"])
async def list_remix_sessions(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        text("""
            SELECT rs.id::text AS id, rs.app_id::text AS app_id, apps.name AS app_name,
                   apps.repository_url, rs.source_commit_sha, rs.title, rs.status,
                   rs.created_at, rs.updated_at
            FROM remix_sessions rs JOIN apps ON apps.id = rs.app_id
            WHERE rs.owner_id = CAST(:owner_id AS uuid)
            ORDER BY rs.updated_at DESC LIMIT 100
        """),
        {"owner_id": user["id"]},
    )).mappings()
    return [RemixSessionResponse(**dict(row)) for row in rows]


@router.get("/remixes/{remix_id}", response_model=RemixSessionResponse, tags=["remix"])
async def get_remix_session(
    remix_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        text("""
            SELECT rs.id::text AS id, rs.app_id::text AS app_id, apps.name AS app_name,
                   apps.repository_url, rs.source_commit_sha, rs.title, rs.status,
                   rs.created_at, rs.updated_at
            FROM remix_sessions rs JOIN apps ON apps.id = rs.app_id
            WHERE rs.id = CAST(:id AS uuid) AND rs.owner_id = CAST(:owner_id AS uuid)
        """),
        {"id": str(remix_id), "owner_id": user["id"]},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Remix session not found")
    messages = (await session.execute(
        text("""
            SELECT id::text AS id, role, content, message_type, evidence, created_at
            FROM remix_messages WHERE session_id = CAST(:id AS uuid)
            ORDER BY created_at ASC LIMIT 200
        """),
        {"id": str(remix_id)},
    )).mappings()
    return RemixSessionResponse(**dict(row), messages=[RemixMessageResponse(**dict(m)) for m in messages])


@router.post("/remixes/{remix_id}/messages", response_model=RemixMessageResponse, status_code=status.HTTP_201_CREATED, tags=["remix"])
async def add_remix_message(
    remix_id: UUID,
    payload: RemixMessageCreateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    owned = await session.execute(
        text("""
            SELECT rs.id::text AS id, rs.app_id::text AS app_id, rs.source_commit_sha,
                   apps.latest_commit_sha
            FROM remix_sessions rs JOIN apps ON apps.id = rs.app_id
            WHERE rs.id = CAST(:id AS uuid) AND rs.owner_id = CAST(:owner_id AS uuid)
              AND rs.status = 'planning'
        """),
        {"id": str(remix_id), "owner_id": user["id"]},
    )
    remix = owned.mappings().first()
    if remix is None:
        raise HTTPException(status_code=404, detail="Active remix session not found")
    if remix["latest_commit_sha"] != remix["source_commit_sha"]:
        raise HTTPException(status_code=409, detail="Repository changed since this remix began; start a new session to use the latest source snapshot")
    await enforce_remix_rate_limit(user["id"])
    message_id = str(uuid4())
    await session.execute(
        text("""
            INSERT INTO remix_messages (id, session_id, role, content, message_type)
            VALUES (CAST(:id AS uuid), CAST(:session_id AS uuid), 'user', :content, 'text')
            RETURNING id::text AS id, role, content, message_type, evidence, created_at
        """),
        {"id": message_id, "session_id": str(remix_id), "content": payload.content.strip()},
    )
    await session.execute(
        text("UPDATE remix_sessions SET updated_at = now() WHERE id = CAST(:id AS uuid)"),
        {"id": str(remix_id)},
    )
    await session.commit()

    history = (await session.execute(
        text("""
            SELECT role, content FROM remix_messages
            WHERE session_id = CAST(:id AS uuid)
            ORDER BY created_at DESC LIMIT 12
        """),
        {"id": str(remix_id)},
    )).mappings()
    files = (await session.execute(
        text("""
            SELECT path, content_excerpt FROM repository_files
            WHERE app_id = CAST(:app_id AS uuid)
            ORDER BY CASE
                WHEN lower(path) LIKE '%androidmanifest.xml' THEN 0
                WHEN lower(path) LIKE '%build.gradle%' THEN 1
                WHEN lower(path) LIKE '%readme%' THEN 2
                ELSE 3 END, path
            LIMIT 12
        """),
        {"app_id": remix["app_id"]},
    )).mappings()
    file_rows = [dict(item) for item in files]
    # Recheck after reading the snapshot to close the catalog-refresh race window.
    current = await session.execute(
        text("SELECT latest_commit_sha FROM apps WHERE id = CAST(:app_id AS uuid)"),
        {"app_id": remix["app_id"]},
    )
    if current.scalar_one_or_none() != remix["source_commit_sha"]:
        raise HTTPException(status_code=409, detail="Repository changed while preparing this plan; start a new remix session")
    try:
        plan = await generate_change_plan(
            request=payload.content,
            files=file_rows,
            history=[dict(item) for item in reversed(list(history))],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Remix planning AI provider is not configured") from exc
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Remix planning is temporarily unavailable") from exc
    plan = plan.strip()[:12_000]
    if not plan:
        raise HTTPException(status_code=503, detail="Remix planner returned an empty response")
    evidence = [{"path": item["path"]} for item in file_rows]
    response = await session.execute(
        text("""
            INSERT INTO remix_messages (session_id, role, content, message_type, evidence)
            VALUES (CAST(:session_id AS uuid), 'assistant', :content, 'change_plan', CAST(:evidence AS jsonb))
            RETURNING id::text AS id, role, content, message_type, evidence, created_at
        """),
        {
            "session_id": str(remix_id), "content": plan,
            "evidence": json.dumps(evidence),
        },
    )
    await session.execute(
        text("UPDATE remix_sessions SET updated_at = now() WHERE id = CAST(:id AS uuid)"),
        {"id": str(remix_id)},
    )
    await session.commit()
    return RemixMessageResponse(**dict(response.mappings().one()))
