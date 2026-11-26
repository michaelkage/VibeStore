from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import httpx

from app.config import get_settings
from app.services.github import fetch_repository_snapshot as fetch_github_snapshot

_ALLOWED_HOSTS = {"github.com", "gitlab.com", "codeberg.org"}
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_FILE_BYTES = 1_000_000
_MAX_INDEXED_FILES = 12


def parse_repository_url(repository_url: str) -> tuple[str, str, str]:
    """Return (host, namespace, project) for a supported public forge URL."""
    try:
        parsed = urlsplit(repository_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Repository URL is invalid") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        raise ValueError(
            "Only HTTPS repositories on GitHub, GitLab.com, and Codeberg are supported"
        )
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2 or (host != "gitlab.com" and len(parts) != 2):
        raise ValueError("Repository URL must identify a namespace and project")
    if any(not _COMPONENT_RE.fullmatch(part) for part in parts):
        raise ValueError("Repository URL contains unsupported path characters")
    project = parts[-1].removesuffix(".git")
    namespace = "/".join(parts[:-1])
    if not project:
        raise ValueError("Repository project name is missing")
    return host, namespace, project


def _is_indexable_file(path: str) -> bool:
    normalized = path.lower()
    filename = normalized.rsplit("/", 1)[-1]
    return (
        normalized in {"readme.md", "readme"}
        or filename == "androidmanifest.xml"
        or filename
        in {
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
            "libs.versions.toml",
        }
    )


def _file_priority(path: str) -> tuple[int, str]:
    filename = path.lower().rsplit("/", 1)[-1]
    if filename in {"readme.md", "readme"}:
        rank = 0
    elif filename == "androidmanifest.xml":
        rank = 1
    else:
        rank = 2
    return rank, path


def _license_value(value):
    if isinstance(value, dict):
        return value.get("spdx_id") or value.get("key") or value.get("name")
    return value if isinstance(value, str) else None



async def _read_bounded_source(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    params: dict | None = None,
) -> bytes | None:
    chunks = []
    total = 0
    async with client.stream("GET", url, params=params, headers=headers) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > _MAX_FILE_BYTES:
                return None
            chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_gitlab_snapshot(namespace: str, project: str) -> dict:
    settings = get_settings()
    project_path = quote(f"{namespace}/{project}", safe="")
    base = f"https://gitlab.com/api/v4/projects/{project_path}"
    headers = {"Accept": "application/json"}
    if settings.gitlab_token:
        headers["PRIVATE-TOKEN"] = settings.gitlab_token

    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        metadata_response = await client.get(base, headers=headers)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        if metadata.get("visibility") != "public":
            raise ValueError("Only public GitLab repositories are supported")

        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise ValueError("GitLab repository has no default branch")
        branch_response = await client.get(
            f"{base}/repository/branches/{quote(branch, safe='')}",
            headers=headers,
        )
        branch_response.raise_for_status()
        commit_sha = branch_response.json().get("commit", {}).get("id")
        if not isinstance(commit_sha, str) or not commit_sha:
            raise ValueError("GitLab default branch did not return a commit SHA")

        entries = []
        page = 1
        while page <= 5:
            tree_response = await client.get(
                f"{base}/repository/tree",
                params={
                    "ref": commit_sha,
                    "recursive": "true",
                    "per_page": 100,
                    "page": page,
                },
                headers=headers,
            )
            tree_response.raise_for_status()
            entries.extend(tree_response.json())
            next_page = tree_response.headers.get("X-Next-Page")
            if not next_page:
                break
            page = int(next_page)
        else:
            raise ValueError("GitLab repository tree exceeds the indexing page limit")

        candidates = sorted(
            (
                entry
                for entry in entries
                if entry.get("type") == "blob"
                and _is_indexable_file(str(entry.get("path", "")))
                and isinstance(entry.get("id"), str)
            ),
            key=lambda entry: _file_priority(entry["path"]),
        )
        files = []
        for entry in candidates[:_MAX_INDEXED_FILES]:
            if int(entry.get("size") or 0) > _MAX_FILE_BYTES:
                continue
            path = entry["path"]
            raw_url = (
                f"{base}/repository/files/{quote(path, safe='')}/raw"
            )
            content = await _read_bounded_source(
                client,
                raw_url,
                params={"ref": commit_sha},
                headers={"Accept": "text/plain", **headers},
            )
            if content is None:
                continue
            files.append(
                {
                    "path": path,
                    "content_sha": entry["id"],
                    "content": content.decode("utf-8", errors="replace"),
                    "size": len(content),
                }
            )

    license_info = metadata.get("license")
    return {
        "name": metadata.get("name") or project,
        "description": metadata.get("description"),
        "repository_url": metadata.get("web_url")
        or f"https://gitlab.com/{namespace}/{project}",
        "default_branch": branch,
        "stars": int(metadata.get("star_count") or 0),
        "license": _license_value(license_info),
        "commit_sha": commit_sha,
        "files": files,
    }


