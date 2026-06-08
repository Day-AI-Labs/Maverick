"""Per-agent fleet run history on the operator console (/fleets).

Hermetic, like ``test_fleets_console.py``: OIDC off, HOME + MAVERICK_HOME
isolated to a tmp_path (so fleets + their run index land in the temp dir), and
the WorldModel points at a fresh DB so goal lookups resolve there.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")


def _save_fleet(name="acme", owner=""):
    from maverick.fleet import Fleet, FleetAgent, save_fleet
    fleet = Fleet(
        name=name,
        owner=owner,
        agents=(
            FleetAgent("researcher", "researcher", "digs through sources"),
            FleetAgent("coder", "coder"),
        ),
    )
    return save_fleet(fleet)


def test_recorded_run_shows_up_with_goal_title_and_status(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    from maverick.fleet import record_run
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    gid = w.create_goal("Summarize the Q3 board deck")
    w.set_goal_status(gid, "done")
    record_run("acme", "researcher", gid)

    r = _client().get("/fleets")
    assert r.status_code == 200
    text = r.text
    assert "recent runs" in text.lower()
    # The agent, goal id, title, and status all render.
    assert "researcher" in text
    assert f"#{gid}" in text
    assert "Summarize the Q3 board deck" in text
    assert "done" in text


def test_empty_state_when_no_runs(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    r = _client().get("/fleets")
    assert r.status_code == 200
    assert "No runs yet" in r.text


def test_runs_are_newest_first_and_capped(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    from maverick.fleet import record_run
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    # Record more than the per-fleet cap (12) so we exercise the trim.
    gids = []
    for i in range(15):
        gid = w.create_goal(f"task number {i}")
        record_run("acme", "coder", gid)
        gids.append(gid)

    text = _client().get("/fleets").text
    # Newest goal renders; the oldest (trimmed past the 12-cap) does not.
    # Assert on the unique goal titles -- a bare ``#<id>`` substring collides
    # with the page's CSS hex colours for tiny ids.
    assert "task number 14" in text
    assert "task number 0" not in text
    # Newest-first: the most recent goal appears before an older one.
    assert text.index("task number 14") < text.index("task number 13")


def test_missing_goal_renders_fail_soft(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _save_fleet()
    from maverick.fleet import record_run
    # A run that points at a goal id that does not exist in the world.
    record_run("acme", "coder", 999999)
    r = _client().get("/fleets")
    assert r.status_code == 200
    text = r.text
    assert "#999999" in text
    assert "missing" in text
