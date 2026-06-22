"""Per-request tenant pinning (council #6).

The world model's tenant scoping (app-layer predicate + Postgres RLS GUC) only
engages when a tenant is pinned; no dashboard request pinned one. The
tenant_pinning middleware pins it from the verified principal when per-user
tenancy is enabled, and is a no-op (single-tenant default) otherwise.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard import app as app_mod
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    yield


def test_pins_tenant_from_principal_when_by_user_enabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    monkeypatch.setattr(app_mod, "caller_principal", lambda request: "user:alice")
    calls = []
    import maverick.paths as paths
    real_set = paths.set_tenant

    def _record(t):
        calls.append(t)
        return real_set(t)

    monkeypatch.setattr(paths, "set_tenant", _record)
    r = client.get("/healthz")
    assert r.status_code in (200, 503)  # health may be degraded without a key
    assert calls == ["api:user:alice"]  # pinned to the principal's tenant
    # And the pin was reset after the request (no leak).
    assert paths.current_tenant_id() is None


def test_no_pin_when_by_user_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT_BY_USER", raising=False)
    monkeypatch.setattr(app_mod, "caller_principal", lambda request: "user:bob")
    calls = []
    import maverick.paths as paths
    monkeypatch.setattr(paths, "set_tenant", lambda t: calls.append(t))
    client.get("/healthz")
    assert calls == []  # single-tenant default: no pinning


def test_no_pin_when_no_principal(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    monkeypatch.setattr(app_mod, "caller_principal", lambda request: None)
    calls = []
    import maverick.paths as paths
    monkeypatch.setattr(paths, "set_tenant", lambda t: calls.append(t))
    client.get("/healthz")
    assert calls == []  # unauthenticated -> no tenant to pin
