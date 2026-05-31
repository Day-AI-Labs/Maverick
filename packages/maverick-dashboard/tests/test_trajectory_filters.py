"""Trajectory timeline filter controls (agent / severity)."""
from __future__ import annotations

import pytest

# Skip the module entirely if FastAPI isn't installed.
fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def world_with_events(tmp_path, monkeypatch):
    """A WorldModel with one goal carrying events of distinct kinds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    g1 = w.create_goal("root task", "high-level")
    w.append_event(g1, "orchestrator", "tool", "called shell: ls")
    w.append_event(g1, "coder", "error", "boom")
    w.append_event(g1, "coder", "thinking", "hmm")
    w.commit() if hasattr(w, "commit") else w.conn.commit()
    yield w, g1
    w.close()


@pytest.fixture
def client(world_with_events, monkeypatch):
    """Wired-up TestClient sharing the same world db as the fixture."""
    from maverick_dashboard import app as app_mod
    w, _g1 = world_with_events
    monkeypatch.setattr(app_mod, "_world", lambda: w)
    return TestClient(app_mod.app)


def test_trajectory_renders_agent_filter(client, world_with_events):
    _, g1 = world_with_events
    resp = client.get(f"/goals/{g1}/trajectory")
    assert resp.status_code == 200
    body = resp.text
    # The agent filter select element is present with its id/class.
    assert 'id="filter-agent"' in body
    assert "filter-agent" in body
    # Distinct agents from the rendered events become options.
    assert ">orchestrator<" in body
    assert ">coder<" in body


def test_trajectory_renders_severity_filter(client, world_with_events):
    _, g1 = world_with_events
    resp = client.get(f"/goals/{g1}/trajectory")
    assert resp.status_code == 200
    body = resp.text
    # The severity (event kind) filter select element is present.
    assert 'id="filter-severity"' in body
    assert "filter-severity" in body
    # Distinct kinds from the rendered events become options.
    assert ">tool<" in body
    assert ">error<" in body
    assert ">thinking<" in body


def test_trajectory_rows_carry_filter_data_attrs(client, world_with_events):
    _, g1 = world_with_events
    resp = client.get(f"/goals/{g1}/trajectory")
    body = resp.text
    # Rows expose the data-agent attribute so the inline JS can filter them.
    assert 'data-agent="orchestrator"' in body
    assert 'data-kind="error"' in body
