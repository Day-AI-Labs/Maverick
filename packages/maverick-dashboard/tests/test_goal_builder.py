"""Drag-and-drop goal builder: page + POST /api/v1/goals/compose.

Compose assembles blocks into a markdown brief (steps as a checklist,
budget/channel/priority folded in — the goals table has no metadata
columns) and starts the run with the budget block as the real dollar cap.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    w = world_model.WorldModel(tmp_path / "world.db")
    yield w
    w.close()


@pytest.fixture
def client(world, monkeypatch):
    from maverick_dashboard import api as api_mod
    from maverick_dashboard import app as app_mod
    monkeypatch.setattr(app_mod, "_world", lambda: world)
    monkeypatch.setattr(api_mod, "_world", lambda: world)
    return TestClient(app_mod.app, headers={"Origin": "http://testserver"})


@pytest.fixture
def runner_stub(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    import maverick.runner as runner_mod
    calls = []

    def fake_run(goal_id, max_dollars=None, *a, **kw):
        calls.append((goal_id, max_dollars))

    monkeypatch.setattr(runner_mod, "run_goal_in_thread", fake_run)
    return calls


def test_builder_page_renders_palette_and_labels(client):
    r = client.get("/goal-builder")
    assert r.status_code == 200
    assert 'for="gb-title"' in r.text                 # labeled title input
    for kind in ("step", "budget", "channel", "priority"):
        assert f'data-kind="{kind}"' in r.text
    assert 'draggable="true"' in r.text               # HTML5 DnD palette
    assert "/api/v1/goals/compose" in r.text


def test_compose_assembles_brief_and_runs_with_budget(client, world, runner_stub):
    r = client.post("/api/v1/goals/compose", json={
        "title": "Ship the report",
        "steps": ["gather data", "draft it", "send for review"],
        "budget_dollars": 1.5,
        "channel": "slack #general",
        "priority": "high",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    g = world.get_goal(body["id"])
    # steps -> markdown checklist
    assert "- [ ] gather data" in g.description
    assert "- [ ] draft it" in g.description
    assert "- [ ] send for review" in g.description
    # metadata folded into the brief (no metadata columns on goals)
    assert "Budget cap: $1.50" in g.description
    assert "Announce progress on: slack #general" in g.description
    assert "Priority: high" in g.description
    # the budget block is the run's real dollar cap
    assert runner_stub == [(body["id"], 1.5)]


def test_compose_budget_clamped_to_server_cap(client, world, runner_stub):
    from maverick.runner import DEFAULT_MAX_DOLLARS
    r = client.post("/api/v1/goals/compose", json={
        "title": "big spender", "budget_dollars": 99.0,
    })
    assert r.status_code == 201
    # the brief records the requested cap; the runner gets the clamped one
    assert runner_stub[0][1] == DEFAULT_MAX_DOLLARS


def test_compose_without_blocks_uses_title_as_brief(client, world, runner_stub):
    r = client.post("/api/v1/goals/compose", json={"title": "just do it"})
    assert r.status_code == 201
    g = world.get_goal(r.json()["id"])
    assert g.description == "just do it"
    # no budget block -> the server default cap applies
    from maverick.runner import DEFAULT_MAX_DOLLARS
    assert runner_stub[0][1] == DEFAULT_MAX_DOLLARS


def test_compose_drops_blank_steps(client, world, runner_stub):
    r = client.post("/api/v1/goals/compose", json={
        "title": "t", "steps": ["  ", "real step", ""],
    })
    assert r.status_code == 201
    g = world.get_goal(r.json()["id"])
    assert g.description.count("- [ ]") == 1


def test_compose_validation(client, runner_stub):
    assert client.post("/api/v1/goals/compose",
                       json={"title": "  "}).status_code == 400
    r = client.post("/api/v1/goals/compose",
                    json={"title": "t", "priority": "urgent!!"})
    assert r.status_code == 400
    assert "priority" in r.json()["detail"]
    r = client.post("/api/v1/goals/compose",
                    json={"title": "t", "steps": ["s"] * 51})
    assert r.status_code == 400
    assert "steps" in r.json()["detail"]
    # pydantic bounds on the budget
    assert client.post("/api/v1/goals/compose",
                       json={"title": "t", "budget_dollars": 10_000}).status_code == 422
    assert runner_stub == []  # nothing invalid ever reached the runner


def test_compose_requires_provider_key(client, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
                "XAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    r = client.post("/api/v1/goals/compose", json={"title": "t"})
    assert r.status_code == 400
    assert "provider key" in r.json()["detail"]
