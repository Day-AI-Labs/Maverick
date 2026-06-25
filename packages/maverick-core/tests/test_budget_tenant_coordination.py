"""Per-run budget coordinated with the per-tenant daily cap (#78).

Without coordination the over-quota gate only fires *between* runs, so a tenant
$1 from its daily ceiling could still launch a $5 run and overshoot. The budget
builder clamps max_dollars to the tenant's remaining daily allowance."""
from __future__ import annotations

import pytest
from maverick.budget import budget_from_config
from maverick.quotas import record_usage
from maverick.tenant import registry


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / ".maverick"))
    for env in ("MAVERICK_TENANT", "MAVERICK_ENFORCE_PLAN_CAPS",
                "MAVERICK_BUDGET_DOLLARS"):
        monkeypatch.delenv(env, raising=False)


def test_remaining_today_none_without_cap():
    assert registry.tenant_remaining_today(None) is None
    assert registry.tenant_remaining_today("ghost") is None   # unprovisioned
    registry.create_tenant("acme", plan="free")               # provisioned, no cap
    assert registry.tenant_remaining_today("acme") is None


def test_remaining_today_is_cap_minus_spend(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 10.0)
    record_usage("user:local", 7.0, 0, 0)                     # acme ledger -> $7
    assert registry.tenant_remaining_today("acme") == pytest.approx(3.0)


def test_budget_clamped_to_tenant_remainder(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 10.0)
    record_usage("user:local", 9.0, 0, 0)                     # $1 left today
    # Even an explicit $5 cap is clamped down to the $1 tenant remainder.
    b = budget_from_config(max_dollars=5.0)
    assert b.max_dollars == pytest.approx(1.0)


def test_budget_clamp_only_lowers(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 100.0)
    record_usage("user:local", 1.0, 0, 0)                     # $99 left
    # A small per-run cap is NOT raised to the big tenant remainder.
    b = budget_from_config(max_dollars=2.0)
    assert b.max_dollars == pytest.approx(2.0)


def test_budget_unchanged_without_tenant():
    # No active tenant -> single-tenant default behavior is untouched.
    b = budget_from_config(max_dollars=5.0)
    assert b.max_dollars == pytest.approx(5.0)


def test_exhausted_tenant_clamps_to_zero(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 5.0)
    record_usage("user:local", 8.0, 0, 0)                     # over cap
    b = budget_from_config(max_dollars=5.0)
    assert b.max_dollars == 0.0


def test_clamp_never_raises_an_unset_cap_above_the_default(monkeypatch):
    # No explicit max_dollars + a tenant with a LARGE remainder must NOT raise
    # the per-run cap above Budget's default -- the clamp only ever lowers.
    from maverick.budget import Budget
    default = Budget.__dataclass_fields__["max_dollars"].default
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    registry.create_tenant("acme", plan="free")
    registry.set_quota("acme", 1000.0)
    record_usage("user:local", 1.0, 0, 0)                     # remainder ~999
    b = budget_from_config()                                  # no max_dollars set
    assert b.max_dollars == pytest.approx(default)            # not 999
