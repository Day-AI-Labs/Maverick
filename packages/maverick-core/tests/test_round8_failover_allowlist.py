"""Audit round 8: provider-failover governance + reliability.

1. Admin model allow-list bypass. ``model_for_role`` enforces the
   ``[access] allowed_models`` hard cap on role resolution, but failover chains
   were dispatched straight from config without passing back through it -- so a
   transient error on the primary could fail over to a model the operator
   forbade. ``_allowlist_filter_fallbacks`` drops disallowed fallbacks.

2. Inert cooldown ledger. ``order_chain`` skips models in cooldown, but nothing
   on the live path ever called ``record_failure``/``record_success``, so
   ``in_cooldown`` was always False and the configured cooldown policy was a
   dead no-op. ``failover``/``afailover`` now feed the shared ledger.
"""
from __future__ import annotations

import pytest

# --- fix 1: failover cannot dispatch a model outside the admin allow-list ---

def _point_overlay(monkeypatch, tmp_path):
    from maverick import runtime_overrides
    monkeypatch.setattr(
        runtime_overrides, "OVERRIDES_PATH", tmp_path / "runtime-overrides.toml")
    return runtime_overrides


def test_allowlist_filter_drops_disallowed_fallbacks(monkeypatch, tmp_path):
    from maverick.llm import _allowlist_filter_fallbacks
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.set_allowed_models(["anthropic:claude-sonnet-4-6"])

    chain = ["anthropic:claude-opus-4-8", "anthropic:claude-sonnet-4-6"]
    assert _allowlist_filter_fallbacks(chain) == ["anthropic:claude-sonnet-4-6"]


def test_allowlist_filter_noop_without_allowlist(monkeypatch, tmp_path):
    from maverick.llm import _allowlist_filter_fallbacks
    _point_overlay(monkeypatch, tmp_path)  # no allow-list set -> unrestricted
    chain = ["anthropic:claude-opus-4-8", "openai:gpt-4.1"]
    assert _allowlist_filter_fallbacks(chain) == chain


def test_allowlist_filter_can_empty_the_chain(monkeypatch, tmp_path):
    # Every fallback disallowed -> empty chain -> the wiring skips failover and
    # runs only the (unchanged) primary, never a forbidden fallback.
    from maverick.llm import _allowlist_filter_fallbacks
    ro = _point_overlay(monkeypatch, tmp_path)
    ro.set_allowed_models(["anthropic:claude-sonnet-4-6"])
    assert _allowlist_filter_fallbacks(["openai:gpt-4.1", "gemini:g"]) == []


# --- fix 2: failover feeds the cooldown ledger so order_chain can skip ------

@pytest.fixture
def _policy_window(monkeypatch):
    from maverick import failover_policy as fp
    monkeypatch.setattr(fp, "_policy_cfg",
                        lambda: {"cooldown_s": 100, "cooldown_after": 1})
    fp.reset_shared_ledger()
    yield fp
    fp.reset_shared_ledger()


def test_failover_records_failure_into_cooldown_ledger(_policy_window):
    from maverick.provider_failover import failover

    def bad():
        raise RuntimeError("provider down")

    def good():
        return "ok"

    out = failover([("bad-model", bad), ("good-model", good)])
    assert out == "ok"
    led = _policy_window.shared_ledger()
    # The failed model is now cooling (threshold=1); the one that answered isn't.
    assert led.in_cooldown("bad-model") is True
    assert led.in_cooldown("good-model") is False


def test_failover_control_signal_does_not_cool(_policy_window):
    from maverick.provider_failover import failover

    def control_denied():
        raise ValueError("budget exceeded")

    # should_retry=False -> a deliberate control signal, not a provider failure;
    # the model must NOT be cooled for it.
    with pytest.raises(ValueError):
        failover([("m", control_denied)], should_retry=lambda e: False)
    assert _policy_window.shared_ledger().in_cooldown("m") is False


def test_afailover_records_failure_into_cooldown_ledger(_policy_window):
    import asyncio

    from maverick.provider_failover import afailover

    async def bad():
        raise RuntimeError("provider down")

    async def good():
        return "ok"

    out = asyncio.run(afailover([("bad-async", bad), ("good-async", good)]))
    assert out == "ok"
    led = _policy_window.shared_ledger()
    assert led.in_cooldown("bad-async") is True
    assert led.in_cooldown("good-async") is False
