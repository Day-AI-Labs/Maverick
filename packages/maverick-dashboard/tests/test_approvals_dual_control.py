"""N-of-M dual control through the dashboard approve/deny/state API."""
from __future__ import annotations

from fastapi.testclient import TestClient

_ORIGIN = {"Origin": "http://testserver"}


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


def test_quorum_needs_two_distinct_approvers(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    w = _world(tmp_path)
    aid = w.create_approval("wire $1M", risk="critical", approvals_required=2)
    from maverick_dashboard import api
    c = _client()

    monkeypatch.setattr(api, "_supervisor", lambda r: "u:alice")
    assert c.post(f"/api/v1/approvals/{aid}/approve", headers=_ORIGIN).status_code == 204
    assert w.get_approval(aid).status == "pending"          # one vote: not yet

    monkeypatch.setattr(api, "_supervisor", lambda r: "u:bob")
    assert c.post(f"/api/v1/approvals/{aid}/approve", headers=_ORIGIN).status_code == 204
    assert w.get_approval(aid).status == "approved"         # quorum met

    st = c.get(f"/api/v1/approvals/{aid}/state").json()
    assert st["approvals_required"] == 2 and st["approved_count"] == 2
    assert st["status"] == "approved"


def test_self_approval_barred_returns_403(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    w = _world(tmp_path)
    aid = w.create_approval("wire $1M", risk="critical", approvals_required=2,
                            requested_by="u:alice")
    from maverick_dashboard import api
    monkeypatch.setattr(api, "_supervisor", lambda r: "u:alice")
    monkeypatch.setattr("maverick.safety.dual_control.allow_self_approval",
                        lambda: False)
    r = _client().post(f"/api/v1/approvals/{aid}/approve", headers=_ORIGIN)
    assert r.status_code == 403
    assert "segregation of duties" in r.json()["detail"]
    assert w.get_approval(aid).status == "pending"          # vote not counted


def test_unknown_approval_still_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick_dashboard import api
    monkeypatch.setattr(api, "_supervisor", lambda r: "u:alice")
    r = _client().post("/api/v1/approvals/4242/approve", headers=_ORIGIN)
    assert r.status_code == 404


def test_state_endpoint_unknown_is_404(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert _client().get("/api/v1/approvals/4242/state").status_code == 404