async def _fetch_codeberg_snapshot(namespace: str, project: str) -> dict:
    settings = get_settings()
    base = f"https://codeberg.org/api/v1/repos/{namespace}/{project}"
    headers = {"Accept": "application/json"}
    if settings.codeberg_token:
        headers["Authorization"] = f"token {settings.codeberg_token}"

    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        metadata_response = await client.get(base, headers=headers)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        if metadata.get("private") is True:
            raise ValueError("Only public Codeberg repositories are supported")

        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise ValueError("Codeberg repository has no default branch")
        branch_response = await client.get(
            f"{base}/branches/{quote(branch, safe='')}",
            headers=headers,
        )
        branch_response.raise_for_status()
        commit_sha = branch_response.json().get("commit", {}).get("id")
        if not isinstance(commit_sha, str) or not commit_sha:
            raise ValueError("Codeberg default branch did not return a commit SHA")

        tree_response = await client.get(
            f"{base}/git/trees/{quote(commit_sha, safe='')}",
            params={"recursive": "true"},
            headers=headers,
        )
        tree_response.raise_for_status()
        tree_payload = tree_response.json()
        if tree_payload.get("truncated"):
            raise ValueError("Codeberg repository tree is too large for complete indexing")
        candidates = sorted(
            (
                entry
                for entry in tree_payload.get("tree", [])
                if entry.get("type") == "blob"
                and _is_indexable_file(str(entry.get("path", "")))
                and isinstance(entry.get("sha"), str)
            ),
            key=lambda entry: _file_priority(entry["path"]),
        )
        files = []
        for entry in candidates[:_MAX_INDEXED_FILES]:
            if int(entry.get("size") or 0) > _MAX_FILE_BYTES:
                continue
            path = entry["path"]
            raw_url = (
                f"https://codeberg.org/{namespace}/{project}/raw/commit/"
                f"{quote(commit_sha, safe='')}/{quote(path, safe='/')}"
            )
            content = await _read_bounded_source(
                client,
                raw_url,
                headers={"Accept": "text/plain", **headers},
            )
            if content is None:
                continue
            files.append(
                {
                    "path": path,
                    "content_sha": entry["sha"],
                    "content": content.decode("utf-8", errors="replace"),
                    "size": len(content),
                }
            )

    return {
        "name": metadata.get("name") or project,
        "description": metadata.get("description"),
        "repository_url": metadata.get("html_url")
        or f"https://codeberg.org/{namespace}/{project}",
        "default_branch": branch,
        "stars": int(metadata.get("stars_count") or 0),
        "license": _license_value(metadata.get("license")),
        "commit_sha": commit_sha,
        "files": files,
    }


async def fetch_repository_snapshot(repository_url: str) -> dict:
    host, namespace, project = parse_repository_url(repository_url)
    if host == "github.com":
        return await fetch_github_snapshot(repository_url)
    if host == "gitlab.com":
        return await _fetch_gitlab_snapshot(namespace, project)
    return await _fetch_codeberg_snapshot(namespace, project)


async def fetch_repository_files(repository_url: str) -> dict[str, str]:
    snapshot = await fetch_repository_snapshot(repository_url)
    return {item["path"]: item["content"] for item in snapshot["files"]}
