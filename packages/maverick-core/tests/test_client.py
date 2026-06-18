"""Client binding — one Maverick deployment, exactly one enterprise client.
The configured client id is the tenant FLOOR, so every data path re-homes under
tenants/<client>/ and a client-bound surface refuses to serve unbound."""
from __future__ import annotations

import pytest
from maverick import client


@pytest.fixture(autouse=True)
def _reset_cache():
    client.reset_client_cache()
    yield
    client.reset_client_cache()


# ---- resolution -----------------------------------------------------------


def test_client_id_from_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme-corp")
    assert client.client_id() == "acme-corp"


def test_client_id_invalid_rejected(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "bad id/with slash")
    assert client.client_id() is None


def test_client_id_none_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.setattr(client, "_resolve", lambda: None)
    client.reset_client_cache()
    assert client.client_id() is None


def test_client_id_is_cached(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    assert client.client_id() == "acme"
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "other")  # cache holds the first
    assert client.client_id() == "acme"
    client.reset_client_cache()
    assert client.client_id() == "other"


# ---- enforcement guard ----------------------------------------------------


def test_enforced_via_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ENFORCE", "1")
    assert client.client_binding_enforced() is True


def test_require_binding_raises_when_enforced_and_unbound(monkeypatch):
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.setenv("MAVERICK_CLIENT_ENFORCE", "1")
    monkeypatch.setattr(client, "_resolve", lambda: None)
    client.reset_client_cache()
    with pytest.raises(client.ClientBindingError):
        client.require_client_binding()


def test_require_binding_ok_when_bound(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    monkeypatch.setenv("MAVERICK_CLIENT_ENFORCE", "1")
    assert client.require_client_binding() == "acme"


def test_require_binding_noop_when_not_enforced(monkeypatch):
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.delenv("MAVERICK_CLIENT_ENFORCE", raising=False)
    monkeypatch.setattr(client, "_resolve", lambda: None)
    monkeypatch.setattr(client, "client_binding_enforced", lambda: False)
    client.reset_client_cache()
    assert client.require_client_binding() is None  # no raise


# ---- tenant floor + path isolation ----------------------------------------


def test_client_id_is_the_tenant_floor(monkeypatch):
    from maverick import paths
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    client.reset_client_cache()
    assert paths.current_tenant_id() == "acme"


def test_data_paths_rehome_under_client(monkeypatch, tmp_path):
    from maverick import paths
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    client.reset_client_cache()
    p = paths.data_dir("world.db")
    assert "tenants/acme" in str(p).replace("\\", "/")
    assert p == tmp_path / "tenants" / "acme" / "world.db"


def test_explicit_tenant_scope_overrides_client(monkeypatch):
    from maverick import paths
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    client.reset_client_cache()
    token = paths.set_tenant("explicit")
    try:
        assert paths.current_tenant_id() == "explicit"
    finally:
        paths.reset_tenant(token)


def test_unbound_keeps_legacy_root(monkeypatch):
    from maverick import paths
    monkeypatch.delenv("MAVERICK_CLIENT_ID", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    monkeypatch.setattr(client, "_resolve", lambda: None)
    client.reset_client_cache()
    assert paths.current_tenant_id() is None  # legacy shared root, unchanged


# ---- status ---------------------------------------------------------------


def test_status_reports_binding(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIENT_ID", "acme")
    client.reset_client_cache()
    st = client.status()
    assert st["client_id"] == "acme" and st["bound"] is True
    assert "tenants/acme" in st["data_root"].replace("\\", "/")
