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


def test_automation_runs_validates_input(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    c = _client()
    # an unknown kind is a 400
    assert c.get("/api/v1/automation-runs",
                 params={"kind": "bogus", "ref": "x"}).status_code == 400
    # an empty ref is an empty result, not an error (and touches no DB)
    r = c.get("/api/v1/automation-runs", params={"kind": "schedule", "ref": ""})
    assert r.status_code == 200
    assert r.json() == {"runs": [], "summary": {}}


def test_page_includes_run_history_loader(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # the page wires the provenance endpoint for per-automation run history
    assert "/api/v1/automation-runs" in _client().get("/automations").text


def test_run_history_links_drill_into_trajectory(monkeypatch, tmp_path):
    # Run-history entries link to each goal's trajectory ("what it did").
    _isolate(monkeypatch, tmp_path)
    assert "/trajectory" in _client().get("/automations").text


def test_templates_page_shows_automate_cta(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick_dashboard.app as appmod
    monkeypatch.setattr(appmod, "template_market_entries",
                        lambda: [{"name": "weekly-report", "title": "T", "body": "b", "params": []}])
    r = _client().get("/templates")
    assert r.status_code == 200
    assert "/workflow-builder?template=weekly-report" in r.text


def test_templates_automate_cta_hidden_when_automation_off(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick_dashboard.app as appmod
    monkeypatch.setattr(appmod, "template_market_entries",
                        lambda: [{"name": "x", "title": "T", "body": "b", "params": []}])
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(config, "get_features",
                        lambda: {**real(), "scheduling": False, "triggers": False})
    assert "/workflow-builder?template=" not in _client().get("/templates").text


def test_base_provides_shared_confirm_and_toast(monkeypatch, tmp_path):
    # The reusable feedback primitives ship from base.html on every page.
    _isolate(monkeypatch, tmp_path)
    t = _client().get("/automations").text
    assert 'id="mv-confirm"' in t and 'id="mv-toasts"' in t
    assert "window.mvConfirm" in t and "window.mvToast" in t


def test_nav_has_automations_link(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # The primary nav renders on every page, so the page links to itself.
    assert 'href="/automations"' in _client().get("/automations").text
