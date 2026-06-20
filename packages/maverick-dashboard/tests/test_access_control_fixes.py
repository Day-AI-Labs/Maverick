"""Regression tests for the broken-access-control audit fixes (Batch B).

Each test pins a cross-tenant / privilege gap that previously let an
authenticated non-admin read or act on data they don't own.
"""
from __future__ import annotations

import sqlite3
import types

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard import api as api_mod
from maverick_dashboard import app as app_mod
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    app_mod._world_cache.clear()
    yield


def _as(monkeypatch, principal):
    """Simulate an authenticated caller with a given principal."""
    from maverick_dashboard import auth
    monkeypatch.setattr(auth, "caller_principal", lambda request: principal)


# --- #3 approval claim/release require the 'operate' permission ---------------

def test_viewer_cannot_claim_or_release_approval(monkeypatch):
    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "")
    from maverick_dashboard import rbac
    rbac.set_role("user:v", "viewer")
    aid = app_mod._world().create_approval(
        "wire_transfer", risk="high", scope="acct", detail="$5k")
    _as(monkeypatch, "user:v")
    assert client.post(f"/api/v1/approvals/{aid}/claim").status_code == 403
    assert client.post(f"/api/v1/approvals/{aid}/release").status_code == 403
    # And the claim never took effect.
    assert app_mod._world().get_approval(aid).claimed_by is None


# --- #1 GET /api/v1/cost.csv owner scoping -----------------------------------

def _seeded_world():
    """A minimal world whose .conn is a real sqlite with two owners' episodes."""
    # check_same_thread=False: the StreamingResponse generator runs on a worker
    # thread under TestClient, so the test fixture's connection must be shareable.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE goals (id INTEGER PRIMARY KEY, owner TEXT)")
    conn.execute(
        "CREATE TABLE episodes (id INTEGER PRIMARY KEY, goal_id INT, started_at REAL,"
        " ended_at REAL, outcome TEXT, cost_dollars REAL, input_tokens INT,"
        " output_tokens INT, tool_calls INT)"
    )
    conn.executemany("INSERT INTO goals VALUES (?,?)",
                     [(1, "user:alice"), (2, "user:bob")])
    conn.executemany(
        "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?)",
        [(10, 1, 100.0, 200.0, "alice-outcome", 1.5, 10, 5, 2),
         (20, 2, 100.0, 200.0, "bob-secret", 9.9, 1, 1, 1)],
    )
    conn.commit()
    return types.SimpleNamespace(conn=conn)


def test_cost_csv_scoped_to_owner(monkeypatch):
    monkeypatch.setattr(app_mod, "_world", lambda: _seeded_world())
    monkeypatch.setattr(app_mod, "goal_owner_filter", lambda request: "user:alice")
    body = client.get("/api/v1/cost.csv").text
    assert "alice-outcome" in body
    assert "bob-secret" not in body  # the other tenant's episode is withheld


def test_cost_csv_admin_or_authoff_sees_all(monkeypatch):
    monkeypatch.setattr(app_mod, "_world", lambda: _seeded_world())
    monkeypatch.setattr(app_mod, "goal_owner_filter", lambda request: None)
    body = client.get("/api/v1/cost.csv").text
    assert "alice-outcome" in body and "bob-secret" in body


# --- #2 GET /api/v1/cost/anomalies owner scoping -----------------------------

class _Ep:
    def __init__(self, goal_id, cost):
        self.goal_id = goal_id
        self.cost_dollars = cost


def test_cost_anomalies_scoped_to_owner(monkeypatch):
    class _W:
        def list_goals(self, owner=None, limit=None, order="asc"):
            assert owner == "user:alice"
            return [types.SimpleNamespace(id=i) for i in (1, 2, 3)]

        def list_episodes(self, limit=500):
            # alice owns 1,2,3 (3 is the outlier); bob's goal 9 is a huge outlier.
            return [_Ep(1, 1.0), _Ep(2, 1.0), _Ep(3, 50.0), _Ep(9, 9999.0)]

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    monkeypatch.setattr(app_mod, "goal_owner_filter", lambda request: "user:alice")
    data = client.get("/api/v1/cost/anomalies").json()
    assert data["goals_considered"] == 3  # only alice's goals were considered
    assert 9 not in {a["goal_id"] for a in data["anomalies"]}  # bob's never leaks


# --- #4 GET /api/v1/automation-runs owner scoping (IDOR) ----------------------

def test_automation_runs_scoped_to_owner(monkeypatch):
    g_alice = types.SimpleNamespace(id=1, title="alice run", status="done",
                                    created_at=1, owner="user:alice")
    g_bob = types.SimpleNamespace(id=2, title="bob run", status="failed",
                                  created_at=2, owner="user:bob")

    class _W:
        def goals_for_origin(self, kind, ref, *, limit=20):
            return [g_alice, g_bob]

    monkeypatch.setattr(api_mod, "_world", lambda: _W())
    monkeypatch.setattr(api_mod, "goal_owner_filter", lambda request: "user:alice")
    monkeypatch.setattr(api_mod, "can_access_goal",
                        lambda request, g: g.owner == "user:alice")

    data = client.get("/api/v1/automation-runs?kind=trigger&ref=nightly").json()
    titles = {r["title"] for r in data["runs"]}
    assert titles == {"alice run"}        # bob's run title does not leak
    assert data["summary"] == {"done": 1}  # summary recomputed from owned goals only


# --- #7 runs/compare must not leak a goal-existence oracle -------------------

def test_runs_compare_missing_goal_has_no_id_oracle(monkeypatch):
    class _W:
        def get_goal(self, gid):
            return None  # nonexistent

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    r = client.get("/api/v1/runs/compare?ids=4242")
    assert r.status_code == 404
    # The detail must NOT echo the id (else it distinguishes "missing" from
    # "exists-but-forbidden", which assert_goal_access deliberately hides).
    assert r.json()["detail"] == "no such goal"
    assert "4242" not in r.json()["detail"]
