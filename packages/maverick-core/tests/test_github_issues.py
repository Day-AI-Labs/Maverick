"""Tests for the github_issues tool. No network calls."""
from __future__ import annotations

from maverick.tools import github_issues as ghi


def test_missing_op_errors():
    assert ghi.github_issues().fn({}).startswith("ERROR: op is required")


def test_list_requires_owner_repo():
    out = ghi.github_issues().fn({"op": "list", "owner": "a"})
    assert out.startswith("ERROR")
    assert "owner and repo" in out


def test_get_requires_number(monkeypatch):
    out = ghi.github_issues().fn({"op": "get", "owner": "a", "repo": "b"})
    assert out.startswith("ERROR")
    assert "requires number" in out


def test_create_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = ghi.github_issues().fn(
        {"op": "create", "owner": "a", "repo": "b", "title": "hi"}
    )
    assert out.startswith("ERROR: set GITHUB_TOKEN")


def test_url_builders():
    assert ghi._list_url("a", "b", "open", 10).startswith(
        "https://api.github.com/repos/a/b/issues?"
    )
    assert "state=open" in ghi._list_url("a", "b", "open", 10)
    assert "per_page=10" in ghi._list_url("a", "b", "open", 10)
    assert ghi._get_url("a", "b", 7) == "https://api.github.com/repos/a/b/issues/7"
    assert ghi._create_url("a", "b") == "https://api.github.com/repos/a/b/issues"


def test_parse_list_skips_prs():
    items = [
        {"number": 1, "state": "open", "title": "real issue"},
        {"number": 2, "state": "open", "title": "a PR", "pull_request": {"url": "x"}},
    ]
    out = ghi._parse_list(items)
    assert "real issue" in out
    assert "a PR" not in out
    assert ghi._parse_list([]) == "no issues"


def test_parse_issue_sample():
    d = {
        "number": 42,
        "title": "Bug",
        "state": "open",
        "user": {"login": "octocat"},
        "html_url": "https://github.com/a/b/issues/42",
        "body": "details",
    }
    out = ghi._parse_issue(d)
    assert "#42" in out and "Bug" in out
    assert "octocat" in out
    assert "details" in out


def test_create_posts_when_token_present(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    seen = {}

    def fake_post(url, body):
        seen["url"], seen["body"] = url, body
        return 201, {"number": 99, "html_url": "https://github.com/a/b/issues/99"}

    monkeypatch.setattr(ghi, "_http_post_json", fake_post)
    out = ghi.github_issues().fn(
        {"op": "create", "owner": "a", "repo": "b", "title": "T", "body": "B"}
    )
    assert "created #99" in out
    assert seen["url"].endswith("/repos/a/b/issues")
    assert seen["body"] == {"title": "T", "body": "B"}
