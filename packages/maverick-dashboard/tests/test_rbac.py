"""Dashboard RBAC: the role store, role resolution, and gate enforcement.

Safety invariants under test:
  * auth OFF (no principal) -> every gate is a no-op (single-user local mode);
  * a config-pinned bootstrap admin is always admin (can't be locked out);
  * viewer is read-only, operator can run goals, only admin reaches settings/users.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


# ---------- store + role logic (no HTTP) ----------

def test_store_roundtrip_and_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick_dashboard import rbac
    assert rbac.list_users() == {}
    rbac.set_role("user:alice", "viewer")
    assert rbac.list_users() == {"user:alice": "viewer"}
    rbac.set_role("user:alice", "operator")
    assert rbac.get_stored_role("user:alice") == "operator"
    rbac.remove_user("user:alice")
    assert rbac.list_users() == {}
    with pytest.raises(ValueError):
        rbac.set_role("user:x", "superuser")
    with pytest.raises(ValueError):
        rbac.set_role("", "viewer")


def test_permissions_map():
    from maverick_dashboard import rbac
    assert "admin" in rbac.permissions_for("admin")
    assert rbac.permissions_for("operator") == frozenset({"operate", "view"})
    assert rbac.permissions_for("viewer") == frozenset({"view"})
    assert rbac.permissions_for(None) == frozenset()


def test_role_for_principal(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:boss")
    from maverick_dashboard import auth, rbac
    assert auth.role_for_principal(None) is None              # auth off -> unrestricted
    assert auth.role_for_principal("user:boss") == "admin"     # bootstrap admin
    rbac.set_role("user:v", "viewer")
    assert auth.role_for_principal("user:v") == "viewer"       # stored
    assert auth.role_for_principal("user:new") == "operator"   # default


# ---------- HTTP enforcement ----------

def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    return TestClient(dash_app.app, headers={"Origin": "http://testserver"})


def _as(monkeypatch, principal):
    """Simulate an authenticated caller with a given principal (the gates read
    caller_principal in auth.py)."""
    from maverick_dashboard import auth
    monkeypatch.setattr(auth, "caller_principal", lambda request: principal)


def test_auth_off_is_a_noop(monkeypatch, tmp_path):
    # No principal (local mode): admin surfaces stay reachable, exactly as before.
    c = _client(monkeypatch, tmp_path)
    assert c.get("/settings").status_code == 200
    assert c.get("/users").status_code == 200


def test_viewer_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "")
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:vy", "viewer")
    _as(monkeypatch, "user:vy")
    assert c.get("/settings").status_code == 403           # admin surface
    assert c.get("/users").status_code == 403
    assert c.post("/settings/capabilities", data={}).status_code == 403
    assert c.post("/chat/send", data={"title": "hi"}).status_code == 403   # operate


def test_viewer_cannot_run_goals_via_compose_or_resume(monkeypatch, tmp_path):
    # compose and resume both spend provider money (they queue run_goal_in_thread),
    # so they are "operate" actions: a read-only viewer must be 403'd before any
    # provider-key / goal-state check, exactly like /chat/send and POST /goals.
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:vz", "viewer")
    _as(monkeypatch, "user:vz")
    assert c.post("/api/v1/goals/compose",
                  json={"title": "spend money"}).status_code == 403
    assert c.post("/api/v1/goals/1/resume").status_code == 403


def test_operator_can_operate_but_not_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "")
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:op", "operator")
    _as(monkeypatch, "user:op")
    assert c.get("/settings").status_code == 403           # not admin
    # operate is allowed: chat/send clears the role gate (then 400s on no key, not 403)
    assert c.post("/chat/send", data={"title": "hi"}).status_code != 403


def test_admin_manages_users_and_cannot_be_locked_out(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:boss")
    c = _client(monkeypatch, tmp_path)
    _as(monkeypatch, "user:boss")
    assert c.get("/settings").status_code == 200
    assert c.get("/users").status_code == 200
    assert c.post("/users/set",
                  data={"principal": "user:alice", "role": "operator"}).status_code == 200
    from maverick_dashboard import auth, rbac
    assert rbac.get_stored_role("user:alice") == "operator"
    # the bootstrap admin stays admin no matter what the store says
    rbac.set_role("user:boss", "viewer")
    assert auth.role_for_principal("user:boss") == "admin"


def test_users_link_in_nav(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert 'href="/users"' in c.get("/").text
