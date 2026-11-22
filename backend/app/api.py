import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.schemas import SearchRequest, SearchResult, InspectionResponse, ManifestFinding, RepositoryRequest
from app.services.github import fetch_repository_files
from app.services.manifest import inspect_manifest

router = APIRouter()

@router.post("/search", response_model=list[SearchResult], tags=["discovery"])
async def search_apps(payload: SearchRequest, session: AsyncSession = Depends(get_session)):
    statement = text("""
      SELECT id::text, name, description, repository_url,
        ts_rank(search_document, websearch_to_tsquery('english', :query)) AS score
      FROM apps WHERE search_document @@ websearch_to_tsquery('english', :query)
      ORDER BY score DESC, stars DESC LIMIT :limit
    """)
    try:
        rows = (await session.execute(statement, {"query": payload.query, "limit": payload.limit})).mappings()
        return [SearchResult(**dict(row)) for row in rows]
    except Exception as exc:
        if "apps" in str(exc).lower() or "relation" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Catalog schema is not initialized; apply migrations/001_initial.sql") from exc
        raise

@router.post("/repositories/inspect", response_model=InspectionResponse, tags=["inspection"])
async def inspect_repository(payload: RepositoryRequest):
    try:
        files = await fetch_repository_files(str(payload.repository_url))
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=f"Repository could not be inspected: {exc}") from exc
    manifest = next((v for k, v in files.items() if k.endswith("AndroidManifest.xml")), None)
    if manifest is None:
        return InspectionResponse(repository=str(payload.repository_url), manifest_found=False,
          permissions=[], limitations=["AndroidManifest.xml was not found in common repository paths.",
          "Only static source inspection is performed; no APK or runtime behavior was executed."])
    try:
        parsed = inspect_manifest(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InspectionResponse(repository=str(payload.repository_url), manifest_found=True,
      package_name=parsed["package_name"], permissions=[ManifestFinding(**v) for v in parsed["permissions"]],
      limitations=["Permission declarations do not prove a permission is used at runtime.",
      "Tracker detection and full architecture analysis are not yet enabled."])
