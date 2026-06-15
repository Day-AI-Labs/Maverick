"""The /workflows index: your saved templates + agent playbooks, with quick
edit / automate actions and a 'New workflow' button. Closes Maya's "the
Workflows nav opens a blank builder" finding by making it a real list.
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
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")


def test_index_lists_user_templates_and_playbooks(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    tdir = tmp_path / ".maverick" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "weekly-report.md").write_text(
        "---\ntitle: Weekly report\nparams:\n  - topic\n---\nbody\n", encoding="utf-8")
    import maverick.domain_edit as de
    monkeypatch.setattr(de, "list_agents", lambda: [
        {"name": "invoice-clerk", "suite": "finance", "description": "pays invoices",
         "is_override": True, "has_workflow": True},
        {"name": "vanilla", "suite": "x", "description": "",
         "is_override": False, "has_workflow": True},   # not overridden -> excluded
    ])
    t = _client().get("/workflows").text
    # user template listed with edit + automate deep-links
    assert "Weekly report" in t and "/workflow-builder?edit=weekly-report" in t
    assert "/workflow-builder?template=weekly-report" in t
    # only the overridden playbook with a workflow is "yours"
    assert "invoice-clerk" in t and "/workflow-builder?edit_agent=invoice-clerk" in t
    assert "vanilla" not in t
    assert "New workflow" in t and "Agent playbooks" in t


def test_index_empty_states(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.domain_edit as de
    monkeypatch.setattr(de, "list_agents", lambda: [])
    t = _client().get("/workflows").text
    assert "No saved templates yet" in t and "No agent playbooks yet" in t


def test_nav_workflows_points_to_index(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.domain_edit as de
    monkeypatch.setattr(de, "list_agents", lambda: [])
    t = _client().get("/workflows").text
    # the nav "Workflows" entry now links to the index (was the blank builder)
    assert '<span class="nav-label">Workflows</span>' in t
    assert 'href="/workflows"' in t
