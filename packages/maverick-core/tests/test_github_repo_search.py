"""Tests for the github_repo_search tool. No network calls."""
from __future__ import annotations

from maverick.tools import github_repo_search as ghs


def test_missing_query_errors():
    out = ghs.github_repo_search().fn({"op": "repos", "query": "  "})
    assert out.startswith("ERROR")
    assert "query is required" in out


def test_unknown_op_errors():
    out = ghs.github_repo_search().fn({"op": "nope", "query": "x"})
    assert out.startswith("ERROR: unknown op")


def test_code_op_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = ghs.github_repo_search().fn({"op": "code", "query": "addNote"})
    assert out.startswith("ERROR: set GITHUB_TOKEN")


def test_build_url_repos_and_code():
    repo_url = ghs._build_url("repos", "tetris language:python", 5)
    assert repo_url.startswith("https://api.github.com/search/repositories?")
    assert "q=tetris+language%3Apython" in repo_url
    assert "per_page=5" in repo_url
    code_url = ghs._build_url("code", "addNote", 200)
    assert code_url.startswith("https://api.github.com/search/code?")
    # per_page is clamped to 100.
    assert "per_page=100" in code_url


def test_parse_repos_sample():
    data = {
        "items": [
            {"full_name": "a/b", "stargazers_count": 12, "description": "hi"},
            {"full_name": "c/d", "stargazers_count": 0, "description": None},
        ]
    }
    out = ghs._parse_repos(data)
    assert "a/b" in out and "★12" in out
    assert "c/d" in out
    assert ghs._parse_repos({"items": []}) == "no repositories"


def test_parse_code_sample():
    data = {
        "items": [
            {"path": "src/x.py", "repository": {"full_name": "a/b"}},
        ]
    }
    out = ghs._parse_code(data)
    assert "a/b" in out and "src/x.py" in out
    assert ghs._parse_code({"items": []}) == "no code matches"


def test_run_uses_token_header(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return 200, {"items": [{"full_name": "a/b", "stargazers_count": 1}]}

    monkeypatch.setattr(ghs, "_http_get_json", fake_get)
    out = ghs.github_repo_search().fn({"op": "repos", "query": "foo"})
    assert "a/b" in out
    assert "/search/repositories" in captured["url"]
    # The Bearer header is built from the env token.
    assert ghs._headers()["Authorization"] == "Bearer tok123"
