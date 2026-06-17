"""Share links end-to-end: create (operator), public read-only view (auth-exempt
token), and revoke. A bad/revoked/expired token 404s and leaks nothing."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


def _world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    return world_model.WorldModel(tmp_path / "world.db")


def _make_goal(w):
    gid = w.create_goal("Refresh forecast", "", domain="finance_cash13w")
    w.set_goal_status(gid, "done", result="| Week | Net |\n| --- | --- |\n| W1 | 300 |")
    return gid


def test_create_and_view_then_revoke(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    gid = _make_goal(w)
    # create (operator; no-token mode == owns everything)
    r = client.post(f"/api/v1/goals/{gid}/share")
    assert r.status_code == 201, r.text
    body = r.json()
    assert "/share/" in body["url"]
    token = body["url"].split("/share/")[1]

    # public view works WITHOUT auth headers (the token is the credential)
    anon = TestClient(app)  # no Origin / no bearer
    page = anon.get(f"/share/{token}")
    assert page.status_code == 200
    assert "Refresh forecast" in page.text
    assert "<td>300</td>" in page.text          # deliverable rendered
    assert "read-only shared view" in page.text.lower()

    # revoke -> the link dies
    rev = client.post(f"/api/v1/goals/{gid}/share/{body['id']}/revoke")
    assert rev.status_code == 200 and rev.json()["ok"] is True
    assert anon.get(f"/share/{token}").status_code == 404


def test_bad_token_404(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    assert TestClient(app).get("/share/not-a-real-token").status_code == 404


def test_share_section_on_goal_page(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    gid = _make_goal(w)
    t = client.get(f"/chat/goal/{gid}").text
    assert "share-create" in t and "Create share link" in t


def test_revoke_is_goal_scoped(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    g1 = _make_goal(w)
    g2 = _make_goal(w)
    token = client.post(f"/api/v1/goals/{g1}/share").json()["url"].split("/share/")[1]
    lid = w.share_links_for_goal(g1)[0]["id"]
    # try to revoke g1's link via g2's path -> no-op, link stays live
    client.post(f"/api/v1/goals/{g2}/share/{lid}/revoke")
    assert TestClient(app).get(f"/share/{token}").status_code == 200
