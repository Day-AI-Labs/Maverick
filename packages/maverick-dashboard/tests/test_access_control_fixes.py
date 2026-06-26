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

# --- workforce operating metrics must be owner-scoped ------------------------

class _Goal:
    def __init__(self, gid, owner, domain, status="done"):
        self.id = gid
        self.owner = owner
        self.domain = domain
        self.status = status
        self.title = f"{owner} {domain}"
        self.updated_at = float(gid)


class _Spend:
    def __init__(self, goal_id, cost):
        self.goal_id = goal_id
        self.cost_dollars = cost


class _Approval:
    def __init__(self, requested_by, decided_by=None):
        self.requested_by = requested_by
        self.decided_by = decided_by
        self.claimed_by = None
        self.requested_at = 10.0
        self.decided_at = 11.0 if decided_by else None
        self.action = "approve secret spend"
        self.status = "approved" if decided_by else "pending"
        self.provenance = None


class _WorkforceWorld:
    goals = [
        _Goal(1, "user:alice", "finance_ar"),
        _Goal(2, "user:bob", "finance_ap"),
    ]
    episodes = [
        ("user:alice", _Spend(1, 12.34)),
        ("user:bob", _Spend(2, 99.99)),
    ]
    approvals = [
        _Approval("user:alice", "user:alice"),
        _Approval("user:bob", "user:bob"),
    ]

    def list_goals(self, limit=500, order="desc", owner=None):
        rows = [g for g in self.goals if owner is None or g.owner == owner]
        return rows[:limit]

    def list_episodes(self, limit=500, goal_id=None, owner=None):
        rows = [e for e_owner, e in self.episodes if owner is None or e_owner == owner]
        if goal_id is not None:
            rows = [e for e in rows if e.goal_id == goal_id]
        return rows[:limit]

    def list_approvals(self, limit=500):
        return self.approvals[:limit]


def test_workforce_outcomes_api_scoped_to_owner(monkeypatch):
    monkeypatch.setattr(api_mod, "_world", lambda: _WorkforceWorld())
    monkeypatch.setattr(api_mod, "goal_owner_filter", lambda request: "user:alice")

    data = client.get("/api/v1/outcomes").json()

    assert data["firm"] == {
        "goals_total": 1,
        "goals_completed": 1,
        "approvals": 1,
        "human_decisions": 1,
        "spend_dollars": 12.34,
    }
    assert {w["worker"] for w in data["workers"]} == {"finance_ar"}


def test_department_review_api_scoped_to_owner(monkeypatch):
    monkeypatch.setattr(api_mod, "_world", lambda: _WorkforceWorld())
    monkeypatch.setattr(api_mod, "goal_owner_filter", lambda request: "user:alice")

    data = client.get("/api/v1/departments/finance/review").json()

    assert data["delivery"]["goals_total"] == 1
    assert data["delivery"]["spend_dollars"] == 12.34
    assert {w["worker"] for w in data["delivery"]["workers"]} == {"finance_ar"}


def test_workforce_page_rollup_scoped_to_owner(monkeypatch):
    monkeypatch.setattr(app_mod, "_world", lambda: _WorkforceWorld())
    monkeypatch.setattr(app_mod, "goal_owner_filter", lambda request: "user:alice")

    body = client.get("/workforce").text

    assert "$12.34" in body
    assert "$112.33" not in body
    assert "finance_ar" in body
    assert "finance_ap" not in body
