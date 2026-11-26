import json
import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_compatible import get_ai_provider
from app.config import get_settings
from app.services.repository_sources import fetch_repository_snapshot
from app.services.inspection import create_inspection_report


async def index_repository_snapshot(
    session: AsyncSession,
    repository_url: str,
    user_id: str | None = None,
) -> dict:
    snapshot = await fetch_repository_snapshot(repository_url)
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
        from app.services.manifest import inspect_manifest
        try:
            package_name = inspect_manifest(manifest_xml)["package_name"]
        except ValueError:
            package_name = None

    embedding_literal = None
    embedding_model = None
    settings = get_settings()
    if settings.ai_provider != "none" and settings.ai_embedding_model:
        provider = get_ai_provider()
        if provider is not None:
            source_text = " ".join(
                [snapshot["name"], description or "", *(item["content"] for item in snapshot["files"])]
            )[:12_000]
            vectors = await provider.embed([source_text])
            if len(vectors) != 1 or not vectors[0] or len(vectors[0]) > 8192:
                raise ValueError("Embedding provider returned an invalid vector")
            values = [float(value) for value in vectors[0]]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Embedding provider returned a non-finite vector")
            embedding_literal = "[" + ",".join(format(value, ".9g") for value in values) + "]"
            embedding_model = settings.ai_embedding_model

    inspection_report = await create_inspection_report(
        {item["path"]: item["content"] for item in snapshot["files"]}
    )

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
    await session.execute(
        text("DELETE FROM repository_files WHERE app_id = CAST(:app_id AS uuid)"),
        {"app_id": app_id},
    )
    for item in snapshot["files"]:
        suffix = item["path"].rsplit(".", 1)[-1].lower() if "." in item["path"] else ""
        language = {"xml": "xml", "md": "markdown", "gradle": "gradle", "kts": "kotlin"}.get(suffix)
        await session.execute(
            text("""
                INSERT INTO repository_files (
                    app_id, path, content_sha, language, content_excerpt, indexed_at
                )
                VALUES (
                    CAST(:app_id AS uuid), :path, :content_sha, :language, :content_excerpt, now()
                )
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
            INSERT INTO inspections (app_id, commit_sha, report)
            VALUES (CAST(:app_id AS uuid), :commit_sha, CAST(:report AS jsonb))
            ON CONFLICT (app_id, commit_sha) DO UPDATE SET
                report = EXCLUDED.report,
                created_at = now()
        """),
        {
            "app_id": app_id,
            "commit_sha": snapshot["commit_sha"],
            "report": json.dumps(inspection_report),
        },
    )
    if user_id is not None:
        await session.execute(
            text("""
                INSERT INTO repository_submissions (user_id, app_id)
                VALUES (CAST(:user_id AS uuid), CAST(:app_id AS uuid))
                ON CONFLICT (user_id, app_id) DO UPDATE SET submitted_at = now()
            """),
            {"user_id": user_id, "app_id": app_id},
        )
    await session.commit()
    return {
        "app_id": app_id,
        "name": snapshot["name"],
        "repository_url": snapshot["repository_url"],
        "default_branch": snapshot["default_branch"],
        "latest_commit_sha": snapshot["commit_sha"],
        "stars": snapshot["stars"],
        "indexed_files": len(snapshot["files"]),
    }
