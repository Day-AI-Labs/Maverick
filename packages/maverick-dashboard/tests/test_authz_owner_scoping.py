"""Owner-scoped multi-tenant authorization tests (stage 2).

The audit's one HIGH finding: with multi-user OIDC on, any authenticated user
could read/control ANY user's goals. These tests prove the fix -- every goal
route (and the fleets surface) is scoped to the caller's principal, with admins
and the auth-OFF single-user path bypassing the scoping.

Hermetic, like ``test_oidc_gate.py``: no real crypto/JWT/network. We monkeypatch
the OIDC seam so a request's ``Authorization: Bearer <name>`` header maps to a
``VerifiedPrincipal`` with ``sub == <name>`` (principal ``user:<name>``). The
WorldModel is pointed at a fresh tmp DB per test, and ``run_goal_in_thread`` is
neutered so POSTs don't spawn a real agent.
"""
from __future__ import annotations

import maverick_dashboard.auth as auth
import pytest
from fastapi.testclient import TestClient
from maverick.oidc import VerifiedPrincipal
from maverick_dashboard.app import app

client = TestClient(app)


# ----------------------------- fixtures / helpers -----------------------------


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fresh WorldModel on a tmp DB, shared by both ``_world()`` caches.

    api.py and app.py keep separate per-path caches but both read
    ``world_model.DEFAULT_DB``; pointing it at a unique tmp file gives each
    test an isolated DB that both surfaces agree on.
    """
    from maverick import world_model

    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    # Drop any cached WorldModel from a prior test so the new DEFAULT_DB binds.
    from maverick_dashboard import api as api_mod
    from maverick_dashboard import app as app_mod

    api_mod._world_cache.clear()
    app_mod._world_cache.clear()
    return world_model.WorldModel(db)


def _enable_oidc_principal_map(monkeypatch):
    """OIDC on; the bearer token string *is* the subject.

    ``Bearer alice`` -> principal ``user:alice``. Lets each request act as a
    chosen user with no real JWT.
    """
    monkeypatch.setattr(auth, "oidc_enabled", lambda: True)

    def _verify(token, **_kw):
        return VerifiedPrincipal(
            sub=token, issuer="https://issuer.example", audience="maverick",
            claims={"sub": token},
        )

    monkeypatch.setattr(auth, "verify_oidc_token", _verify)


def _origin() -> dict:
    """Same-origin header so mutating POSTs pass the central CSRF check.

    In loopback/no-token mode (the test setup) the bearer_auth middleware
    same-origin-gates every mutating method before the route runs; without a
    matching Origin a POST 403s regardless of ownership.
    """
    return {"Origin": "http://testserver"}


def _as(user: str, *, post: bool = False) -> dict:
    """Headers acting as ``user`` (principal ``user:<user>``).

    ``post=True`` also adds the same-origin header required by mutating routes.
    """
    headers = {"Authorization": f"Bearer {user}"}
    if post:
        headers.update(_origin())
    return headers


@pytest.fixture
def no_run(monkeypatch):
    """Neuter the background runner so POST /goals doesn't spawn an agent."""
    import maverick.runner as runner

    monkeypatch.setattr(runner, "run_goal_in_thread", lambda *a, **k: None)
    # Generous rate cap so a test that creates several goals never 429s; the
    # global ceiling derives as 10x this.
    monkeypatch.setenv("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "1000")
    # A provider key so create_goal passes the "no LLM configured" guard.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")


# ------------------------------- REST: GET / list -----------------------------


def test_owner_can_get_own_goal(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    resp = client.get(f"/api/v1/goals/{gid}", headers=_as("alice"))
    assert resp.status_code == 200
    assert resp.json()["id"] == gid


def test_different_principal_gets_404_on_get(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    resp = client.get(f"/api/v1/goals/{gid}", headers=_as("mallory"))
    assert resp.status_code == 404
    # 404 not 403: never reveal the goal exists.
    assert resp.json()["detail"] == "no such goal"


def test_cross_user_404_on_every_readonly_byid_route(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    for path in (
        f"/api/v1/goals/{gid}",
        f"/api/v1/goals/{gid}/events",
        f"/api/v1/goals/{gid}/open_questions",
        f"/api/v1/goals/{gid}/attachments",
    ):
        r = client.get(path, headers=_as("mallory"))
        assert r.status_code == 404, f"{path} leaked to a non-owner ({r.status_code})"


def test_cross_user_404_on_mutating_byid_routes(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    # cancel
    assert client.post(
        f"/api/v1/goals/{gid}/cancel", headers=_as("mallory", post=True)
    ).status_code == 404
    # answer
    r = client.post(
        f"/api/v1/goals/{gid}/answer",
        json={"question_id": 1, "answer": "x"},
        headers=_as("mallory", post=True),
    )
    assert r.status_code == 404
    # The goal must still be untouched (not cancelled by the failed attempt).
    assert world.get_goal(gid).status == "pending"


def test_cross_user_404_on_upload_attachment(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    resp = client.post(
        f"/api/v1/goals/{gid}/attachments",
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=_as("mallory", post=True),
    )
    assert resp.status_code == 404
    # Nothing was stored against the goal.
    assert world.list_attachments(gid) == []


def test_cross_user_404_on_resume(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    world.set_goal_status(gid, "cancelled")
    resp = client.post(f"/api/v1/goals/{gid}/resume", headers=_as("mallory", post=True))
    assert resp.status_code == 404
    assert world.get_goal(gid).status == "cancelled"


def test_owner_can_cancel_and_resume_own_goal(world, monkeypatch, no_run):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    assert client.post(
        f"/api/v1/goals/{gid}/cancel", headers=_as("alice", post=True)
    ).status_code == 204
    assert world.get_goal(gid).status == "cancelled"
    assert client.post(
        f"/api/v1/goals/{gid}/resume", headers=_as("alice", post=True)
    ).status_code == 204
    assert world.get_goal(gid).status == "pending"


def test_list_goals_scoped_to_caller(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    a1 = world.create_goal("a-one", owner="user:alice")
    a2 = world.create_goal("a-two", owner="user:alice")
    world.create_goal("b-one", owner="user:bob")
    world.create_goal("legacy", owner="")  # unowned legacy goal

    ids = {g["id"] for g in client.get("/api/v1/goals", headers=_as("alice")).json()}
    assert ids == {a1, a2}  # not bob's, not the legacy unowned one


def test_create_goal_stamps_caller_as_owner(world, monkeypatch, no_run):
    _enable_oidc_principal_map(monkeypatch)
    resp = client.post(
        "/api/v1/goals", json={"title": "stamp me"}, headers=_as("alice", post=True),
    )
    assert resp.status_code == 201
    gid = resp.json()["id"]
    assert world.get_goal(gid).owner == "user:alice"


# --------------------------------- REST: admin --------------------------------


def test_admin_sees_and_controls_all(world, monkeypatch, no_run):
    _enable_oidc_principal_map(monkeypatch)
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:root")
    a = world.create_goal("a-one", owner="user:alice")
    b = world.create_goal("b-one", owner="user:bob")

    # Admin lists everything (both owners + any others).
    ids = {g["id"] for g in client.get("/api/v1/goals", headers=_as("root")).json()}
    assert {a, b} <= ids
    # Admin reads another user's goal.
    assert client.get(f"/api/v1/goals/{a}", headers=_as("root")).status_code == 200
    # Admin cancels another user's goal.
    assert client.post(
        f"/api/v1/goals/{b}/cancel", headers=_as("root", post=True)
    ).status_code == 204
    assert world.get_goal(b).status == "cancelled"


def test_admin_via_config_admins_list(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    # No env override -> admins come from [dashboard] admins in config.
    monkeypatch.delenv("MAVERICK_DASHBOARD_ADMINS", raising=False)
    import maverick.config as config

    monkeypatch.setattr(config, "load_config", lambda *a, **k: {"dashboard": {"admins": ["user:root"]}})
    gid = world.create_goal("alice's goal", owner="user:alice")
    assert client.get(f"/api/v1/goals/{gid}", headers=_as("root")).status_code == 200
    # A non-listed user is still blocked.
    assert client.get(f"/api/v1/goals/{gid}", headers=_as("mallory")).status_code == 404


# ------------------------------- REST: auth OFF -------------------------------


def test_auth_off_sees_all_goals(world, monkeypatch):
    """OIDC off (single-user): listing is unscoped -- the #1 regression risk."""
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    a = world.create_goal("a-one", owner="user:alice")
    b = world.create_goal("b-one", owner="user:bob")
    legacy = world.create_goal("legacy", owner="")
    ids = {g["id"] for g in client.get("/api/v1/goals").json()}
    assert ids == {a, b, legacy}


def test_auth_off_can_get_and_mutate_any_goal(world, monkeypatch, no_run):
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    gid = world.create_goal("owned-by-someone", owner="user:alice")
    assert client.get(f"/api/v1/goals/{gid}").status_code == 200
    assert client.post(f"/api/v1/goals/{gid}/cancel", headers=_origin()).status_code == 204
    assert world.get_goal(gid).status == "cancelled"


def test_auth_off_create_leaves_owner_empty(world, monkeypatch, no_run):
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    resp = client.post(
        "/api/v1/goals", json={"title": "no owner"}, headers=_origin(),
    )
    assert resp.status_code == 201
    assert world.get_goal(resp.json()["id"]).owner == ""


# ---------------------------------- HTML pages --------------------------------


def test_goals_page_filters_to_caller(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    world.create_goal("alice-secret-goal", owner="user:alice")
    world.create_goal("bob-secret-goal", owner="user:bob")
    body = client.get("/goals", headers=_as("alice")).text
    assert "alice-secret-goal" in body
    assert "bob-secret-goal" not in body


def test_chat_goal_page_cross_user_404(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    gid = world.create_goal("alice's goal", owner="user:alice")
    assert client.get(f"/chat/goal/{gid}", headers=_as("alice")).status_code == 200
    assert client.get(f"/chat/goal/{gid}", headers=_as("mallory")).status_code == 404


def test_chat_send_stamps_owner(world, monkeypatch, no_run):
    _enable_oidc_principal_map(monkeypatch)
    resp = client.post(
        "/chat/send",
        data={"title": "via chat"},
        headers={**_as("alice"), **_origin()},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    g = world.list_goals(owner="user:alice")
    assert len(g) == 1 and g[0].title == "via chat"


# ----------------------------------- fleets -----------------------------------


def _patch_fleets(monkeypatch):
    from maverick.fleet import Fleet

    fleets = [
        Fleet(name="alice-fleet", owner="user:alice"),
        Fleet(name="bob-fleet", owner="user:bob"),
    ]
    import maverick.fleet as fleet_mod

    monkeypatch.setattr(fleet_mod, "list_fleets", lambda *a, **k: list(fleets))


def test_fleets_api_scoped_to_caller(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    _patch_fleets(monkeypatch)
    names = {f["name"] for f in client.get("/api/v1/fleets", headers=_as("alice")).json()["fleets"]}
    assert names == {"alice-fleet"}


def test_fleets_api_admin_sees_all(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:root")
    _patch_fleets(monkeypatch)
    names = {f["name"] for f in client.get("/api/v1/fleets", headers=_as("root")).json()["fleets"]}
    assert names == {"alice-fleet", "bob-fleet"}


def test_fleets_api_auth_off_sees_all(world, monkeypatch):
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    _patch_fleets(monkeypatch)
    names = {f["name"] for f in client.get("/api/v1/fleets").json()["fleets"]}
    assert names == {"alice-fleet", "bob-fleet"}


def test_fleets_page_filters_to_caller(world, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    _patch_fleets(monkeypatch)
    body = client.get("/fleets", headers=_as("alice")).text
    assert "alice-fleet" in body
    assert "bob-fleet" not in body
