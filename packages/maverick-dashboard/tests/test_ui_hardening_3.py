"""UI hardening round 3: active-nav highlighting + graceful goal-form errors."""
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


# ---------- active nav highlighting ----------

@pytest.mark.parametrize("path,label", [
    ("/", "Overview"),
    ("/goals", "Goals"),
    ("/facts", "Facts"),
    ("/tools", "Tools"),
    ("/spend", "Spend"),
])
def test_current_page_link_is_marked_active(monkeypatch, tmp_path, path, label):
    _prep(monkeypatch, tmp_path)
    r = _client().get(path)
    assert f'<a href="{path}" class="active" aria-current="page">{label}</a>' in r.text


def test_exactly_one_nav_link_is_active(monkeypatch, tmp_path):
    """Only the current page is highlighted, never two."""
    _prep(monkeypatch, tmp_path)
    r = _client().get("/goals")
    assert r.text.count('aria-current="page"') == 1
    # The home link is rendered in its inactive form on a non-home page.
    assert '<a href="/">Overview</a>' in r.text


def test_home_link_not_active_on_other_pages(monkeypatch, tmp_path):
    """`/` must not match every path via a prefix check."""
    _prep(monkeypatch, tmp_path)
    r = _client().get("/spend")
    assert '<a href="/" class="active"' not in r.text


# ---------- graceful goal-form errors ----------

def test_chat_form_has_inline_error_region(monkeypatch, tmp_path):
    _prep(monkeypatch, tmp_path)
    r = _client().get("/chat")
    assert 'id="goal-error"' in r.text
    assert 'role="alert"' in r.text


def test_chat_form_submits_via_fetch(monkeypatch, tmp_path):
    """The form posts with fetch so 4xx surfaces inline, not as raw JSON.

    The handler lives in base.html (shared by the chat + overview forms),
    so it ships on every page render.
    """
    _prep(monkeypatch, tmp_path)
    r = _client().get("/chat")
    assert "new FormData(form)" in r.text
    # It reads Retry-After so a rate-limited user sees the wait time.
    assert "Retry-After" in r.text


def test_overview_first_run_form_has_inline_error_region(monkeypatch, tmp_path):
    """The landing-page first-goal form gets the same graceful errors."""
    _prep(monkeypatch, tmp_path)
    r = _client().get("/")
    # Empty DB -> first-run branch with the goal form.
    assert 'action="/chat/send"' in r.text
    assert 'id="goal-error"' in r.text
