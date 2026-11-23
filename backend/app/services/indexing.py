from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.github import fetch_repository_snapshot


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

    result = await session.execute(
        text("""
            INSERT INTO apps (
                package_name, name, description, repository_url, default_branch, stars,
                license, latest_commit_sha, indexed_at
            )
            VALUES (
                :package_name, :name, :description, :repository_url, :default_branch, :stars,
                :license, :commit_sha, now()
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
                updated_at = now()
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
