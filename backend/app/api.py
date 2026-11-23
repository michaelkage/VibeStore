import asyncio
import math

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_compatible import get_ai_provider
from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.config import get_settings
from app.db import get_session
from app.schemas import (
    InspectionResponse,
    IndexRepositoryResponse,
    LoginRequest,
    ManifestFinding,
    RegisterRequest,
    RepositoryRequest,
    SearchRequest,
    SearchResult,
    TokenResponse,
    UserResponse,
)
from app.services.github import fetch_repository_files, fetch_repository_snapshot
from app.services.manifest import inspect_manifest

router = APIRouter()


def _serialize_embedding(values: list[float]) -> str:
    if not values or len(values) > 8192:
        raise ValueError("Embedding dimensions are outside the supported range")
    normalized = [float(value) for value in values]
    if not all(math.isfinite(value) for value in normalized):
        raise ValueError("Embedding contains a non-finite value")
    return "[" + ",".join(format(value, ".9g") for value in normalized) + "]"


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, tags=["authentication"])
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


@router.post("/auth/token", response_model=TokenResponse, tags=["authentication"])
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
    candidate_hash = user["password_hash"] if user is not None else __import__("app.auth", fromlist=["_DUMMY_PASSWORD_HASH"])._DUMMY_PASSWORD_HASH
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

@router.post("/repositories/inspect", response_model=InspectionResponse, tags=["inspection"])
async def inspect_repository(payload: RepositoryRequest):
    try:
        files = await fetch_repository_files(str(payload.repository_url))
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=f"Repository could not be inspected: {exc}") from exc
    manifest = next((value for path, value in files.items() if path.endswith("AndroidManifest.xml")), None)
    if manifest is None:
        return InspectionResponse(
            repository=str(payload.repository_url),
            manifest_found=False,
            permissions=[],
            limitations=[
                "AndroidManifest.xml was not found in common repository paths.",
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
        limitations=[
            "Permission declarations do not prove a permission is used at runtime.",
            "Tracker detection and full architecture analysis are not yet enabled.",
        ],
    )
