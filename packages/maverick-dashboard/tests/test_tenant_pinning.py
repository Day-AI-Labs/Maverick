"""Per-request tenant pinning (council #6).

The world model's tenant scoping (app-layer predicate + Postgres RLS GUC) only
engages when a tenant is pinned; no dashboard request pinned one. The
tenant_pinning middleware pins it from the verified principal when per-user
tenancy is enabled, and is a no-op (single-tenant default) otherwise.
"""

from __future__ import annotations

import maverick_dashboard.auth as auth
import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model

    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    yield


def _enable_proxy_auth(monkeypatch):
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "proxy_trusts", lambda host: True)
    monkeypatch.setattr(auth, "proxy_header_name", lambda: "X-Forwarded-User")
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)


def test_pins_tenant_from_real_proxy_principal_when_by_user_enabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    _enable_proxy_auth(monkeypatch)
    calls = []
    import maverick.paths as paths

    real_set = paths.set_tenant

    def _record(t):
        calls.append(t)
        return real_set(t)

    monkeypatch.setattr(paths, "set_tenant", _record)
    r = client.get("/api/v1/facts", headers={"X-Forwarded-User": "alice"})
    assert r.status_code == 200
    assert calls == ["api:user:alice"]  # pinned after auth, before route world lookup
    # And the pin was reset after the request (no leak).
    assert paths.current_tenant_id() is None


def test_no_pin_when_by_user_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT_BY_USER", raising=False)
    _enable_proxy_auth(monkeypatch)
    calls = []
    import maverick.paths as paths

    monkeypatch.setattr(paths, "set_tenant", lambda t: calls.append(t))
    r = client.get("/api/v1/facts", headers={"X-Forwarded-User": "bob"})
    assert r.status_code == 200
    assert calls == []  # single-tenant default: no pinning


def test_no_pin_when_no_principal(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    monkeypatch.setattr(auth, "proxy_auth_enabled", lambda: False)
    monkeypatch.setattr(auth, "oidc_enabled", lambda: False)
    calls = []
    import maverick.paths as paths

    monkeypatch.setattr(paths, "set_tenant", lambda t: calls.append(t))
    r = client.get("/api/v1/facts")
    assert r.status_code == 200
    assert calls == []  # unauthenticated -> no tenant to pin
