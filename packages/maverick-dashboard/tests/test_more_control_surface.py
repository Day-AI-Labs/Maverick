"""Council round-2 Tier-2: the 5 missing UI endpoints that close
capabilities-seat gaps.

- /api/v1/halt now returns reason + armed_at when the file is present.
- /api/v1/cache/stats + /api/v1/cache/purge (with /cache HTML page).
- /api/v1/audit/grep — regex search; mirrors the CLI.
- /api/v1/goals/{id}/resume — flip blocked/cancelled/failed → pending +
  re-queue runner. Closes the parity gap with `maverick resume`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


# ---------- halt detail ----------

def test_halt_status_includes_reason_and_armed_at(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    # Arm with a reason.
    r = client.post(
        "/api/v1/halt",
        json={"reason": "test arm"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    s = client.get("/api/v1/halt").json()
    assert s["file_present"] is True
    assert s["reason"] == "test arm"
    assert isinstance(s["armed_at"], (int, float))
    assert s["armed_at"] > 0


def test_halt_status_when_clear_has_no_reason(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    s = client.get("/api/v1/halt").json()
    assert s["file_present"] is False
    assert s["reason"] is None
    assert s["armed_at"] is None


# ---------- cache ----------

def test_cache_stats_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/cache/stats")
    assert r.status_code == 200
    body = r.json()
    assert "files" in body
    assert "max_entries" in body["files"]


def test_cache_purge_endpoint_default_all(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.post(
        "/api/v1/cache/purge",
        json={"scopes": ["all"]},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200
    report = r.json()
    assert {"files", "repo_map"}.issubset(report.keys())


def test_cache_purge_targeted_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick.file_cache import read_cache_stats, read_file_cached
    f = tmp_path / "x.txt"
    f.write_text("data")
    read_file_cached(f)
    assert read_cache_stats()["entries"] >= 1

    client = _client()
    r = client.post(
        "/api/v1/cache/purge",
        json={"scopes": ["files"]},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200
    assert read_cache_stats()["entries"] == 0


def test_cache_html_page_renders(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/cache")
    assert r.status_code == 200
    text = r.text
    assert "Purge" in text
    assert "files" in text
    # Nav link present.
    assert 'href="/cache"' in text


# ---------- audit grep ----------

def test_audit_grep_requires_pattern(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick.audit.writer as w
    w._default = w.AuditLog(audit_dir=tmp_path / "audit")
    client = _client()
    r = client.get("/api/v1/audit/grep?pattern=")
    assert r.status_code == 422 or r.status_code == 400  # required arg either way


def test_audit_grep_treats_regex_tokens_as_literal_text(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog
    al = AuditLog(audit_dir=tmp_path / "audit")
    al.record(AuditEvent(
        ts=1.0, kind=EventKind.TOOL_CALL,
        payload={"name": "has-parens", "input_summary": "(unclosed"}))
    import maverick.audit.writer as w
    w._default = al
    client = _client()
    # A regex metacharacter that would be an invalid pattern is now matched
    # literally (no ReDoS surface), so this returns the event, not a 400.
    r = client.get("/api/v1/audit/grep?pattern=(unclosed")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["name"] == "has-parens"


def test_audit_grep_finds_matching_events(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick.audit.events import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog
    al = AuditLog(audit_dir=tmp_path / "audit")
    al.record(AuditEvent(
        ts=1.0, kind=EventKind.TOOL_CALL,
        payload={"name": "shell", "input_summary": "ls"}))
    al.record(AuditEvent(
        ts=2.0, kind=EventKind.TOOL_CALL,
        payload={"name": "web_search", "input_summary": "x"}))
    import maverick.audit.writer as w
    w._default = al
    client = _client()
    r = client.get("/api/v1/audit/grep?pattern=shell")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["name"] == "shell"


# ---------- goal resume ----------

def test_resume_404_for_unknown_goal(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.post(
        "/api/v1/goals/9999/resume",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 404


def test_resume_400_when_goal_not_paused(monkeypatch, tmp_path):
    """Only blocked / cancelled / failed goals are resumable."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(tmp_path / "world.db")
    gid = wm.create_goal("g", "x")
    wm.set_goal_status(gid, "active")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    client = _client()
    r = client.post(
        f"/api/v1/goals/{gid}/resume",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 400
    assert "active" in r.json()["detail"]


def test_resume_flips_cancelled_to_pending(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(tmp_path / "world.db")
    gid = wm.create_goal("g", "x")
    wm.set_goal_status(gid, "cancelled", result="cancelled via dashboard")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    # Stub runner so the background task doesn't actually start the agent.
    from maverick import runner
    captured = []
    monkeypatch.setattr(runner, "run_goal_in_thread",
                        lambda *a, **kw: captured.append(("called", a)))
    client = _client()
    r = client.post(
        f"/api/v1/goals/{gid}/resume",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    # The world.db row flipped.
    g = world_model.WorldModel(tmp_path / "world.db").get_goal(gid)
    assert g.status == "pending"
    # The runner was scheduled.
    assert captured, "runner was not scheduled"


def test_resume_blocked_goal(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(tmp_path / "world.db")
    gid = wm.create_goal("g", "x")
    wm.set_goal_status(gid, "blocked")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    from maverick import runner
    monkeypatch.setattr(runner, "run_goal_in_thread", lambda *a, **kw: None)
    client = _client()
    r = client.post(
        f"/api/v1/goals/{gid}/resume",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
