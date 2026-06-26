"""Admin tenant-provisioning API (/api/v1/admin/tenants).

A control-plane surface so operators can spin tenants up/down over HTTP instead
of shelling in for `maverick tenant ...`. Auth-off TestClient => the local
caller is admin (matches the rest of the API). The registry and per-tenant
workspaces are isolated under a temp MAVERICK_HOME so nothing touches real data.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    yield


def test_create_list_get_roundtrip():
    r = client.post("/api/v1/admin/tenants", json={"id": "acme", "plan": "enterprise"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "acme"
    assert body["plan"] == "enterprise"
    assert body["status"] == "active"
    # The response tells the operator where to drop acme's own config.toml.
    assert body["config_path"].endswith("/config.toml")
    assert "tenants/acme/" in body["config_path"].replace("\\", "/")

    # It shows up in the list and is fetchable.
    assert any(t["id"] == "acme" for t in client.get("/api/v1/admin/tenants").json())
    assert client.get("/api/v1/admin/tenants/acme").json()["plan"] == "enterprise"


def test_duplicate_is_409():
    assert client.post("/api/v1/admin/tenants", json={"id": "dup"}).status_code == 201
    assert client.post("/api/v1/admin/tenants", json={"id": "dup"}).status_code == 409


def test_unknown_tenant_is_404():
    assert client.get("/api/v1/admin/tenants/ghost").status_code == 404
    assert client.post("/api/v1/admin/tenants/ghost/suspend").status_code == 404


def test_suspend_resume_plan_quota():
    client.post("/api/v1/admin/tenants", json={"id": "acme", "plan": "free"})

    assert client.post("/api/v1/admin/tenants/acme/suspend").json()["status"] == "suspended"
    assert client.post("/api/v1/admin/tenants/acme/resume").json()["status"] == "active"

    assert client.post(
        "/api/v1/admin/tenants/acme/plan", json={"plan": "pro"}
    ).json()["plan"] == "pro"

    out = client.post(
        "/api/v1/admin/tenants/acme/quota", json={"max_daily_dollars": 42.5}
    ).json()
    assert out["max_daily_dollars"] == 42.5


def test_bad_plan_rejected_by_schema():
    r = client.post("/api/v1/admin/tenants", json={"id": "acme", "plan": "platinum"})
    assert r.status_code == 422  # not a valid plan enum


def test_delete_removes_tenant():
    client.post("/api/v1/admin/tenants", json={"id": "acme"})
    assert client.request("DELETE", "/api/v1/admin/tenants/acme").status_code == 204
    assert client.get("/api/v1/admin/tenants/acme").status_code == 404


def test_admin_required_when_caller_is_viewer(monkeypatch):
    """A non-admin authenticated caller is forbidden (403)."""
    import maverick_dashboard.auth as auth
    # Simulate an authenticated, non-admin principal: has_permission consults
    # the caller's role, and "view" lacks "admin".
    monkeypatch.setattr(auth, "caller_principal", lambda request: "user:viewer")
    monkeypatch.setattr(auth, "role_for_principal", lambda principal: "viewer")
    monkeypatch.setattr(auth, "global_role_for_principal", lambda principal: "viewer")
    assert client.get("/api/v1/admin/tenants").status_code == 403
    assert client.post("/api/v1/admin/tenants", json={"id": "x"}).status_code == 403


def test_tenant_admin_cannot_manage_other_tenant_roles(monkeypatch):
    """Tenant-scoped admin must not satisfy global tenant-admin APIs."""
    from maverick.paths import reset_tenant, set_tenant
    from maverick_dashboard import auth, rbac

    assert client.post("/api/v1/admin/tenants", json={"id": "acme"}).status_code == 201
    assert client.post("/api/v1/admin/tenants", json={"id": "globex"}).status_code == 201
    rbac.set_role("user:alice", "viewer")
    rbac.set_tenant_role("acme", "user:alice", "admin")
    monkeypatch.setattr(auth, "caller_principal", lambda request: "user:alice")

    tok = set_tenant("acme")
    try:
        assert auth.role_for_principal("user:alice") == "admin"
        r = client.put(
            "/api/v1/admin/tenants/globex/roles/user:bob",
            json={"role": "viewer"},
        )
    finally:
        reset_tenant(tok)

    assert r.status_code == 403
    assert rbac.get_tenant_role("globex", "user:bob") is None
