"""UI hardening: CSP + security headers, plan-tree escaping, trajectory a11y."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


# ---------- Content-Security-Policy ----------

def test_csp_header_present_and_locked_down(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    csp = _client().get("/").headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    # The exfil + clickjack + injection backstops:
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    # Dashboard pages stay self-only.
    assert "http://" not in csp and "https://" not in csp


def test_docs_csp_allows_fastapi_cdn_assets(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    docs_csp = _client().get("/docs").headers.get("Content-Security-Policy", "")
    redoc_csp = _client().get("/redoc").headers.get("Content-Security-Policy", "")
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "https://cdn.jsdelivr.net" in redoc_csp
    assert "connect-src 'self'" in docs_csp and "connect-src 'self'" in redoc_csp


def test_csp_on_api_responses_too(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    r = _client().get("/livez")
    assert "Content-Security-Policy" in r.headers


def test_all_baseline_headers_still_present(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    h = _client().get("/").headers
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "no-referrer"
    assert h["Cross-Origin-Opener-Policy"] == "same-origin"


# ---------- plan-tree escaping ----------

def test_plan_tree_escapes_quotes_in_title(monkeypatch, tmp_path):
    """A goal title with a quote + angle bracket must be escaped in the
    pre-rendered HTML (quote=True closes the attribute-context hole)."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(tmp_path / "world.db")
    gid = wm.create_goal('"><script>alert(1)</script>', "x")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    r = _client().get(f"/goals/{gid}/plan")
    assert r.status_code == 200
    # The raw script tag must NOT appear unescaped.
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_render_tree_html_quote_escaping_unit():
    from maverick_dashboard.app import _render_tree_html
    node = {
        "id": 1, "parent_id": None, "status": 'x" onmouseover="alert(1)',
        "title": "t", "dollars": 0, "children": [],
    }
    html = _render_tree_html(node)
    # The double-quote in status must be entity-encoded so it can't break
    # out of class="badge ...".
    assert 'onmouseover="alert(1)"' not in html
    assert "&quot;" in html


# ---------- trajectory a11y ----------

def test_trajectory_controls_have_aria_labels(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    wm = world_model.WorldModel(tmp_path / "world.db")
    gid = wm.create_goal("g", "x")
    wm.append_event(gid, "agent", "plan", "first")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    r = _client().get(f"/goals/{gid}/trajectory")
    assert r.status_code == 200
    for label in ("Jump to start", "Step back", "Step forward", "Jump to end",
                  "Scrub through events"):
        assert label in r.text
    # Keyboard handler wired.
    assert "ArrowLeft" in r.text and "ArrowRight" in r.text
