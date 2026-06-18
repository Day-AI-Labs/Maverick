"""Cross-user isolation for /api/v1/spend and /api/v1/approvals.

Before this, any authenticated caller could read every user's runs + spend via
/spend, and any caller (even a viewer) could enumerate every parked high-risk
action via /approvals. /spend is now owner-scoped; the /approvals queue is
operator-only (matching approve/deny/claim).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick.oidc import VerifiedPrincipal
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from maverick import world_model
    from maverick_dashboard import api as api_mod
    from maverick_dashboard import app as app_mod

    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    api_mod._world_cache.clear()
    app_mod._world_cache.clear()
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    yield


def _enable_oidc(monkeypatch, *, default_role: str = "operator") -> None:
    import maverick_dashboard.auth as auth
    import maverick_dashboard.rbac as rbac

    monkeypatch.setattr(auth, "oidc_enabled", lambda: True)
    monkeypatch.setattr(rbac, "default_role", lambda: default_role)

    def _verify(token, **_kw):
        return VerifiedPrincipal(
            sub=token, issuer="https://issuer.example", audience="maverick",
            claims={"sub": token},
        )

    monkeypatch.setattr(auth, "verify_oidc_token", _verify)


def _as(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {user}", "Origin": "http://testserver"}


def _spend_goal(owner: str, cost: float) -> int:
    """A completed goal+episode owned by ``owner`` with a known cost."""
    from maverick_dashboard.app import _world
    w = _world()
    gid = w.create_goal("g", "d", owner=owner)
    eid = w.start_episode(gid)
    w.end_episode(eid, "done", "success", cost_dollars=cost,
                  input_tokens=10, output_tokens=5)
    return gid


# ---- /spend owner scoping -------------------------------------------------


def test_spend_scoped_to_caller(monkeypatch):
    _enable_oidc(monkeypatch)
    _spend_goal("user:alice", 1.00)
    _spend_goal("user:bob", 9.00)

    alice = client.get("/api/v1/spend", headers=_as("alice")).json()
    assert alice["total"]["dollars"] == pytest.approx(1.00)
    assert {e["goal_id"] for e in alice["episodes"]}  # only alice's
    assert all(e["cost_dollars"] == pytest.approx(1.00) for e in alice["episodes"])

    bob = client.get("/api/v1/spend", headers=_as("bob")).json()
    assert bob["total"]["dollars"] == pytest.approx(9.00)


def test_spend_admin_sees_all(monkeypatch):
    _enable_oidc(monkeypatch)
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:root")
    _spend_goal("user:alice", 1.00)
    _spend_goal("user:bob", 9.00)
    root = client.get("/api/v1/spend", headers=_as("root")).json()
    assert root["total"]["dollars"] == pytest.approx(10.00)


def test_spend_auth_off_unchanged():
    # No auth -> deployment-wide totals (legacy single-operator behaviour).
    _spend_goal("", 2.00)
    _spend_goal("", 3.00)
    data = client.get("/api/v1/spend").json()
    assert data["total"]["dollars"] == pytest.approx(5.00)


# ---- /approvals operator gate ---------------------------------------------


def test_approvals_list_requires_operate(monkeypatch):
    _enable_oidc(monkeypatch, default_role="viewer")
    from maverick_dashboard.app import _world
    _world().create_approval("rm -rf /", risk="high", detail="bob's secret action")
    r = client.get("/api/v1/approvals", headers=_as("viewer-vic"))
    assert r.status_code == 403


def test_approvals_list_allows_operator(monkeypatch):
    _enable_oidc(monkeypatch, default_role="operator")
    from maverick_dashboard.app import _world
    _world().create_approval("rm -rf /", risk="high", detail="x")
    r = client.get("/api/v1/approvals", headers=_as("op-olivia"))
    assert r.status_code == 200
    assert len(r.json()["approvals"]) == 1
