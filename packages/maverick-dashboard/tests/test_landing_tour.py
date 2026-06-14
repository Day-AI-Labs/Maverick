"""Landing-page tour: the three entry points + dismiss persistence."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _client(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    return TestClient(dash_app.app)


def test_landing_tour_shows_three_entry_points(monkeypatch, tmp_path):
    body = _client(monkeypatch, tmp_path).get("/overview").text
    # 1) web UI, 2) REST API, 3) CLI.
    assert "/chat" in body
    assert "POST /api/v1/goals" in body
    assert "maverick start" in body
    # The curl one-liner shape is shown for the API path.
    assert "curl -X POST" in body


def test_landing_tour_is_dismissible_and_persists(monkeypatch, tmp_path):
    body = _client(monkeypatch, tmp_path).get("/overview").text
    assert 'id="tour-dismiss"' in body
    assert 'aria-label="Dismiss tour"' in body
    # Dismissal persists via localStorage under this key.
    assert "maverick_tour_dismissed" in body
