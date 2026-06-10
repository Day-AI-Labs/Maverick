"""Multi-tenant `maverick serve`: roster + spend-cap enforcement at the door."""
from __future__ import annotations

import asyncio

import maverick.server as server_mod
from maverick.paths import data_dir
from maverick.quotas import UsageLedger
from maverick.tenant_registry import (
    create_tenant,
    set_quota,
    suspend_tenant,
    tenant_over_quota,
    tenant_spend_today,
)

# ---- registry-level quota helpers ----

def test_tenant_over_quota_none_without_record(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    assert tenant_over_quota("ghost") is None
    assert tenant_over_quota(None) is None


def test_tenant_spend_sums_all_principals_today(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    ledger = UsageLedger(data_dir("usage", "ledger.json", tenant="acme"))
    ledger.record("user:alice", 3.0, 1, 1)
    ledger.record("user:bob", 2.0, 1, 1)
    ledger.record("user:old", 9.0, 1, 1, day="2020-01-01")  # not today
    assert tenant_spend_today("acme") == 5.0


def test_tenant_over_quota_fires_at_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    create_tenant("acme")
    set_quota("acme", 5.0)
    ledger = UsageLedger(data_dir("usage", "ledger.json", tenant="acme"))
    ledger.record("user:alice", 4.0, 1, 1)
    assert tenant_over_quota("acme") is None  # under
    ledger.record("user:bob", 1.5, 1, 1)
    reason = tenant_over_quota("acme")
    assert reason and "daily spend cap" in reason and "$5.50" in reason


def test_zero_cap_means_no_enforcement(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    create_tenant("free")
    ledger = UsageLedger(data_dir("usage", "ledger.json", tenant="free"))
    ledger.record("user:x", 999.0, 1, 1)
    assert tenant_over_quota("free") is None


# ---- serve-level gate (mirrors test_tenancy's Server harness) ----

class _World:
    def get_or_create_conversation(self, channel, user_id):
        raise AssertionError("refused message must not create a conversation")


class _Msg:
    channel = "slack"
    user_id = "CROOM"
    principal_id = "UALICE"
    text = "hello"
    attachments: list = []


def _serve_with_tenancy(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(server_mod, "tenant_by_user_enabled", lambda: True,
                        raising=False)
    import maverick.paths as paths_mod
    monkeypatch.setattr(paths_mod, "tenant_by_user_enabled", lambda: True)
    monkeypatch.setattr(server_mod, "world_for_tenant", lambda _t: _World())
    return server_mod.Server(world=_World(), llm=object(), sandbox=object())


def test_suspended_tenant_refused_at_door(monkeypatch, tmp_path):
    srv = _serve_with_tenancy(monkeypatch, tmp_path)
    # provision + suspend the per-user tenant id serve derives
    create_tenant("slack:UALICE")
    suspend_tenant("slack:UALICE")
    out = asyncio.run(srv._handle_message(_Msg()))
    assert "suspended" in out
    # _World.get_or_create_conversation never ran (no goal, no turn)


def test_over_cap_tenant_refused_at_door(monkeypatch, tmp_path):
    srv = _serve_with_tenancy(monkeypatch, tmp_path)
    create_tenant("slack:UALICE")
    set_quota("slack:UALICE", 1.0)
    ledger = UsageLedger(
        data_dir("usage", "ledger.json", tenant="slack:UALICE"))
    ledger.record("user:slack:UALICE", 2.0, 1, 1)
    out = asyncio.run(srv._handle_message(_Msg()))
    assert "daily spend cap" in out


def test_unprovisioned_tenant_with_roster_refused(monkeypatch, tmp_path):
    # Once a roster exists, unknown tenants are refused (is_active contract).
    srv = _serve_with_tenancy(monkeypatch, tmp_path)
    create_tenant("someone-else")
    out = asyncio.run(srv._handle_message(_Msg()))
    assert "suspended" in out
