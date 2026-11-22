import re
import httpx
from app.config import get_settings

_GITHUB_RE = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
async def fetch_repository_files(repository_url: str) -> dict[str, str]:
    match = _GITHUB_RE.match(repository_url)
    if not match:
        raise ValueError("Only public GitHub repository URLs are currently supported")
    owner, repo = match.groups()
    headers = {"Accept": "application/vnd.github+json"}
    if token := get_settings().github_token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        metadata = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        metadata.raise_for_status()
        branch = metadata.json()["default_branch"]
        tree = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1", headers=headers)
        tree.raise_for_status()
        candidates = [e["path"] for e in tree.json().get("tree", [])
            if e.get("type") == "blob" and (e["path"].endswith("AndroidManifest.xml") or e["path"].lower() == "readme.md")]
        result = {}
        for path in candidates[:12]:
            raw = await client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}", headers=headers)
            if raw.is_success and len(raw.content) <= 1_000_000:
                result[path] = raw.text
        return result
