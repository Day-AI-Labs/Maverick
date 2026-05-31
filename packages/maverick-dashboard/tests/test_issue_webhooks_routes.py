"""Inbound Linear + Jira issue-assigned webhook tests.

Mirrors test_webhook_start.py: a valid HMAC signature + an assigned-to-bot
event creates a goal (and a world-model row); an invalid signature, or a
non-assignment event, does not. The runner is monkeypatched so no real LLM
call happens.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from maverick_dashboard.app import app

client = TestClient(app)

SECRET = "test-webhook-secret"
LINEAR_BOT = "linear-bot-id"
JIRA_BOT = "jira-bot-account-id"


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    # Reset the dashboard's per-DB-path WorldModel cache so each test gets
    # its own DB (the cache keys on DEFAULT_DB, which we just repointed).
    from maverick_dashboard import app as app_mod
    app_mod._world_cache.clear()
    yield


@pytest.fixture
def _no_real_run(monkeypatch):
    """Stub the background runner so the route returns immediately."""
    import maverick.runner as runner_mod
    called = []

    def fake_run(goal_id, max_dollars=None, max_wall_seconds=None, max_depth=3):
        called.append((goal_id, max_dollars))

    monkeypatch.setattr(runner_mod, "run_goal_in_thread", fake_run)
    return called


@pytest.fixture
def _configured(monkeypatch):
    monkeypatch.setenv("MAVERICK_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("MAVERICK_BOT_LINEAR_ID", LINEAR_BOT)
    monkeypatch.setenv("MAVERICK_BOT_JIRA_ACCOUNT_ID", JIRA_BOT)


def _linear_assigned(assignee_id=LINEAR_BOT):
    return {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "uuid-1",
            "identifier": "ENG-123",
            "title": "Fix the login bug",
            "description": "Users can't log in on Safari.",
            "assigneeId": assignee_id,
            "assignee": {"id": assignee_id, "email": "bot@example.com"},
        },
    }


def _jira_assigned(account_id=JIRA_BOT):
    return {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "PROJ-7",
            "fields": {
                "summary": "Add a retry to the uploader",
                "description": {
                    "type": "doc", "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Uploads fail under load."}],
                    }],
                },
                "assignee": {"accountId": account_id, "emailAddress": "bot@example.com"},
            },
        },
    }


# ----- Linear -----

def test_linear_valid_signature_assigned_to_bot_creates_goal(_configured, _no_real_run):
    body = json.dumps(_linear_assigned()).encode()
    resp = client.post(
        "/webhook/linear", content=body,
        headers={"Linear-Signature": _sign(body)},
    )
    assert resp.status_code == 201
    goal_id = resp.json()["goal_id"]
    assert isinstance(goal_id, int)
    assert len(_no_real_run) == 1 and _no_real_run[0][0] == goal_id

    # The goal row really landed in the world model with the issue content.
    from maverick.world_model import DEFAULT_DB, WorldModel
    g = WorldModel(DEFAULT_DB).get_goal(goal_id)
    assert g is not None
    assert g.status == "pending"
    assert "ENG-123" in g.title
    assert "Fix the login bug" in g.title
    assert "Users can't log in on Safari." in g.description


def test_linear_invalid_signature_rejected(_configured, _no_real_run):
    body = json.dumps(_linear_assigned()).encode()
    resp = client.post(
        "/webhook/linear", content=body,
        headers={"Linear-Signature": "deadbeef"},
    )
    assert resp.status_code == 403
    assert _no_real_run == []


def test_linear_assigned_to_someone_else_ignored(_configured, _no_real_run):
    body = json.dumps(_linear_assigned(assignee_id="some-other-human")).encode()
    resp = client.post(
        "/webhook/linear", content=body,
        headers={"Linear-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] is True
    assert _no_real_run == []


def test_linear_non_assign_event_ignored(_configured, _no_real_run):
    # A comment event (wrong type) must not spawn a goal even when signed.
    payload = {"type": "Comment", "action": "create", "data": {"id": "c1"}}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/linear", content=body,
        headers={"Linear-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] is True
    assert _no_real_run == []


# ----- Jira -----

def test_jira_valid_signature_assigned_to_bot_creates_goal(_configured, _no_real_run):
    body = json.dumps(_jira_assigned()).encode()
    resp = client.post(
        "/webhook/jira", content=body,
        headers={"X-Hub-Signature": "sha256=" + _sign(body)},
    )
    assert resp.status_code == 201
    goal_id = resp.json()["goal_id"]
    assert isinstance(goal_id, int)
    assert len(_no_real_run) == 1 and _no_real_run[0][0] == goal_id

    from maverick.world_model import DEFAULT_DB, WorldModel
    g = WorldModel(DEFAULT_DB).get_goal(goal_id)
    assert g is not None
    assert g.status == "pending"
    assert "PROJ-7" in g.title
    assert "Add a retry to the uploader" in g.title
    assert "Uploads fail under load." in g.description


def test_jira_invalid_signature_rejected(_configured, _no_real_run):
    body = json.dumps(_jira_assigned()).encode()
    resp = client.post(
        "/webhook/jira", content=body,
        headers={"X-Hub-Signature": "sha256=deadbeef"},
    )
    assert resp.status_code == 403
    assert _no_real_run == []


def test_jira_assigned_to_someone_else_ignored(_configured, _no_real_run):
    body = json.dumps(_jira_assigned(account_id="other-human")).encode()
    resp = client.post(
        "/webhook/jira", content=body,
        headers={"X-Hub-Signature": "sha256=" + _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] is True
    assert _no_real_run == []


# ----- shared auth -----

def test_no_secret_configured_fails_closed(monkeypatch, _no_real_run):
    monkeypatch.delenv("MAVERICK_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    import maverick.webhooks as wh
    monkeypatch.setattr(wh, "_load_config_outbound", lambda: ([], None))

    body = json.dumps(_linear_assigned()).encode()
    resp = client.post(
        "/webhook/linear", content=body,
        headers={"Linear-Signature": _sign(body)},
    )
    assert resp.status_code == 401
    assert _no_real_run == []


def test_linear_oversized_content_length_rejected_before_signature_check(
    _configured, _no_real_run, monkeypatch,
):
    import maverick.issue_webhooks as iw
    from maverick_dashboard import app as app_mod

    def fail_verify(*args, **kwargs):
        raise AssertionError("signature verification should not run for oversized bodies")

    monkeypatch.setattr(iw, "verify_signature", fail_verify)
    body = b"x" * (app_mod._MAX_WEBHOOK_BODY_BYTES + 1)
    resp = client.post(
        "/webhook/linear",
        content=body,
        headers={"Linear-Signature": "invalid"},
    )
    assert resp.status_code == 413
    assert _no_real_run == []
