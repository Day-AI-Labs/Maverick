"""UI hardening round 10: keyboard-scrollable regions + truncation tooltips."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _prep(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()


def test_goal_log_and_result_are_keyboard_scrollable(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from maverick import world_model
    gid = world_model.WorldModel(tmp_path / "world.db").create_goal("g", "d")
    r = _client().get(f"/chat/goal/{gid}")
    assert r.status_code == 200
    assert ('id="events" role="log" aria-live="polite" '
            'aria-label="Goal progress" tabindex="0"') in r.text
    assert 'id="result" tabindex="0" aria-label="Goal result"' in r.text


def test_audit_results_region_is_focusable_and_named(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(
        "maverick.audit.writer.DEFAULT_AUDIT_DIR", tmp_path / "audit",
    )
    import maverick.audit.writer as aw
    aw._default = None
    r = _client().get("/audit")
    assert 'id="audit-search-results" tabindex="0" aria-label="Search results"' in r.text


def test_focus_ring_covers_focusable_regions(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().get("/")
    assert '[tabindex="0"]:focus-visible' in r.text


def test_long_goal_description_has_tooltip(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    from maverick import world_model
    long_desc = "x" * 200
    world_model.WorldModel(tmp_path / "world.db").create_goal("g", long_desc)
    r = _client().get("/goals")
    assert r.status_code == 200
    assert 'title="' + long_desc + '"' in r.text
