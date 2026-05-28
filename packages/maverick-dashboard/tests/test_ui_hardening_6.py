"""UI hardening round 6: audit-page markup correctness + a11y."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _audit_page(monkeypatch, tmp_path):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(
        "maverick.audit.writer.DEFAULT_AUDIT_DIR", tmp_path / "audit",
    )
    import maverick.audit.writer as w
    w._default = None
    return _client().get("/audit")


def test_audit_div_tags_balanced(monkeypatch, tmp_path):
    """Regression: the search panel carried a stray closing </div>."""
    r = _audit_page(monkeypatch, tmp_path)
    assert r.status_code == 200
    assert r.text.count("<div") == r.text.count("</div>")


def test_audit_search_status_is_live_region(monkeypatch, tmp_path):
    r = _audit_page(monkeypatch, tmp_path)
    assert 'id="audit-search-msg" role="status" aria-live="polite"' in r.text
