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
