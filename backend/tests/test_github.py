import pytest

from app.services.github import parse_github_url


def test_parse_github_repository_url():
    assert parse_github_url("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_github_repository_url_with_git_suffix():
    assert parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.evil.example/owner/repo",
        "https://example.com/owner/repo",
        "https://github.com/owner",
        "file:///etc/passwd",
        "https://github.com/owner/repo/issues",
    ],
)
def test_reject_non_repository_urls(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_git_blob_sha_matches_git_object_hash():
    import hashlib

    from app.services.github import _git_blob_sha

    content = b"source text\n"
    expected = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    assert _git_blob_sha(content) == expected



@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repo", ("github.com", "owner", "repo")),
        ("https://gitlab.com/group/subgroup/project.git", ("gitlab.com", "group/subgroup", "project")),
        ("https://codeberg.org/owner/repo", ("codeberg.org", "owner", "repo")),
    ],
)
def test_parse_supported_repository_sources(url, expected):
    from app.services.repository_sources import parse_repository_url

    assert parse_repository_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo",
        "https://github.com.evil.example/owner/repo",
        "https://example.com/owner/repo",
        "https://gitlab.com/group",
        "https://codeberg.org/owner/repo/issues",
        "https://user:pass@github.com/owner/repo",
        "https://github.com/owner%2Frepo",
        "https://github.com/owner/repo?redirect=https://evil.example",
    ],
)
def test_reject_unsupported_repository_sources(url):
    from app.services.repository_sources import parse_repository_url

    with pytest.raises(ValueError):
        parse_repository_url(url)
