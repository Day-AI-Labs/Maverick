"""Metering -> billing & entitlements (ROADMAP platform spine)."""
from __future__ import annotations

import pytest
from maverick import billing
from maverick.billing import (
    Entitlements,
    RateCard,
    entitled,
    entitlements_for,
    rate_ledger,
)
from maverick.quotas import UsageLedger


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)


def _ledger(tmp_path):
    led = UsageLedger(path=tmp_path / "ledger.json")
    led.record("user:alice", 1.00, 10_000, 2_000, day="2026-06-01")
    led.record("user:alice", 0.50, 5_000, 1_000, day="2026-06-02")
    led.record("user:bob", 2.00, 20_000, 4_000, day="2026-06-02")
    return led


# ---- rating -----------------------------------------------------------------

def test_passthrough_with_markup(tmp_path):
    led = _ledger(tmp_path)
    inv = rate_ledger(led, RateCard(markup_pct=20.0), tenant="acme")
    # 3 line items, each charged at cost * 1.2.
    assert len(inv.line_items) == 3
    alice_d1 = next(li for li in inv.line_items if li.principal == "user:alice" and li.day == "2026-06-01")
    assert alice_d1.charge == pytest.approx(1.20)
    # subtotal = (1.00 + 0.50 + 2.00) * 1.2 = 4.20
    assert inv.subtotal == pytest.approx(4.20)
    assert inv.total == pytest.approx(4.20)


def test_token_priced(tmp_path):
    led = _ledger(tmp_path)
    card = RateCard(usd_per_million_input_tokens=3.0, usd_per_million_output_tokens=15.0)
    inv = rate_ledger(led, card)
    # bob 2026-06-02: 20k in * $3/M + 4k out * $15/M = 0.06 + 0.06 = 0.12
    bob = next(li for li in inv.line_items if li.principal == "user:bob")
    assert bob.charge == pytest.approx(0.12)


def test_period_filter_and_minimum_charge(tmp_path):
    led = _ledger(tmp_path)
    inv = rate_ledger(led, RateCard(minimum_charge=100.0), since="2026-06-02", until="2026-06-02")
    # Only the two 06-02 rows are in-period.
    assert {li.day for li in inv.line_items} == {"2026-06-02"}
    assert inv.subtotal == pytest.approx(2.50)
    # minimum charge floors the total.
    assert inv.total == pytest.approx(100.0)


def test_empty_ledger_is_zero_invoice(tmp_path):
    inv = rate_ledger(UsageLedger(path=tmp_path / "empty.json"), RateCard())
    assert inv.line_items == []
    assert inv.total == 0.0


def test_invoice_to_dict_round_trips(tmp_path):
    inv = rate_ledger(_ledger(tmp_path), RateCard(), tenant="acme")
    d = inv.to_dict()
    assert d["tenant"] == "acme"
    assert len(d["line_items"]) == 3
    assert d["total"] == inv.total


# ---- entitlements -----------------------------------------------------------

def test_default_plans_gate_features():
    assert entitled("free", "core") is True
    assert entitled("free", "grpc") is False
    assert entitled("pro", "grpc") is True
    assert entitled("enterprise", "sso") is True
    # Unknown plan -> free entitlements.
    assert entitled("mystery", "grpc") is False


def test_config_override_plans(monkeypatch):
    # entitlements_for reads [billing.plans] via config.load_config (lazy import).
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {
        "billing": {"plans": {"pro": {"features": ["core", "wow"], "max_daily_dollars": 9}}}
    })
    ent = entitlements_for("pro")
    assert isinstance(ent, Entitlements)
    assert "wow" in ent.features
    assert ent.max_daily_dollars == 9.0


def test_tenant_entitled_reads_registered_plan(tmp_path):
    from maverick import tenant_registry as tr
    tr.create_tenant("acme", plan="enterprise")
    assert billing.tenant_entitled("acme", "audit_export") is True
    assert billing.tenant_entitled("acme", "nonexistent") is False
    # Unprovisioned tenant -> free.
    assert billing.tenant_entitled("ghost", "grpc") is False
