"""P2 cost-governance layer: a per-principal usage ledger + daily quota check.

Budget caps one run; quotas cap a principal across runs over a rolling day, so
an operator can chargeback / rate-limit spend per user. Default-off and opt-in
(``[quotas] enforce`` or ``MAVERICK_QUOTA_*``), and fail-soft: a ledger error
must never crash a run. ``HOME`` is isolated per-test by the autouse conftest
fixture, so every ledger lands under the temp ``~/.maverick``.
"""
from __future__ import annotations

import json

import pytest
from maverick.quotas import (
    UsageLedger,
    over_quota,
    quotas_enforced,
    record_usage,
)


@pytest.fixture(autouse=True)
def _clear_quota_env(monkeypatch):
    for env in (
        "MAVERICK_QUOTA_ENFORCE",
        "MAVERICK_QUOTA_MAX_DOLLARS_PER_DAY",
        "MAVERICK_QUOTA_MAX_TOKENS_PER_DAY",
        "MAVERICK_TENANT",
    ):
        monkeypatch.delenv(env, raising=False)


def _enforce(monkeypatch, *, dollars=0.0, tokens=0):
    monkeypatch.setenv("MAVERICK_QUOTA_ENFORCE", "1")
    if dollars:
        monkeypatch.setenv("MAVERICK_QUOTA_MAX_DOLLARS_PER_DAY", str(dollars))
    if tokens:
        monkeypatch.setenv("MAVERICK_QUOTA_MAX_TOKENS_PER_DAY", str(tokens))


# --- ledger ----------------------------------------------------------------

def test_record_and_usage_roundtrip():
    led = UsageLedger()
    led.record("alice", 1.50, 1000, 200)
    u = led.usage("alice")
    assert u == {"dollars": 1.5, "in_tokens": 1000, "out_tokens": 200}


def test_record_accumulates_within_day():
    led = UsageLedger()
    led.record("alice", 1.0, 100, 10)
    led.record("alice", 2.0, 50, 5)
    u = led.usage("alice")
    assert u["dollars"] == pytest.approx(3.0)
    assert u["in_tokens"] == 150
    assert u["out_tokens"] == 15


def test_usage_unknown_principal_is_zero():
    assert UsageLedger().usage("nobody") == {
        "dollars": 0.0, "in_tokens": 0, "out_tokens": 0,
    }


def test_principals_are_isolated():
    led = UsageLedger()
    led.record("alice", 5.0, 0, 0)
    led.record("bob", 1.0, 0, 0)
    assert led.usage("alice")["dollars"] == pytest.approx(5.0)
    assert led.usage("bob")["dollars"] == pytest.approx(1.0)


def test_record_persists_across_instances():
    UsageLedger().record("alice", 2.0, 0, 0)
    # A fresh instance reads from disk -> concurrent processes accrue correctly.
    assert UsageLedger().usage("alice")["dollars"] == pytest.approx(2.0)


def test_distinct_days_do_not_mix():
    led = UsageLedger()
    led.record("alice", 1.0, 0, 0, day="2026-01-01")
    led.record("alice", 4.0, 0, 0, day="2026-01-02")
    assert led.usage("alice", day="2026-01-01")["dollars"] == pytest.approx(1.0)
    assert led.usage("alice", day="2026-01-02")["dollars"] == pytest.approx(4.0)


def test_negative_inputs_clamped():
    led = UsageLedger()
    led.record("alice", -5.0, -10, -1)
    assert led.usage("alice") == {"dollars": 0.0, "in_tokens": 0, "out_tokens": 0}


def test_blank_principal_ignored():
    led = UsageLedger()
    led.record("", 5.0, 0, 0)
    assert led._load() == {}


def test_ledger_is_tenant_scoped(monkeypatch):
    from maverick.paths import set_tenant
    tok = set_tenant("team-a")
    try:
        UsageLedger().record("alice", 9.0, 0, 0)
    finally:
        from maverick.paths import reset_tenant
        reset_tenant(tok)
    # Different tenant -> different ledger file -> no spend visible.
    tok2 = set_tenant("team-b")
    try:
        assert UsageLedger().usage("alice")["dollars"] == pytest.approx(0.0)
    finally:
        from maverick.paths import reset_tenant
        reset_tenant(tok2)


