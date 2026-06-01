"""Pre-filled GitHub bug-report URL builder (`maverick report-issue`)."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import unquote

from maverick.issue_report import DEFAULT_REPO, build_issue_url, build_report

# A realistic-looking Anthropic key (matches the secret detector pattern).
_FAKE_KEY = "sk-ant-api03-AbCdEf1234567890abcdefghijklmno_PQRST"


def test_build_issue_url_encodes_title_and_body():
    url = build_issue_url("owner/repo", "a title & more", "body with spaces")
    assert url.startswith("https://github.com/owner/repo/issues/new?title=")
    assert "&body=" in url
    # Everything is percent-encoded -- no raw spaces or ampersands in the params.
    params = url.split("issues/new?", 1)[1]
    assert " " not in params
    assert "%20" in params  # space encoded, not '+'


def test_build_issue_url_truncates_long_body():
    url = build_issue_url("o/r", "t", "x" * 10_000, max_body=500)
    body = unquote(url.split("&body=", 1)[1])
    assert "[... truncated]" in body
    assert len(body) < 1_000


def test_build_report_redacts_secrets_and_includes_context():
    goal = SimpleNamespace(id=7, title="do the thing", status="failed")
    err = SimpleNamespace(agent="coder", kind="error",
                          content=f"crashed; leaked {_FAKE_KEY} in the log")
    url = build_report(goal, [err], repo="o/r", version="0.1.9")
    # The raw key must never reach the URL...
    assert _FAKE_KEY not in url
    assert "sk-ant-api03-AbCdEf" not in unquote(url)
    body = unquote(url.split("&body=", 1)[1])
    # ...but the goal context is present.
    assert "Goal #7" in body
    assert "do the thing" in body
    assert "Status: failed" in body
    assert "0.1.9" in body


def test_build_report_empty_errors_has_placeholder():
    goal = SimpleNamespace(id=1, title="t", status="succeeded")
    url = build_report(goal, [])
    assert f"github.com/{DEFAULT_REPO}/issues/new" in url
    body = unquote(url.split("&body=", 1)[1])
    assert "no error events recorded" in body.lower()
