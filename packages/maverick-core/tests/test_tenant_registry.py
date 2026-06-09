"""Tenant lifecycle / provisioning registry (ROADMAP platform spine)."""
from __future__ import annotations

import pytest
from maverick import tenant_registry as tr


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)


def test_create_lists_and_makes_workspace(tmp_path):
    rec = tr.create_tenant("acme", plan="pro", display_name="Acme Inc", max_daily_dollars=50)
    assert rec.id == "acme" and rec.status == tr.ACTIVE and rec.plan == "pro"
    assert rec.max_daily_dollars == 50.0
    assert [t.id for t in tr.list_tenants()] == ["acme"]
    # The tenant's workspace dir was materialized under tenants/.
    assert (tmp_path / "tenants" / "acme").exists()


def test_create_duplicate_rejected():
    tr.create_tenant("acme")
    with pytest.raises(ValueError):
        tr.create_tenant("acme")


def test_create_blank_id_rejected():
    with pytest.raises(ValueError):
        tr.create_tenant("  ")


def test_suspend_resume_flips_active_and_enforcement():
    tr.create_tenant("acme")
    assert tr.is_active("acme") is True
    tr.assert_tenant_active("acme")  # no raise

    tr.suspend_tenant("acme")
    assert tr.is_active("acme") is False
    assert tr.get_tenant("acme").status == tr.SUSPENDED
    with pytest.raises(tr.TenantSuspended):
        tr.assert_tenant_active("acme")

    tr.resume_tenant("acme")
    assert tr.is_active("acme") is True


def test_enforcement_is_noop_for_unprovisioned_and_none():
    # No registry file at all -> everything is active (opt-in).
    assert tr.is_active("never-provisioned") is True
    assert tr.is_active(None) is True
    tr.assert_tenant_active(None)  # no raise
    tr.assert_tenant_active("never-provisioned")  # no raise


def test_unknown_tenant_refused_once_registry_exists():
    tr.create_tenant("acme")
    assert tr.is_active(None) is True
    assert tr.is_active("ghost") is False
    with pytest.raises(tr.TenantSuspended):
        tr.assert_tenant_active("ghost")


def test_set_quota_and_plan():
    tr.create_tenant("acme")
    assert tr.set_quota("acme", 12.5).max_daily_dollars == 12.5
    assert tr.set_plan("acme", "enterprise").plan == "enterprise"


def test_mutate_unknown_tenant_raises():
    with pytest.raises(tr.UnknownTenant):
        tr.suspend_tenant("ghost")


def test_delete_without_purge_keeps_data(tmp_path):
    tr.create_tenant("acme")
    data = tmp_path / "tenants" / "acme"
    (data / "world.db").write_text("x", encoding="utf-8") if data.exists() else None
    assert tr.delete_tenant("acme") is True
    assert tr.get_tenant("acme") is None
    # Data dir survives a non-purging delete.
    assert data.exists()
    assert tr.is_active("acme") is False
    with pytest.raises(tr.TenantSuspended):
        tr.assert_tenant_active("acme")
    assert tr.delete_tenant("acme") is False  # already gone


def test_delete_with_purge_removes_data(tmp_path):
    tr.create_tenant("acme")
    data = tmp_path / "tenants" / "acme"
    (data / "world.db").write_text("x", encoding="utf-8")
    assert tr.delete_tenant("acme", purge=True) is True
    assert not data.exists()


def test_registry_round_trips_on_disk():
    tr.create_tenant("acme", plan="pro")
    tr.create_tenant("beta")
    # Fresh read from disk preserves both records, sorted.
    ids = [t.id for t in tr.list_tenants()]
    assert ids == ["acme", "beta"]
    assert tr.get_tenant("acme").plan == "pro"
