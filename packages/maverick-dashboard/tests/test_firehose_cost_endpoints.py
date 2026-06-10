"""Run-events firehose (WS), inline cost preview, cost breakdown, anomalies."""
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
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    yield


def _goal(title="t", description="d"):
    return app_mod._world().create_goal(title, description, owner="")


def test_firehose_streams_until_terminal():
    gid = _goal()
    w = app_mod._world()
    w.append_event(gid, "coder", "plan", "step one")
    w.set_goal_status(gid, "done", result="ok")
    with client.websocket_connect(f"/ws/v1/runs/{gid}/events") as ws:
        first = ws.receive_json()
        assert first["kind"] == "plan" and first["content"] == "step one"
        final = ws.receive_json()
        assert final["kind"] == "status" and final["content"] == "done"


def test_firehose_resume_since_id():
    gid = _goal()
    w = app_mod._world()
    e1 = w.append_event(gid, "a", "k", "one")
    w.append_event(gid, "a", "k", "two")
    w.set_goal_status(gid, "done", result="ok")
    with client.websocket_connect(f"/ws/v1/runs/{gid}/events?since_id={e1}") as ws:
        msg = ws.receive_json()
        assert msg["content"] == "two"


def test_firehose_unknown_goal():
    with client.websocket_connect("/ws/v1/runs/99999/events") as ws:
        assert ws.receive_json() == {"error": "no such goal"}


def test_firehose_token_mode_requires_bearer(monkeypatch):
    monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "tok")
    gid = _goal()
    from starlette.testclient import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/v1/runs/{gid}/events"):
            pass
    auth_client = TestClient(app, headers={"Authorization": "Bearer tok"})
    w = app_mod._world()
    w.set_goal_status(gid, "done", result="ok")
    with auth_client.websocket_connect(f"/ws/v1/runs/{gid}/events") as ws:
        assert ws.receive_json()["kind"] == "status"


def test_cost_preview_projects_and_verdicts():
    gid = _goal(description="research the market\nwrite the report")
    r = client.get(f"/api/v1/goals/{gid}/cost-preview")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["steps"] == 2
    assert data["total_dollars"] > 0
    assert data["verdict"] in ("OK", "TIGHT", "OVER")
    r2 = client.get(f"/api/v1/goals/{gid}/cost-preview?iterations=3")
    assert r2.json()["total_dollars"] > data["total_dollars"]


class _Ep:
    def __init__(self, goal_id, cost, outcome="success", it=100, ot=50):
        self.goal_id = goal_id
        self.cost_dollars = cost
        self.outcome = outcome
        self.input_tokens = it
        self.output_tokens = ot


def test_cost_breakdown(monkeypatch):
    gid = _goal()
    real_goal = app_mod._world().get_goal(gid)

    class _W:
        def get_goal(self, g):
            return real_goal if g == gid else None

        def list_episodes(self, limit=500, goal_id=None):
            return [_Ep(gid, 0.5), _Ep(gid, 0.2, outcome="error")]

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    r = client.get(f"/api/v1/goals/{gid}/cost-breakdown")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_dollars"] == 0.7
    buckets = {b["bucket"]: b for b in data["buckets"]}
    assert buckets["success"]["dollars"] == 0.5
    assert buckets["error"]["episodes"] == 1
    # Sorted by spend: success first.
    assert data["buckets"][0]["bucket"] == "success"


def test_cost_anomalies(monkeypatch):
    class _W:
        def list_episodes(self, limit=500):
            eps = [_Ep(i, 0.10) for i in range(1, 9)]
            eps.append(_Ep(99, 25.0))  # the outlier
            return eps

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    r = client.get("/api/v1/cost/anomalies?threshold_sigma=2")
    assert r.status_code == 200
    data = r.json()
    assert [a["goal_id"] for a in data["anomalies"]] == [99]
    assert data["goals_considered"] == 9


def test_cost_anomalies_needs_baseline(monkeypatch):
    class _W:
        def list_episodes(self, limit=500):
            return [_Ep(1, 1.0)]

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    data = client.get("/api/v1/cost/anomalies").json()
    assert data["anomalies"] == [] and "baseline" in data["note"]


def test_tutorial_endpoint():
    gid = _goal("Build the widget", "from scratch")
    w = app_mod._world()
    w.append_event(gid, "planner", "plan", "1. design 2. build")
    w.append_event(gid, "coder", "finding", "the API needs auth")
    r = client.get(f"/api/v1/goals/{gid}/tutorial.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "# Tutorial: Build the widget" in r.text
    assert "the API needs auth" in r.text
    assert client.get("/api/v1/goals/99999/tutorial.md").status_code == 404
