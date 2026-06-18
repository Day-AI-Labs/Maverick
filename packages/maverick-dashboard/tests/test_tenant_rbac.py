"""Per-tenant RBAC: a principal can hold a different role in each tenant.

Tenant memberships override the GLOBAL stored role for that tenant only; the
config-pinned bootstrap admin stays globally admin regardless (can't be locked
out of a tenant). No active tenant / no membership => unchanged global behaviour.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    # store_path()/tenant_store_path() use Path.home(); point HOME at tmp too.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield


def test_tenant_membership_store_roundtrip():
    from maverick_dashboard import rbac
    assert rbac.list_tenant_roles("acme") == {}
    rbac.set_tenant_role("acme", "user:alice", "admin")
    rbac.set_tenant_role("acme", "user:bob", "viewer")
    assert rbac.get_tenant_role("acme", "user:alice") == "admin"
    assert rbac.list_tenant_roles("acme") == {"user:alice": "admin", "user:bob": "viewer"}
    # Distinct tenants are independent.
    assert rbac.get_tenant_role("globex", "user:alice") is None
    rbac.remove_tenant_role("acme", "user:alice")
    assert rbac.get_tenant_role("acme", "user:alice") is None


def test_bad_role_rejected():
    from maverick_dashboard import rbac
    with pytest.raises(ValueError):
        rbac.set_tenant_role("acme", "user:x", "superuser")


def test_role_for_principal_uses_tenant_membership(monkeypatch):
    from maverick.paths import reset_tenant, set_tenant
    from maverick_dashboard import auth, rbac

    # Global role for alice is viewer; in acme she is an operator.
    rbac.set_role("user:alice", "viewer")
    rbac.set_tenant_role("acme", "user:alice", "operator")

    # No active tenant -> global role.
    assert auth.role_for_principal("user:alice") == "viewer"

    # Active tenant acme -> tenant membership wins.
    tok = set_tenant("acme")
    try:
        assert auth.role_for_principal("user:alice") == "operator"
    finally:
        reset_tenant(tok)

    # A tenant with no membership for alice -> falls back to global role.
    tok = set_tenant("globex")
    try:
        assert auth.role_for_principal("user:alice") == "viewer"
    finally:
        reset_tenant(tok)


def test_bootstrap_admin_stays_admin_in_every_tenant(monkeypatch):
    from maverick.paths import reset_tenant, set_tenant
    from maverick_dashboard import auth, rbac

    monkeypatch.setenv("MAVERICK_DASHBOARD_ADMINS", "user:root")
    # Even if someone tries to demote root within a tenant, bootstrap wins.
    rbac.set_tenant_role("acme", "user:root", "viewer")
    tok = set_tenant("acme")
    try:
        assert auth.role_for_principal("user:root") == "admin"
    finally:
        reset_tenant(tok)
