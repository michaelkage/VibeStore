import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, tags=["authentication"])
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    email = payload.email.strip().lower()
    try:
        result = await session.execute(
            text("""
                INSERT INTO users (email, password_hash)
                VALUES (:email, :password_hash)
                RETURNING id::text AS id, email, created_at
            """),
            {"email": email, "password_hash": hash_password(payload.password)},
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
    if user is None or not verify_password(payload.password, user["password_hash"]):
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
    result = await session.execute(
        text("""
            INSERT INTO apps (
                name, description, repository_url, default_branch, stars,
                license, latest_commit_sha, indexed_at
            )
            VALUES (
                :name, :description, :repository_url, :default_branch, :stars,
                :license, :commit_sha, now()
            )
            ON CONFLICT (repository_url) DO UPDATE SET
                name = EXCLUDED.name,
                description = COALESCE(EXCLUDED.description, apps.description),
                default_branch = EXCLUDED.default_branch,
                stars = EXCLUDED.stars,
                license = EXCLUDED.license,
                latest_commit_sha = EXCLUDED.latest_commit_sha,
                indexed_at = now(),
                updated_at = now()
            RETURNING id::text AS id
        """),
        {
            "name": snapshot["name"],
            "description": description,
            "repository_url": snapshot["repository_url"],
            "default_branch": snapshot["default_branch"],
            "stars": snapshot["stars"],
            "license": snapshot["license"],
            "commit_sha": snapshot["commit_sha"],
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
    statement = text("""
        SELECT id::text, name, description, repository_url,
               ts_rank(search_document, websearch_to_tsquery('english', :query)) AS score
        FROM apps
        WHERE search_document @@ websearch_to_tsquery('english', :query)
        ORDER BY score DESC, stars DESC
        LIMIT :limit
    """)
    try:
        rows = (await session.execute(statement, {"query": payload.query, "limit": payload.limit})).mappings()
        return [SearchResult(**dict(row)) for row in rows]
    except Exception as exc:
        if "apps" in str(exc).lower() or "relation" in str(exc).lower():
            raise HTTPException(
                status_code=503,
                detail="Catalog schema is not initialized; apply migrations/001_initial.sql",
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
