"""Council pass: dashboard control surface.

Adds halt button, consent / answer-question UI, audit log page,
plugins / MCP / tools / channels list pages, skill install form, and
goal cancel. Each requires a backing route or page render here.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


# ---------- halt ----------

def test_halt_status_when_clear(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/halt")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert body["file"].endswith("HALT")
    assert body["file_present"] is False


def test_halt_post_then_status_then_delete(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    # Arm.
    r = client.post(
        "/api/v1/halt",
        json={"reason": "test"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    assert (tmp_path / "HALT").exists()
    # Status reflects file presence.
    s = client.get("/api/v1/halt").json()
    assert s["file_present"] is True
    # Clear.
    r = client.delete(
        "/api/v1/halt",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    assert not (tmp_path / "HALT").exists()


# ---------- cancel goal ----------

def test_cancel_goal_marks_status(monkeypatch, tmp_path: Path):
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)

    wm = world_model.WorldModel(db)
    gid = wm.create_goal("test", "desc")
    wm.close() if hasattr(wm, "close") else None

    client = _client()
    r = client.post(
        f"/api/v1/goals/{gid}/cancel",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204

    wm2 = world_model.WorldModel(db)
    g = wm2.get_goal(gid)
    assert g.status == "cancelled"


def test_cancel_unknown_goal_404(monkeypatch, tmp_path: Path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.post(
        "/api/v1/goals/99999/cancel",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 404


def test_cancel_already_done_goal_noop(monkeypatch, tmp_path: Path):
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(db)
    gid = wm.create_goal("test", "desc")
    wm.set_goal_status(gid, "done", result="ok")
    client = _client()
    r = client.post(
        f"/api/v1/goals/{gid}/cancel",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 204
    g = world_model.WorldModel(db).get_goal(gid)
    assert g.status == "done"  # untouched


# ---------- open questions ----------

def test_open_questions_empty(monkeypatch, tmp_path: Path):
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(db)
    gid = wm.create_goal("test", "desc")
    client = _client()
    r = client.get(f"/api/v1/goals/{gid}/open_questions")
    assert r.status_code == 200
    assert r.json() == {"open_questions": []}


def test_open_questions_returns_unanswered(monkeypatch, tmp_path: Path):
    from maverick import world_model
    db = tmp_path / "world.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(db)
    gid = wm.create_goal("test", "desc")
    wm.ask("Which dates?", goal_id=gid)
    client = _client()
    r = client.get(f"/api/v1/goals/{gid}/open_questions")
    body = r.json()
    assert len(body["open_questions"]) == 1
    assert body["open_questions"][0]["question"] == "Which dates?"


# ---------- list endpoints ----------

def test_list_plugins_returns_groups(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/plugins")
    assert r.status_code == 200
    body = r.json()
    assert "plugins" in body
    for kind in ("tools", "channels", "skills", "personas"):
        assert kind in body["plugins"]
        assert isinstance(body["plugins"][kind], list)


def test_list_mcp_servers(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/mcp")
    assert r.status_code == 200
    assert "servers" in r.json()


def test_list_channels(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/channels")
    assert r.status_code == 200
    assert "channels" in r.json()


def test_audit_tail_empty(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    # AuditLog's default arg was bound at class-def time, so patching
    # DEFAULT_AUDIT_DIR on the module is ineffective. Inject a fresh
    # singleton with the explicit tmp dir.
    import maverick.audit.writer as w
    w._default = w.AuditLog(audit_dir=tmp_path / "audit")
    client = _client()
    r = client.get("/api/v1/audit/tail")
    assert r.status_code == 200
    assert r.json()["events"] == []


# ---------- HTML pages render ----------

def test_audit_page_renders(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(
        "maverick.audit.writer.DEFAULT_AUDIT_DIR", tmp_path / "audit",
    )
    import maverick.audit.writer as w
    w._default = None
    client = _client()
    r = client.get("/audit")
    assert r.status_code == 200
    assert "audit log" in r.text.lower()


def test_plugins_page_renders(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/plugins")
    assert r.status_code == 200
    assert "plugins" in r.text.lower()


def test_mcp_page_renders(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/mcp")
    assert r.status_code == 200
    assert "mcp" in r.text.lower()


def test_tools_page_renders(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/tools")
    assert r.status_code == 200
    assert "tool" in r.text.lower()


def test_channels_page_renders(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/channels")
    assert r.status_code == 200
    assert "channel" in r.text.lower()


def test_channels_page_redacts_sensitive_values(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick.config as _cfg
    monkeypatch.setattr(
        _cfg,
        "load_config",
        lambda: {
            "channels": {
                "slack": {
                    "enabled": True,
                    "bot_token": "xoxb-real-secret",
                    "app_token": "xapp-real-secret",
                    "workspace": "ops",
                }
            }
        },
    )
    client = _client()
    r = client.get("/channels")
    assert r.status_code == 200
    assert "workspace=ops" in r.text
    assert "bot_token=[redacted]" in r.text
    assert "app_token=[redacted]" in r.text
    assert "xoxb-real-secret" not in r.text
    assert "xapp-real-secret" not in r.text


# ---------- nav + halt UI present in base.html ----------

def test_base_nav_includes_new_pages(monkeypatch, tmp_path):
    """Every new page is reachable via the header nav."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/")
    text = r.text
    for href in ("/audit", "/plugins", "/mcp", "/tools", "/channels"):
        assert href in text, f'nav missing link to {href}'


def test_base_renders_halt_pill(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/")
    assert "halt-pill" in r.text


def test_footer_no_longer_leaks_world_db_path(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/")
    assert "~/.maverick/world.db" not in r.text


# ---------- index hero empty state ----------

def test_index_empty_state_shows_hero(monkeypatch, tmp_path):
    """The overview shows the hero CTA on a fresh install, not 4 zeros + 3 'No X yet' rows."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/overview")
    text = r.text
    assert "Start your first goal" in text
    # The 4-zeros graveyard should be absent on a fresh install.
    assert text.count('class="num"') == 0
