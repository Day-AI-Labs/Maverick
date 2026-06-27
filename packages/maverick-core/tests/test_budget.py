"""Budget cap tests."""
from __future__ import annotations

import logging

import maverick.budget as budget_mod
import pytest
from maverick.budget import (
    Budget,
    BudgetExceeded,
    UnpricedModelError,
    _lookup_price,
)


def test_budget_under_caps():
    b = Budget(max_dollars=1.0, max_input_tokens=10_000)
    b.record_tokens(1000, 500)
    assert b.input_tokens == 1000
    assert b.output_tokens == 500
    assert b.dollars < 1.0


def test_budget_input_token_excess():
    b = Budget(max_input_tokens=100)
    with pytest.raises(BudgetExceeded):
        b.record_tokens(200, 0)


def test_budget_output_token_excess():
    b = Budget(max_output_tokens=100)
    with pytest.raises(BudgetExceeded):
        b.record_tokens(0, 200)


def test_budget_tool_call_excess():
    b = Budget(max_tool_calls=2)
    b.record_tool_call()
    b.record_tool_call()
    with pytest.raises(BudgetExceeded):
        b.record_tool_call()


def test_budget_summary_contains_expected_fields():
    b = Budget()
    s = b.summary()
    assert "tokens" in s
    assert "wall" in s
    assert "tools" in s


@pytest.fixture(autouse=True)
def _reset_unpriced_warned():
    saved = set(budget_mod._UNPRICED_WARNED)
    budget_mod._UNPRICED_WARNED.clear()
    yield
    budget_mod._UNPRICED_WARNED.clear()
    budget_mod._UNPRICED_WARNED.update(saved)


def test_known_model_priced_from_table():
    in_rate, out_rate = _lookup_price("claude-sonnet-4-6")
    assert (in_rate, out_rate) == (3.0, 15.0)


def test_unknown_model_warns_once_then_falls_back(monkeypatch, caplog):
    monkeypatch.delenv("MAVERICK_BILLING_STRICT", raising=False)
    monkeypatch.setattr("maverick.config.get_budget_overrides", dict)
    with caplog.at_level(logging.WARNING, logger="maverick.budget"):
        first = _lookup_price("totally-made-up-model")
        second = _lookup_price("totally-made-up-model")
    assert first == second == (3.0, 15.0)  # documented Sonnet fallback estimate
    unpriced = [r for r in caplog.records if "no verified price" in r.getMessage()]
    assert len(unpriced) == 1  # warned once, not per call


def test_none_model_does_not_warn(monkeypatch, caplog):
    monkeypatch.delenv("MAVERICK_BILLING_STRICT", raising=False)
    with caplog.at_level(logging.WARNING, logger="maverick.budget"):
        assert _lookup_price(None) == (3.0, 15.0)
    assert not [r for r in caplog.records if "no verified price" in r.getMessage()]


def test_strict_pricing_raises_on_unknown_model(monkeypatch):
    monkeypatch.setenv("MAVERICK_BILLING_STRICT", "1")
    with pytest.raises(UnpricedModelError, match="no verified price"):
        _lookup_price("totally-made-up-model")


def test_strict_pricing_allows_known_and_selfhosted(monkeypatch):
    monkeypatch.setenv("MAVERICK_BILLING_STRICT", "1")
    # A table model is fine.
    assert _lookup_price("claude-sonnet-4-6") == (3.0, 15.0)
    # A self-hosted ($0) model is priced, not refused.
    assert _lookup_price("ollama:llama-4-maverick") == (0.0, 0.0)


def test_strict_pricing_via_config(monkeypatch):
    monkeypatch.delenv("MAVERICK_BILLING_STRICT", raising=False)
    monkeypatch.setattr("maverick.config.get_budget_overrides",
                        lambda: {"strict_pricing": True})
    with pytest.raises(UnpricedModelError):
        _lookup_price("totally-made-up-model")


def test_cache_hit_rate_consolidates_across_providers():
    b = Budget(max_dollars=1000.0, max_input_tokens=10_000_000)
    # No traffic yet -> 0.0, never divides by zero.
    assert b.cache_hit_rate() == 0.0
    # 200 billable input + 800 cache-read => 80% served from cache.
    b.record_tokens(200, 10, cache_read_tok=800)
    assert b.cache_hit_rate() == 0.8
    stats = b.cache_stats()
    assert stats["cache_read_tokens"] == 800
    assert stats["billable_input_tokens"] == 200
    assert stats["hit_rate"] == 0.8
    assert "hit_rate" in b.summary()
