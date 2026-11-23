import re
from urllib.parse import quote

import httpx

from app.config import get_settings

_GITHUB_RE = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_MAX_FILE_BYTES = 1_000_000
_MAX_INDEXED_FILES = 12


def parse_github_url(repository_url: str) -> tuple[str, str]:
    match = _GITHUB_RE.fullmatch(repository_url.strip())
    if match is None:
        raise ValueError("Only canonical public GitHub repository URLs are supported")
    owner, repository = match.groups()
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    return owner, repository


async def fetch_repository_snapshot(repository_url: str) -> dict:
    owner, repository = parse_github_url(repository_url)
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        base = f"https://api.github.com/repos/{owner}/{repository}"
        metadata_response = await client.get(base, headers=headers)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        if metadata.get("private"):
            raise ValueError("Private repositories are not supported by this indexing endpoint")

        branch = metadata["default_branch"]
        branch_response = await client.get(f"{base}/branches/{quote(branch, safe='')}", headers=headers)
        branch_response.raise_for_status()
        commit_sha = branch_response.json()["commit"]["sha"]

        tree_response = await client.get(
            f"{base}/git/trees/{quote(branch, safe='')}?recursive=1",
            headers=headers,
        )
        tree_response.raise_for_status()
        tree_payload = tree_response.json()
        if tree_payload.get("truncated"):
            raise ValueError("Repository tree is too large for complete indexing")

        def is_indexable_file(path: str) -> bool:
            normalized = path.lower()
            filename = normalized.rsplit("/", 1)[-1]
            return (
                normalized in {"readme.md", "readme"}
                or filename == "androidmanifest.xml"
                or filename in {
                    "build.gradle",
                    "build.gradle.kts",
                    "settings.gradle",
                    "settings.gradle.kts",
                    "libs.versions.toml",
                }
            )

        candidates = [
            entry for entry in tree_payload.get("tree", [])
            if entry.get("type") == "blob" and is_indexable_file(entry["path"])
        ]
        def priority(entry: dict) -> tuple[int, str]:
            filename = entry["path"].lower().rsplit("/", 1)[-1]
            if filename in {"readme.md", "readme"}:
                rank = 0
            elif filename == "androidmanifest.xml":
                rank = 1
            else:
                rank = 2
            return rank, entry["path"]

        candidates.sort(key=priority)
        files = []
        for entry in candidates[:_MAX_INDEXED_FILES]:
            if entry.get("size", 0) > _MAX_FILE_BYTES:
                continue
            raw_url = (
                f"https://raw.githubusercontent.com/{owner}/{repository}/"
                f"{quote(branch, safe='')}/{quote(entry['path'], safe='/')}"
            )
            chunks = []
            total_bytes = 0
            oversized = False
            async with client.stream("GET", raw_url, headers={"Accept": "text/plain"}) as raw_response:
                if raw_response.status_code == 404:
                    continue
                raw_response.raise_for_status()
                async for chunk in raw_response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_FILE_BYTES:
                        oversized = True
                        break
                    chunks.append(chunk)
            if oversized:
                continue
            content_bytes = b"".join(chunks)
            files.append({
                "path": entry["path"],
                "content_sha": entry["sha"],
                "content": content_bytes.decode("utf-8", errors="replace"),
                "size": total_bytes,
            })

    license_info = metadata.get("license") or {}
    return {
        "name": metadata["name"],
        "description": metadata.get("description"),
        "repository_url": metadata["html_url"],
        "default_branch": branch,
        "stars": int(metadata.get("stargazers_count") or 0),
        "license": license_info.get("spdx_id"),
        "commit_sha": commit_sha,
        "files": files,
    }


async def fetch_repository_files(repository_url: str) -> dict[str, str]:
    snapshot = await fetch_repository_snapshot(repository_url)
    return {item["path"]: item["content"] for item in snapshot["files"]}
