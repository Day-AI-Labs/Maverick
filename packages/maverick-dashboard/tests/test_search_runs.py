"""Dashboard /api/v1/goals/search endpoint (search across runs)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    from maverick_dashboard import app as app_mod
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    app_mod._world_cache.clear()
    w = world_model.WorldModel(tmp_path / "world.db")
    w.create_goal("Deploy the billing service", "prod rollout")
    w.create_goal("Write quarterly report", "finance summary")
    yield


def test_search_returns_matching_runs():
    resp = client.get("/api/v1/goals/search", params={"q": "billing"})
    assert resp.status_code == 200
    titles = [g["title"].lower() for g in resp.json()]
    assert any("billing" in t for t in titles)
    assert all("report" not in t for t in titles)


def test_search_empty_query_returns_empty():
    resp = client.get("/api/v1/goals/search", params={"q": "   "})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_path_not_shadowed_by_goal_id():
    # /goals/search must not be parsed as /goals/{goal_id}
    resp = client.get("/api/v1/goals/search", params={"q": "report"})
    assert resp.status_code == 200
    assert any("report" in g["title"].lower() for g in resp.json())


def test_goals_page_renders_search_box():
    resp = client.get("/goals")
    assert resp.status_code == 200
    assert 'id="run-search-q"' in resp.text
    assert "/api/v1/goals/search?q=" in resp.text