def test_corrupt_ledger_is_fail_soft(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{ not json")
    led = UsageLedger(path=path)
    # Reads as empty, and a write recovers (overwrites) without raising.
    assert led.usage("alice")["dollars"] == 0.0
    led.record("alice", 1.0, 0, 0)
    assert json.loads(path.read_text())["alice"]


def test_record_usage_fail_soft_on_bad_path(monkeypatch, caplog):
    # An unwritable ledger path must not raise out of record_usage.
    import maverick.quotas as q

    class _Boom:
        def record(self, *a, **k):
            raise OSError("disk full")
    monkeypatch.setattr(q, "UsageLedger", lambda *a, **k: _Boom())
    record_usage("alice", 1.0, 1, 1)  # no exception


# --- enforcement toggle ----------------------------------------------------

def test_default_off():
    assert quotas_enforced() is False


def test_enforced_via_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_QUOTA_ENFORCE", "1")
    assert quotas_enforced() is True


def test_enforced_via_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[quotas]\nenforce = true\n")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    assert quotas_enforced() is True


# --- over_quota ------------------------------------------------------------

def test_over_quota_none_when_disabled(monkeypatch):
    record_usage("alice", 1000.0, 0, 0)
    assert over_quota("alice") is None  # enforcement off


def test_over_quota_none_when_no_caps(monkeypatch):
    _enforce(monkeypatch)  # enforce on, but no caps set -> no limit
    record_usage("alice", 1000.0, 0, 0)
    assert over_quota("alice") is None


def test_over_quota_dollars(monkeypatch):
    _enforce(monkeypatch, dollars=5.0)
    record_usage("alice", 4.0, 0, 0)
    assert over_quota("alice") is None
    record_usage("alice", 1.5, 0, 0)  # now 5.5 >= 5.0
    reason = over_quota("alice")
    assert reason and "spend quota" in reason


def test_over_quota_tokens(monkeypatch):
    _enforce(monkeypatch, tokens=1000)
    record_usage("alice", 0.0, 600, 300)  # 900 < 1000
    assert over_quota("alice") is None
    record_usage("alice", 0.0, 100, 50)   # 1050 >= 1000
    reason = over_quota("alice")
    assert reason and "token quota" in reason


def test_over_quota_blank_principal(monkeypatch):
    _enforce(monkeypatch, dollars=1.0)
    assert over_quota("") is None


def test_over_quota_isolates_principals(monkeypatch):
    _enforce(monkeypatch, dollars=5.0)
    record_usage("alice", 10.0, 0, 0)
    assert over_quota("alice") is not None
    assert over_quota("bob") is None  # bob hasn't spent


def test_run_goal_blocks_over_quota_principal(monkeypatch, tmp_path, fake_llm):
    from maverick.budget import Budget
    from maverick.orchestrator import run_goal
    from maverick.sandbox import LocalBackend
    from maverick.world_model import WorldModel

    _enforce(monkeypatch, dollars=1.0)
    record_usage("attacker", 1.0, 0, 0)
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("blocked quota", "")

    import asyncio

    out = asyncio.run(run_goal(
        fake_llm, world, Budget(max_dollars=1.0), gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1, user_id="attacker",
    ))

    assert "quota exceeded" in out
    assert world.get_goal(gid).status == "blocked"
    assert fake_llm.calls == []


def test_run_goal_records_usage_for_principal(monkeypatch, tmp_path, fake_llm, make_llm_response):
    from maverick.budget import Budget
    from maverick.orchestrator import run_goal
    from maverick.sandbox import LocalBackend
    from maverick.world_model import WorldModel

    fake_llm.scripted = [
        make_llm_response(text="FINAL: quota accounting works"),
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        make_llm_response(text="FINAL: (no skill)"),
    ]
    budget = Budget(max_dollars=1.0)
    budget.record_tokens(1000, 250, model="fake:test")
    before = budget.dollars
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("account quota", "")

    import asyncio

    asyncio.run(run_goal(
        fake_llm, world, budget, gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1, user_id="alice",
    ))

    usage = UsageLedger().usage("alice")
    assert usage["dollars"] >= before
    assert usage["in_tokens"] >= 1000
    assert usage["out_tokens"] >= 250
