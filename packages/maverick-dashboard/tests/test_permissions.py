"""Permissions page + snapshot + tool disable/enable via the overlay."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    from maverick import runtime_overrides, world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setattr(runtime_overrides, "OVERRIDES_PATH", tmp_path / "ro.toml")
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)


def test_permissions_api_shape(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.get("/api/v1/permissions")
    assert r.status_code == 200
    body = r.json()
    for key in ("tools", "capabilities", "channels", "sandbox", "budget",
                "network", "providers", "retention", "overlay_denied"):
        assert key in body
    assert isinstance(body["tools"], list)


def test_permissions_tools_include_enabled_flag(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    body = client.get("/api/v1/permissions").json()
    # The registry builds a bunch of tools; each carries an enabled flag.
    assert body["tools"], "expected some tools registered"
    assert all("enabled" in t for t in body["tools"])
    assert any(t["enabled"] for t in body["tools"])


def test_permissions_warns_on_local_sandbox(monkeypatch, tmp_path):
    """The default (no-isolation) local sandbox must be flagged on the
    permissions surface, and an isolated backend must NOT be flagged."""
    _isolate(monkeypatch, tmp_path)  # no config file -> defaults to local
    client = _client()
    body = client.get("/api/v1/permissions").json()
    assert body["sandbox_warning"], "local sandbox should be flagged"
    assert "isolation" in body["sandbox_warning"]
    # Page renders the banner too.
    assert "⚠" in client.get("/permissions").text

    # An explicit docker backend is isolated -> no warning.
    (tmp_path / "config.toml").write_text('[sandbox]\nbackend = "docker"\n')
    body2 = client.get("/api/v1/permissions").json()
    assert body2["sandbox_warning"] is None


def test_disable_tool_then_shows_disabled(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    # shell is registered + enabled to start.
    before = {t["name"]: t["enabled"] for t in client.get("/api/v1/permissions").json()["tools"]}
    assert before.get("shell") is True

    r = client.post("/api/v1/permissions/tools/shell/disable", headers={"Origin": "http://testserver"})
    assert r.status_code == 204

    after = {t["name"]: t["enabled"] for t in client.get("/api/v1/permissions").json()["tools"]}
    assert after.get("shell") is False
    # Overlay file records it.
    assert "shell" in client.get("/api/v1/permissions").json()["overlay_denied"]


def test_enable_tool_clears_override(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    client.post("/api/v1/permissions/tools/shell/disable", headers={"Origin": "http://testserver"})
    r = client.post("/api/v1/permissions/tools/shell/enable", headers={"Origin": "http://testserver"})
    assert r.status_code == 204
    body = client.get("/api/v1/permissions").json()
    assert "shell" not in body["overlay_denied"]
    names = {t["name"]: t["enabled"] for t in body["tools"]}
    assert names.get("shell") is True


def test_disable_tool_rejects_invalid_name(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.post('/api/v1/permissions/tools/bad"name/disable', headers={"Origin": "http://testserver"})
    assert r.status_code == 400


def test_permissions_page_renders(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.get("/permissions")
    assert r.status_code == 200
    text = r.text
    assert "what lightwork can do" in text.lower()
    assert "your data" in text.lower()
    assert "No telemetry" in text
    # Nav link present.
    assert 'href="/permissions"' in text


def test_permissions_page_shows_disable_buttons(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    client = _client()
    r = client.get("/permissions")
    assert "perm-toggle" in r.text
    assert "Disable" in r.text
