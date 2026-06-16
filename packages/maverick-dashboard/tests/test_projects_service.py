"""Projects pages: list + create, detail (member goals), and filing a goal under
a project from the goal page."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


def _world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    return world_model.WorldModel(tmp_path / "world.db")


def test_projects_page_lists(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    pid = w.create_project("Q3 Close", domain="finance_sox")
    w.create_goal("Reconcile", "", project_id=pid)
    t = client.get("/projects").text
    assert "Q3 Close" in t and "finance_sox" in t
    assert "New project" in t  # create form present


def test_create_project_redirects_to_detail(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    r = client.post("/projects", data={"name": "Audit FY26", "domain": "assurance"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/projects/")


def test_create_project_requires_name(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    r = client.post("/projects", data={"name": "   "}, follow_redirects=False)
    assert r.status_code == 422


def test_project_detail_shows_member_goals(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    pid = w.create_project("Close", domain="finance_sox")
    w.create_goal("Reconcile AP", "", project_id=pid)
    w.create_goal("Unrelated", "")  # not in project
    t = client.get(f"/projects/{pid}").text
    assert "Reconcile AP" in t and "Unrelated" not in t
    assert "Goals in this project" in t


def test_project_detail_404(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    assert client.get("/projects/9999").status_code == 404


def test_file_goal_under_project_from_goal_page(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    pid = w.create_project("Close")
    gid = w.create_goal("Reconcile", "")
    # goal page offers the project selector
    assert "goal-project-sel" in client.get(f"/chat/goal/{gid}").text
    # file it
    r = client.post(f"/chat/goal/{gid}/project", data={"project_id": str(pid)},
                    follow_redirects=False)
    assert r.status_code == 303
    assert w.get_goal(gid).project_id == pid
    # clear it (empty value)
    client.post(f"/chat/goal/{gid}/project", data={"project_id": ""}, follow_redirects=False)
    assert w.get_goal(gid).project_id is None
