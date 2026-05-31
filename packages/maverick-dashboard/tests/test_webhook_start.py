"""Inbound webhook tests: POST /webhook/start (HMAC-signed).

A valid X-Maverick-Signature creates a goal (and a row in the world
model); a missing or invalid signature is rejected. The runner is
monkeypatched so no real LLM call happens.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from maverick_dashboard.app import app

# /webhook/start authenticates via HMAC, not the dashboard bearer / Origin,
# so no Origin header is needed (it's in _AUTH_EXEMPT).
client = TestClient(app)

SECRET = "test-webhook-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
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


def test_valid_signature_creates_goal(_configured, _no_real_run):
    body = json.dumps({"title": "ship it", "description": "do the thing"}).encode()
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": _sign(body)},
    )
    assert resp.status_code == 201
    goal_id = resp.json()["goal_id"]
    assert isinstance(goal_id, int)
    assert len(_no_real_run) == 1
    assert _no_real_run[0][0] == goal_id

    # The goal row really landed in the world model.
    from maverick.world_model import DEFAULT_DB, WorldModel
    g = WorldModel(DEFAULT_DB).get_goal(goal_id)
    assert g is not None
    assert g.title == "ship it"
    assert g.status == "pending"


def test_budget_propagates_to_runner(_configured, _no_real_run):
    body = json.dumps({"title": "capped", "budget": 1.5}).encode()
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": _sign(body)},
    )
    assert resp.status_code == 201
    assert _no_real_run[0][1] == 1.5


def test_invalid_signature_rejected(_configured, _no_real_run):
    body = json.dumps({"title": "spoof"}).encode()
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": "sha256=deadbeef"},
    )
    assert resp.status_code == 403
    assert _no_real_run == []


def test_missing_signature_rejected(_configured, _no_real_run):
    body = json.dumps({"title": "spoof"}).encode()
    resp = client.post("/webhook/start", content=body)
    assert resp.status_code == 403
    assert _no_real_run == []


def test_no_secret_configured_fails_closed(monkeypatch, _no_real_run):
    monkeypatch.delenv("MAVERICK_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    # Make config-based secret resolution return nothing too.
    import maverick.webhooks as wh
    monkeypatch.setattr(wh, "_load_config_outbound", lambda: ([], None))

    body = json.dumps({"title": "x"}).encode()
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": _sign(body)},
    )
    assert resp.status_code == 401
    assert _no_real_run == []


def test_missing_title_rejected(_configured, _no_real_run):
    body = json.dumps({"description": "no title"}).encode()
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": _sign(body)},
    )
    assert resp.status_code == 400
    assert _no_real_run == []


def test_oversized_content_length_rejected_before_signature_check(
    _configured, _no_real_run, monkeypatch,
):
    import maverick.webhooks as wh
    from maverick_dashboard import app as app_mod

    def fail_verify(*args, **kwargs):
        raise AssertionError("signature verification should not run for oversized bodies")

    monkeypatch.setattr(wh, "verify_signature", fail_verify)
    body = b"x" * (app_mod._MAX_WEBHOOK_BODY_BYTES + 1)
    resp = client.post(
        "/webhook/start",
        content=body,
        headers={"X-Maverick-Signature": "sha256=invalid"},
    )
    assert resp.status_code == 413
    assert _no_real_run == []


def test_missing_signature_rejected_without_reading_body(_configured, _no_real_run, monkeypatch):
    from maverick_dashboard import app as app_mod

    async def fail_read(request):
        raise AssertionError("body should not be read when signature is missing")

    monkeypatch.setattr(app_mod, "_read_limited_webhook_body", fail_read)
    resp = client.post("/webhook/start", content=b"x")
    assert resp.status_code == 403
    assert _no_real_run == []


def test_lengthless_webhook_body_stream_is_bounded():
    from maverick_dashboard import app as app_mod

    class ChunkedRequest:
        headers = {}

        async def stream(self):
            yield b"x" * app_mod._MAX_WEBHOOK_BODY_BYTES
            yield b"x"

    async def read():
        await app_mod._read_limited_webhook_body(ChunkedRequest())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(read())
    assert exc.value.status_code == 413
