"""Interactive plan-tree visualization: Cytoscape container + live poll.

The plan-tree page swaps the static <ul> for a JS-driven Cytoscape graph
that fetches /api/v1/goals/{id}/tree and polls it. These tests lock in:
  - the interactive container (#plan-tree) + the SRI-pinned CDN script,
  - the existing tree JSON API still works unchanged,
  - the CSP on the plan page allows the CDN host (and only that page),
  - the no-JS <noscript> fallback still renders.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def world_with_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    w = world_model.WorldModel(tmp_path / "world.db")
    g1 = w.create_goal("root task", "high-level")
    g2 = w.create_goal("subtask A", "child of 1", parent_id=g1)
    g3 = w.create_goal("subtask B", "child of 1", parent_id=g1)
    w.conn.commit()
    yield w, g1, g2, g3
    w.close()


@pytest.fixture
def client(world_with_tree, monkeypatch):
    from maverick_dashboard import app as app_mod
    w, *_ = world_with_tree
    monkeypatch.setattr(app_mod, "_world", lambda: w)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    return TestClient(app_mod.app)


def test_plan_page_renders_interactive_container_and_script(client, world_with_tree):
    _, g1, *_ = world_with_tree
    resp = client.get(f"/goals/{g1}/plan")
    assert resp.status_code == 200
    body = resp.text
    # The interactive graph mount point.
    assert 'id="plan-tree"' in body
    # Cytoscape vendored from the CDN, SRI-pinned + crossorigin.
    assert "cdn.jsdelivr.net/npm/cytoscape" in body
    assert "integrity=" in body and "sha384-" in body
    assert 'crossorigin="anonymous"' in body
    # It fetches the live tree endpoint and polls.
    assert "/api/v1/goals/" in body
    # Still says it updates live (no more "Refresh to see live state").
    assert "live" in body.lower()
    assert "Refresh to see live state" not in body


def test_plan_page_keeps_noscript_fallback(client, world_with_tree):
    _, g1, *_ = world_with_tree
    body = client.get(f"/goals/{g1}/plan").text
    assert "<noscript>" in body
    # The root goal id appears in the fallback markup.
    assert f"#{g1}" in body


def test_tree_api_still_returns_json(client, world_with_tree):
    _, g1, g2, g3 = world_with_tree
    resp = client.get(f"/api/v1/goals/{g1}/tree")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == g1
    child_ids = sorted(c["id"] for c in data["children"])
    assert child_ids == sorted([g2, g3])


def test_plan_page_csp_allows_cdn_only_there(client, world_with_tree):
    _, g1, *_ = world_with_tree
    plan_csp = client.get(f"/goals/{g1}/plan").headers.get("Content-Security-Policy", "")
    # The plan page allows the Cytoscape CDN on script-src...
    assert "https://cdn.jsdelivr.net" in plan_csp
    # ...but connect-src stays self-only (the poll hits our own API).
    assert "connect-src 'self'" in plan_csp
    assert "object-src 'none'" in plan_csp
    # Other dashboard pages remain locked to 'self' (no CDN host).
    home_csp = client.get("/goals").headers.get("Content-Security-Policy", "")
    assert "cdn.jsdelivr.net" not in home_csp


def test_tree_api_unknown_goal_404(client):
    assert client.get("/api/v1/goals/99999/tree").status_code == 404
