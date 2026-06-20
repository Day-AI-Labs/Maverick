"""Operator tenant console (/tenants) — the hosted control-plane roster view."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)


def test_tenants_page_renders_and_nav(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _client().get("/tenants")
    assert r.status_code == 200
    assert "tenants" in r.text.lower()
    assert 'href="/tenants"' in r.text  # nav link wired


def test_empty_state(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert "No tenants provisioned" in _client().get("/tenants").text


def test_lists_provisioned_tenants(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    from maverick.tenant import registry as tr
    tr.create_tenant("acme", plan="enterprise", display_name="Acme Inc",
                     max_daily_dollars=100)
    tr.create_tenant("beta")
    tr.suspend_tenant("beta")
    text = _client().get("/tenants").text
    assert "acme" in text and "enterprise" in text and "Acme Inc" in text
    assert "$100/day" in text
    # beta is suspended.
    assert "beta" in text and "suspended" in text
