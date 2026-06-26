"""/healthz + /metrics probe the CONFIGURED world backend, not a hard-coded
local world.db -- so a Postgres-backed (HA) deployment reports the DB it
actually uses, and the goal-count gauge reflects the real store.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


def _use_sqlite(monkeypatch, tmp_path):
    """Point the dashboard's _world() at an isolated SQLite world."""
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    return world_model.WorldModel(db)


def test_metrics_goal_counts_from_configured_backend(monkeypatch, tmp_path):
    wm = _use_sqlite(monkeypatch, tmp_path)
    g1 = wm.create_goal("a")
    wm.set_goal_status(g1, "done")
    wm.create_goal("b")  # stays pending

    text = client.get("/metrics").text
    assert 'maverick_goals_total{status="done"} 1' in text
    assert 'maverick_goals_total{status="pending"} 1' in text


def test_healthz_db_ok_via_ping(monkeypatch, tmp_path):
    _use_sqlite(monkeypatch, tmp_path)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    body = client.get("/healthz").json()
    # No token -> full checks block; the db check uses the backend ping.
    assert body["checks"]["db"] == "ok"


def test_healthz_db_fail_is_reported(monkeypatch, tmp_path):
    _use_sqlite(monkeypatch, tmp_path)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)

    class _Broken:
        def ping(self):
            raise RuntimeError("db down")

    from maverick_dashboard import app as dash_app
    monkeypatch.setattr(dash_app, "_world", lambda: _Broken())
    resp = client.get("/healthz")
    body = resp.json()
    assert resp.status_code == 503
    assert body["checks"]["db"].startswith("fail")


def test_metrics_omits_world_db_bytes_under_postgres(monkeypatch, tmp_path):
    _use_sqlite(monkeypatch, tmp_path)
    # Simulate a Postgres deployment: the SQLite-file size gauge is meaningless,
    # so it must be omitted while the disk-free gauge stays.
    from maverick import world_model_backends
    monkeypatch.setattr(world_model_backends, "is_postgres_configured", lambda: True)
    text = client.get("/metrics").text
    assert "maverick_world_db_bytes" not in text
    assert "# TYPE maverick_data_disk_free_bytes gauge" in text
