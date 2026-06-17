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


def _enable_oidc_principal_map(monkeypatch):
    """OIDC on; map ``Bearer <name>`` to principal ``user:<name>``."""
    import maverick_dashboard.auth as auth
    from maverick.oidc import VerifiedPrincipal

    monkeypatch.setattr(auth, "oidc_enabled", lambda: True)

    def _verify(token, **_kw):
        return VerifiedPrincipal(
            sub=token,
            issuer="https://issuer.example",
            audience="maverick",
            claims={"sub": token},
        )

    monkeypatch.setattr(auth, "verify_oidc_token", _verify)


def _as(user: str, *, post: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {user}"}
    if post:
        headers["Origin"] = "http://testserver"
    return headers


def test_project_detail_hides_ownerless_project_from_authenticated_user(tmp_path, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    w = _world(tmp_path, monkeypatch)
    pid = w.create_project("Legacy Admin Project", owner="")
    w.create_goal("Legacy Secret", "", owner="", project_id=pid)

    r = client.get(f"/projects/{pid}", headers=_as("alice"))

    assert r.status_code == 404
    assert "Legacy Secret" not in r.text


def test_project_detail_scopes_member_goals_to_project_owner(tmp_path, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    w = _world(tmp_path, monkeypatch)
    pid = w.create_project("Alice Project", owner="user:alice")
    w.create_goal("Alice Visible", "", owner="user:alice", project_id=pid)
    bob_goal = w.create_goal("Bob Secret", "", owner="user:bob", project_id=pid)
    w.set_goal_status(bob_goal, "done")

    r = client.get(f"/projects/{pid}", headers=_as("alice"))

    assert r.status_code == 200
    assert "Alice Visible" in r.text
    assert "Bob Secret" not in r.text
    assert ">done<" not in r.text


def test_goal_project_assignment_requires_accessible_project(tmp_path, monkeypatch):
    _enable_oidc_principal_map(monkeypatch)
    w = _world(tmp_path, monkeypatch)
    alice_goal = w.create_goal("Alice Goal", "", owner="user:alice")
    bob_project = w.create_project("Bob Project", owner="user:bob")
    legacy_project = w.create_project("Legacy Project", owner="")

    for pid in (bob_project, legacy_project):
        r = client.post(
            f"/chat/goal/{alice_goal}/project",
            headers=_as("alice", post=True),
            data={"project_id": str(pid)},
            follow_redirects=False,
        )
        assert r.status_code == 404
        assert w.get_goal(alice_goal).project_id is None

    alice_project = w.create_project("Alice Project", owner="user:alice")
    r = client.post(
        f"/chat/goal/{alice_goal}/project",
        headers=_as("alice", post=True),
        data={"project_id": str(alice_project)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert w.get_goal(alice_goal).project_id == alice_project
