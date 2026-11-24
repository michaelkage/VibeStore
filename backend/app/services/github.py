import base64
import hashlib
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
            f"{base}/git/trees/{quote(commit_sha, safe='')}?recursive=1",
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
                f"{quote(commit_sha, safe='')}/{quote(entry['path'], safe='/')}"
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


_MAX_PATCH_SOURCE_BYTES = 1_000_000
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(\n        b"blob " + str(len(content)).encode() + b"\0" + content,\n        usedforsecurity=False,\n    ).hexdigest()


async def fetch_repository_files_at_commit(
    repository_url: str, commit_sha: str, expected_files: list[dict],
) -> dict[str, dict]:
    """Fetch complete, hash-verified file contents from one immutable Git commit."""
    if not _GIT_SHA_RE.fullmatch(commit_sha):
        raise ValueError("Pinned source commit SHA is invalid")
    if not 1 <= len(expected_files) <= 6:
        raise ValueError("Patch source file count is outside the supported range")
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
        commit_response = await client.get(
            f"{base}/git/commits/{commit_sha}", headers=headers,
        )
        commit_response.raise_for_status()
        tree_sha = commit_response.json().get("tree", {}).get("sha")
        if not isinstance(tree_sha, str) or not _GIT_SHA_RE.fullmatch(tree_sha):
            raise ValueError("Pinned commit does not contain a valid Git tree")
        tree_response = await client.get(
            f"{base}/git/trees/{tree_sha}?recursive=1", headers=headers,
        )
        tree_response.raise_for_status()
        tree = tree_response.json()
        if tree.get("truncated"):
            raise ValueError("Pinned repository tree is truncated; source cannot be verified safely")
        entries = {
            entry["path"]: entry for entry in tree.get("tree", [])
            if entry.get("type") == "blob"
        }
        result = {}
        for item in expected_files:
            path, expected_sha = item.get("path"), item.get("content_sha")
            if not isinstance(path, str) or not _GIT_SHA_RE.fullmatch(str(expected_sha or "")):
                raise ValueError("Stored source file identity is invalid")
            entry = entries.get(path)
            if entry is None or entry.get("sha") != expected_sha:
                raise ValueError(f"Source file no longer matches the pinned commit: {path}")
            if entry.get("size", 0) > _MAX_PATCH_SOURCE_BYTES:
                raise ValueError(f"Source file exceeds the 1 MB validation limit: {path}")
            blob_response = await client.get(
                f"{base}/git/blobs/{expected_sha}", headers=headers,
            )
            blob_response.raise_for_status()
            blob = blob_response.json()
            if blob.get("sha") != expected_sha or blob.get("encoding") != "base64":
                raise ValueError(f"GitHub returned an unexpected source blob: {path}")
            try:
                content = base64.b64decode(blob.get("content", ""), validate=False)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"GitHub returned invalid base64 source: {path}") from exc
            if len(content) > _MAX_PATCH_SOURCE_BYTES or _git_blob_sha(content) != expected_sha:
                raise ValueError(f"Complete source hash verification failed: {path}")
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Binary or non-UTF-8 source is not supported: {path}") from exc
            result[path] = {
                "content": decoded,
                "content_sha": expected_sha,
                "size": len(content),
            }
        return result
