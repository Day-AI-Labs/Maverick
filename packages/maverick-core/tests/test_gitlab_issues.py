"""Tests for the gitlab_issues tool. No network calls."""
from __future__ import annotations

from maverick.tools import gitlab_issues as gli


def test_missing_op_errors():
    assert gli.gitlab_issues().fn({}).startswith("ERROR: op is required")


def test_list_requires_project_id():
    out = gli.gitlab_issues().fn({"op": "list"})
    assert out.startswith("ERROR")
    assert "project_id is required" in out


def test_list_requires_token(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    out = gli.gitlab_issues().fn({"op": "list", "project_id": "42"})
    assert out.startswith("ERROR: set GITLAB_TOKEN")


def test_create_requires_title(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "t")
    out = gli.gitlab_issues().fn({"op": "create", "project_id": "42"})
    assert out.startswith("ERROR")
    assert "requires title" in out


def test_url_builders_encode_project_path():
    base = "https://gitlab.com"
    # A group/path project id must be URL-encoded.
    url = gli._list_url(base, "group/repo", "opened", 25)
    assert "projects/group%2Frepo/issues?" in url
    assert "state=opened" in url
    assert gli._get_url(base, "42", 7).endswith("/projects/42/issues/7")
    assert gli._create_url(base, "42").endswith("/projects/42/issues")


def test_parse_list_and_issue():
    items = [{"iid": 3, "state": "opened", "title": "hello"}]
    assert "hello" in gli._parse_list(items)
    assert gli._parse_list([]) == "no issues"
    d = {
        "iid": 5,
        "title": "Bug",
        "state": "opened",
        "author": {"username": "dev"},
        "web_url": "https://gitlab.com/g/r/-/issues/5",
        "description": "body",
    }
    out = gli._parse_issue(d)
    assert "#5" in out and "Bug" in out and "dev" in out and "body" in out


def test_create_posts_when_token_present(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "tok")
    seen = {}

    def fake_post(url, body):
        seen["url"], seen["body"] = url, body
        return 201, {"iid": 9, "web_url": "https://gitlab.com/g/r/-/issues/9"}

    monkeypatch.setattr(gli, "_http_post_json", fake_post)
    out = gli.gitlab_issues().fn(
        {"op": "create", "project_id": "g/r", "title": "T", "body": "B"}
    )
    assert "created #9" in out
    assert "projects/g%2Fr/issues" in seen["url"]
    assert seen["body"] == {"title": "T", "description": "B"}
    # PRIVATE-TOKEN header carries the PAT.
    assert gli._headers()["PRIVATE-TOKEN"] == "tok"
