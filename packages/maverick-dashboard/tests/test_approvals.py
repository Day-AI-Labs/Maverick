"""Approval queue page + approve/deny endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)


def _world(tmp_path):
    from maverick.world_model import WorldModel
    return WorldModel(tmp_path / "world.db")


def test_pending_approval_shows_on_page(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    aid = _world(tmp_path).create_approval(
        "rm-rf", risk="high", scope="/tmp/build", detail="wipe build dir",
    )
    client = _client()
    r = client.get("/approvals")
    assert r.status_code == 200
    text = r.text
    assert "approval queue" in text.lower()
    assert "rm-rf" in text
    assert "/tmp/build" in text
    assert f'data-id="{aid}"' in text
    assert 'href="/approvals"' in text  # nav link present


def test_approve_transitions_state(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    w = _world(tmp_path)
    aid = w.create_approval("mass-dm", risk="high")
    client = _client()

    r = client.post(
        f"/api/v1/approvals/{aid}/approve",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    # State change is persisted in the world model.
    assert w.get_approval(aid).status == "approved"
    # No longer listed as pending.
    assert client.get("/api/v1/approvals").json()["approvals"] == []


def test_deny_transitions_state(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    w = _world(tmp_path)
    aid = w.create_approval("force-push", risk="high", scope="main")
    client = _client()

    r = client.post(
        f"/api/v1/approvals/{aid}/deny",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    assert w.get_approval(aid).status == "denied"


def test_approve_unknown_is_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.post(
        "/api/v1/approvals/9999/approve",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 404


def test_approvals_api_lists_pending(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    w = _world(tmp_path)
    w.create_approval("rm-rf", risk="high", scope="/x", detail="d")
    client = _client()
    body = client.get("/api/v1/approvals").json()
    assert len(body["approvals"]) == 1
    a = body["approvals"][0]
    assert a["action"] == "rm-rf"
    assert a["risk"] == "high"
    assert a["scope"] == "/x"
