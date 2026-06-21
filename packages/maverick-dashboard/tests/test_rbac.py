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


def test_concurrent_set_role_does_not_lose_assignments(monkeypatch, tmp_path):
    """set_role does a load-modify-save; without the lock two concurrent role
    assignments both load the same roster and the second drops the first -- a
    lost role grant/revoke on a security store. All N must survive."""
    import threading

    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick_dashboard import rbac
    n = 24

    def assign(i: int):
        rbac.set_role(f"user:u{i:03d}", "viewer")

    threads = [threading.Thread(target=assign, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rbac.list_users()) == n
    assert list((tmp_path / ".maverick").glob("*.tmp")) == []


def test_permissions_map():
    from maverick_dashboard import rbac
    assert "admin" in rbac.permissions_for("admin")
    assert rbac.permissions_for("operator") == frozenset({"operate", "view"})
    assert rbac.permissions_for("viewer") == frozenset({"view"})
    assert rbac.permissions_for(None) == frozenset()
    # Separation of duties: only admin and the dedicated auditor role hold the
    # "audit" permission; operator/viewer never do. The auditor grants ONLY
    # read access (audit + view), nothing operational.
    assert rbac.permissions_for("auditor") == frozenset({"audit", "view"})
    assert "audit" in rbac.permissions_for("admin")
    assert "audit" not in rbac.permissions_for("operator")
    assert "audit" not in rbac.permissions_for("viewer")
    assert "operate" not in rbac.permissions_for("auditor")
    assert "admin" not in rbac.permissions_for("auditor")
    assert "auditor" in rbac.ROLES


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


def test_viewer_cannot_run_create_or_delete_fleets(monkeypatch, tmp_path):
    # The fleet routes (run/create/delete) dispatch governed goals and mutate
    # fleet config -- "operate" actions. They are owner-scoped, but owner-scoping
    # is not authz: a viewer could self-own a created fleet and then run it. A
    # read-only viewer must be 403'd before any provider-key / owner check, just
    # like compose/resume. Regression for the missing require_permission gate.
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:vf", "viewer")
    _as(monkeypatch, "user:vf")
    assert c.post("/api/v1/fleets/myfleet/run",
                  json={"agent": "a", "prompt": "spend money"}).status_code == 403
    assert c.post("/api/v1/fleets",
                  json={"name": "myfleet", "agents": []}).status_code == 403
    assert c.delete("/api/v1/fleets/myfleet").status_code == 403


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


def test_audit_endpoints_require_audit_permission(monkeypatch, tmp_path):
    # The audit trail (who-did-what-when) is gated by the "audit" permission:
    # an operator/viewer is 403'd, auth-off (local mode) and admin get through.
    # Regression for the gap where /api/v1/audit/tail + /audit/grep had no gate.
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "")
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:op2", "operator")
    _as(monkeypatch, "user:op2")
    assert c.get("/api/v1/audit/tail").status_code == 403
    assert c.get("/api/v1/audit/grep?pattern=x").status_code == 403
    # a viewer is likewise 403'd: read-of-the-trail is a distinct grant.
    rbac.set_role("user:vw2", "viewer")
    _as(monkeypatch, "user:vw2")
    assert c.get("/api/v1/audit/tail").status_code == 403
    # auth-off (no principal -> local single-user mode) is unrestricted.
    _as(monkeypatch, None)
    assert c.get("/api/v1/audit/tail").status_code == 200


def test_auditor_reads_audit_but_nothing_operational(monkeypatch, tmp_path):
    # Separation of duties: the auditor role reaches the audit trail (read-only)
    # but is 403'd from every operate/admin surface -- it can review the
    # who-did-what-when record without being able to run goals, change settings,
    # or manage users.
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "")
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:aud", "auditor")
    _as(monkeypatch, "user:aud")
    # audit surface: reachable (200, not 403).
    assert c.get("/api/v1/audit/tail").status_code == 200
    assert c.get("/api/v1/audit/grep?pattern=x").status_code == 200
    # admin surfaces: denied.
    assert c.get("/settings").status_code == 403
    assert c.get("/users").status_code == 403
    # operate surfaces: denied (no running goals, no spending).
    assert c.post("/chat/send", data={"title": "hi"}).status_code == 403
    assert c.post("/api/v1/goals/compose",
                  json={"title": "spend money"}).status_code == 403


def test_viewer_cannot_mutate_owned_goal(monkeypatch, tmp_path):
    # answer/retitle/reparent are "operate" actions. A viewer who OWNS a goal
    # (so the access check passes) must still be 403'd by the role gate -- owner
    # access is not authz. Regression for the missing require_permission gate.
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:vm", "viewer")
    from maverick.world_model import WorldModel
    gid = WorldModel(tmp_path / "world.db").create_goal("owned", owner="user:vm")
    _as(monkeypatch, "user:vm")
    assert c.post(f"/api/v1/goals/{gid}/answer",
                  json={"question_id": 1, "answer": "x"}).status_code == 403
    assert c.post(f"/api/v1/goals/{gid}/retitle",
                  json={"title": "new"}).status_code == 403
    assert c.post(f"/api/v1/goals/{gid}/reparent",
                  json={"parent_id": None}).status_code == 403


def test_redact_preview_requires_operate(monkeypatch, tmp_path):
    # /redact/preview ran the detector pipeline on caller text unauthenticated;
    # it now requires "operate" (a viewer is 403'd).
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import rbac
    rbac.set_role("user:vp", "viewer")
    _as(monkeypatch, "user:vp")
    assert c.post("/api/v1/redact/preview", json={"text": "hi"}).status_code == 403


def test_validate_agent_override_requires_pack_admin(monkeypatch, tmp_path):
    # /agents/{name}/validate (pack-edit lint) was unauthenticated; it now uses
    # the same pack-admin gate as save/delete override.
    c = _client(monkeypatch, tmp_path)
    from maverick_dashboard import api
    monkeypatch.setattr(api, "caller_principal", lambda request: "user:alice")
    monkeypatch.setattr(api, "is_dashboard_admin", lambda principal: False)
    assert c.post("/api/v1/agents/orchestrator/validate", json={}).status_code == 403
