"""UI hardening round 4: action-result feedback (ARIA live + error detail)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _prep(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()


# ---------- ARIA live regions on status messages ----------

@pytest.mark.parametrize("path,msg_id", [
    ("/permissions", "perm-msg"),
    ("/cache", "cache-msg"),
    ("/skills", "skill-install-msg"),
    ("/store", "store-msg"),
])
def test_status_region_is_an_aria_live_region(monkeypatch, tmp_path, path, msg_id):
    """Dynamically-updated result text is announced to screen readers."""
    _prep(monkeypatch, tmp_path)
    r = _client().get(path)
    assert f'id="{msg_id}" role="status" aria-live="polite"' in r.text


# ---------- error messages surface the server's detail ----------

@pytest.mark.parametrize("path", ["/permissions", "/cache"])
def test_action_errors_read_server_detail(monkeypatch, tmp_path, path):
    """A failed action shows the server's reason, not a bare status code."""
    _prep(monkeypatch, tmp_path)
    r = _client().get(path)
    assert "j.detail" in r.text
