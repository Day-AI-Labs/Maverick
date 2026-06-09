"""GitHub App webhook route (/webhook/github) — issue→PR receiver wiring."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _labeled_issue(label="maverick"):
    return {
        "action": "labeled",
        "repository": {"full_name": "acme/widgets"},
        "issue": {"number": 7, "title": "Fix the bug", "body": "details"},
        "label": {"name": label},
        "sender": {"login": "alice"},
    }


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("MAVERICK_GH_APP_WEBHOOK_SECRET", "shh")  # pragma: allowlist secret


def test_rejects_bad_signature():
    body = json.dumps(_labeled_issue()).encode()
    r = _client().post("/webhook/github", content=body,
                       headers={"X-GitHub-Event": "issues",
                                "X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 401


def test_accepts_trigger_and_schedules(monkeypatch):
    ran = {}

    async def _fake_process(payload, **kw):
        ran["issue"] = payload.issue_number

    monkeypatch.setattr("maverick.github_app.process_issue", _fake_process)
    body = json.dumps(_labeled_issue()).encode()
    r = _client().post("/webhook/github", content=body,
                       headers={"X-GitHub-Event": "issues",
                                "X-Hub-Signature-256": _sig(body, "shh")})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["issue"] == 7
    assert ran.get("issue") == 7  # background task ran (TestClient runs them)


def test_ignores_non_trigger_label():
    body = json.dumps(_labeled_issue(label="wontfix")).encode()
    r = _client().post("/webhook/github", content=body,
                       headers={"X-GitHub-Event": "issues",
                                "X-Hub-Signature-256": _sig(body, "shh")})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_route_is_auth_exempt():
    # The webhook authenticates by HMAC, so it must bypass the bearer gate.
    from maverick_dashboard.app import _AUTH_EXEMPT
    assert "/webhook/github" in _AUTH_EXEMPT
