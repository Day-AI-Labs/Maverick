"""Design-system rollout: a consistent .page-title across pages that drifted to
a bare <h2>, plus the shared .section-head component."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)


def test_pages_use_shared_page_title(monkeypatch, tmp_path):
    # agents/roles/skills used a bare lowercase <h2>; now the shared <h1>.
    _isolate(monkeypatch, tmp_path)
    c = _client()
    for path, label in [("/agents", "Agents"), ("/roles", "Roles"), ("/skills", "Skills"),
                        ("/plugins", "Plugins"), ("/safety", "Safety"), ("/compliance", "Compliance")]:
        t = c.get(path).text
        assert '<h1 class="page-title">' + label in t, path


def test_generic_empties_use_mv_empty(monkeypatch, tmp_path):
    # Generic full-page empties converged onto the single .mv-empty component.
    _isolate(monkeypatch, tmp_path)
    c = _client()
    for path in ["/benchmarks", "/compartments", "/store"]:
        assert "mv-empty" in c.get(path).text, path


def test_automations_uses_shared_section_head(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    t = _client().get("/automations").text
    assert 'class="section-head"' in t and "auto__section-head" not in t
