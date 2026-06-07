"""Dashboard smoke tests.

No network -- just verify the FastAPI app constructs, routes are
registered, and templates render with empty data.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app)


def test_livez():
    """Cheap liveness probe always 200s."""
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_returns_check_breakdown(monkeypatch):
    """Deep healthz returns a per-check map, may be 200 or 503."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "checks" in body


def test_index_renders(tmp_path, monkeypatch):
    # Point the WorldModel at a fresh tmp DB so we don't depend on
    # ~/.maverick/world.db existing on the runner.
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Maverick" in resp.text
    assert "overview" in resp.text or "goals" in resp.text


def test_goals_page_renders(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    resp = client.get("/goals")
    assert resp.status_code == 200


def test_skills_page_renders(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    resp = client.get("/skills")
    assert resp.status_code == 200


def test_compartments_page_renders(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    resp = client.get("/compartments")
    assert resp.status_code == 200
    assert "compartments" in resp.text.lower()
    # the built-in finance pack shows up as a domain in the roster
    assert "finance" in resp.text


def test_facts_page_renders(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    resp = client.get("/facts")
    assert resp.status_code == 200
