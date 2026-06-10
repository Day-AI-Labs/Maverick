"""Collaborative supervision API: claim/release/attribution on approvals."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard import app as app_mod
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    app_mod._world_cache.clear()
    yield


def _park():
    return app_mod._world().create_approval(
        "wire_transfer", risk="high", scope="acct", detail="$5k")


def test_claim_release_roundtrip():
    aid = _park()
    r = client.post(f"/api/v1/approvals/{aid}/claim")
    assert r.status_code == 200 and r.json() == {"claimed_by": "operator"}
    listing = client.get("/api/v1/approvals").json()["approvals"]
    assert listing[0]["claimed_by"] == "operator"
    assert client.post(f"/api/v1/approvals/{aid}/release").json() == {"released": True}
    assert client.get("/api/v1/approvals").json()["approvals"][0]["claimed_by"] is None


def test_conflicting_claim_409(monkeypatch):
    aid = _park()
    app_mod._world().claim_approval(aid, "alice")
    r = client.post(f"/api/v1/approvals/{aid}/claim")
    assert r.status_code == 409 and "alice" in r.json()["detail"]
    # Release without holding -> 409 too.
    assert client.post(f"/api/v1/approvals/{aid}/release").status_code == 409


def test_decide_records_supervisor():
    aid = _park()
    assert client.post(f"/api/v1/approvals/{aid}/approve").status_code == 204
    a = app_mod._world().get_approval(aid)
    assert a.status == "approved" and a.decided_by == "operator"


def test_unknown_approval_404():
    assert client.post("/api/v1/approvals/424242/claim").status_code == 404
