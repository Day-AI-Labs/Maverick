"""Dashboard landing tour (#433): a dismissible getting-started panel that
points first-time users at the three entry points (chat / REST API / CLI).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.world_model import WorldModel
    from maverick_dashboard import app as app_mod
    w = WorldModel(tmp_path / "world.db")
    monkeypatch.setattr(app_mod, "_world", lambda: w)
    yield TestClient(app_mod.app)
    w.close()


def test_index_renders_tour(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="tour"' in body
    assert "Three ways to run a goal" in body


def test_tour_lists_all_three_entry_points(client):
    body = client.get("/").text
    # Chat, REST API, and CLI must each be surfaced.
    assert "/chat" in body
    assert "/api/v1/goals" in body
    assert 'maverick start' in body or "maverick onboard" in body


def test_tour_is_dismissible(client):
    body = client.get("/").text
    assert 'id="tour-dismiss"' in body
    # The dismiss state is persisted client-side; the script references the
    # localStorage key so a closed tour stays closed.
    assert "maverick.tourDismissed" in body


def test_index_csp_allows_inline_script(client):
    # The tour's dismiss logic is an inline <script>; the default CSP must
    # permit it (script-src 'self' 'unsafe-inline'), or the tour is dead.
    resp = client.get("/")
    csp = resp.headers.get("content-security-policy", "")
    assert "script-src" in csp
    assert "'unsafe-inline'" in csp


def test_tour_present_on_populated_dashboard(client, tmp_path, monkeypatch):
    # Even when there are goals (not the empty state), the tour still shows
    # so returning-but-new users can find their bearings until they dismiss.
    from maverick_dashboard import app as app_mod
    w = app_mod._world()
    w.create_goal("an existing goal", "desc")
    body = client.get("/").text
    assert 'id="tour"' in body
    assert "recent goals" in body  # populated view rendered
