"""The /automations control page: one place to see/manage schedules + triggers.

The page is client-rendered (it fetches the existing /api/v1/schedules and
/api/v1/triggers); these tests cover the route, the feature gating of each
section, and the nav entry. The endpoints themselves are covered by
test_schedules.py / test_triggers.py.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)


def test_page_renders_both_sections(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/automations")
    assert r.status_code == 200
    assert "Automations" in r.text
    assert 'id="auto-sched-list"' in r.text and "/api/v1/schedules" in r.text
    assert 'id="auto-trig-list"' in r.text and "/api/v1/triggers" in r.text


def test_sections_hidden_when_features_off(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(
        config, "get_features",
        lambda: {**real(), "scheduling": False, "triggers": False})
    r = _client().get("/automations")
    assert r.status_code == 200
    assert 'id="auto-sched-list"' not in r.text
    assert 'id="auto-trig-list"' not in r.text
    assert "Automations are disabled" in r.text


def test_one_section_when_only_scheduling_on(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(
        config, "get_features", lambda: {**real(), "triggers": False})
    r = _client().get("/automations")
    assert 'id="auto-sched-list"' in r.text          # scheduling stays
    assert 'id="auto-trig-list"' not in r.text         # triggers hidden
    assert "Automations are disabled" not in r.text


def test_nav_has_automations_link(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # The primary nav renders on every page, so the page links to itself.
    assert 'href="/automations"' in _client().get("/automations").text
