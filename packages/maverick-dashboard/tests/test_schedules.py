"""Dashboard scheduling: arm a saved template (or a prompt) to run on a cron.

Hermetic like the other dashboard tests: HOME is isolated to tmp so JobQueue
uses a tmp jobs.db and templates resolve under tmp. Nothing here runs a goal —
the worker is out of scope; these cover the REST surface that arms/lists/cancels
schedules, plus the [features] scheduling gate.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    # Mutating /api/v1 requests in no-token mode must pass the same-origin CSRF check.
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")


def test_create_list_cancel_text_schedule(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    c = _client()
    r = c.post("/api/v1/schedules", json={
        "cron": "0 9 * * 1-5", "text": "Summarize overnight emails", "title": "AM digest"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cron"] == "0 9 * * 1-5" and body["kind"] == "start_goal"
    assert body["title"] == "AM digest" and body["next_run"] > 0
    sid = body["id"]
    # it appears in the list
    listed = c.get("/api/v1/schedules").json()["schedules"]
    assert any(s["id"] == sid and s["cron"] == "0 9 * * 1-5" for s in listed)
    # cancel; a second cancel is a 404, and it leaves the list
    assert c.delete(f"/api/v1/schedules/{sid}").status_code == 200
    assert c.delete(f"/api/v1/schedules/{sid}").status_code == 404
    assert all(s["id"] != sid for s in c.get("/api/v1/schedules").json()["schedules"])


def test_create_schedule_preserves_proxy_identity(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick_dashboard.auth as auth

    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "proxy_trusts", lambda _host: True)
    monkeypatch.setattr(auth, "proxy_header_name", lambda: "X-Forwarded-User")
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)

    c = _client()
    r = c.post(
        "/api/v1/schedules",
        headers={"X-Forwarded-User": "alice"},
        json={"cron": "0 9 * * *", "text": "Run restricted task", "title": "Restricted"},
    )
    assert r.status_code == 201, r.text

    from maverick.job_queue import JobQueue

    job = JobQueue().get(r.json()["id"])
    assert job is not None
    assert job.payload["owner"] == "user:alice"
    assert job.payload["channel"] == "api"
    assert job.payload["user_id"] == "alice"


def test_create_schedule_returns_stable_schedule_id(monkeypatch, tmp_path):
    # v2 provenance: a stable schedule_id is minted, carried in the job payload
    # (so it survives cron re-arms), surfaced by the API, and used to group runs.
    _isolate(monkeypatch, tmp_path)
    c = _client()
    r = c.post("/api/v1/schedules", json={"cron": "0 9 * * *", "text": "x", "title": "t"})
    assert r.status_code == 201, r.text
    sid = r.json()["schedule_id"]
    assert sid
    from maverick.job_queue import JobQueue
    assert JobQueue().get(r.json()["id"]).payload["schedule_id"] == sid
    listed = c.get("/api/v1/schedules").json()["schedules"]
    assert any(s["schedule_id"] == sid for s in listed)


def test_create_schedule_from_template_renders_params(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    tdir = tmp_path / ".maverick" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "weekly-report.md").write_text(
        "---\ntitle: Weekly {{topic}} report\nparams:\n  - topic\n---\n"
        "Research {{topic}} and email the team.\n", encoding="utf-8")
    c = _client()
    r = c.post("/api/v1/schedules", json={
        "cron": "0 9 * * 1", "template": "weekly-report", "params": {"topic": "rivals"}})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Weekly rivals report"   # title rendered from the template
    # a missing required param is a 400 (render raises ValueError)
    assert c.post("/api/v1/schedules", json={
        "cron": "0 9 * * 1", "template": "weekly-report"}).status_code == 400
    # an unknown template is a 404
    assert c.post("/api/v1/schedules", json={
        "cron": "0 9 * * 1", "template": "nope"}).status_code == 404


def test_bad_cron_and_empty_body_are_400(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    c = _client()
    assert c.post("/api/v1/schedules",
                  json={"cron": "not a cron", "text": "x"}).status_code == 400
    # neither a template nor text to run
    assert c.post("/api/v1/schedules",
                  json={"cron": "0 9 * * *"}).status_code == 400


def test_scheduling_feature_off_403(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick import config
    real = config.get_features
    monkeypatch.setattr(config, "get_features", lambda: {**real(), "scheduling": False})
    c = _client()
    # the mutating route 403s; the read-only list stays available
    assert c.post("/api/v1/schedules",
                  json={"cron": "0 9 * * *", "text": "x"}).status_code == 403
    assert c.get("/api/v1/schedules").status_code == 200
