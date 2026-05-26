"""Per-model + cache-aware budget pricing.

The v0.1.x Budget hardcoded Sonnet pricing for every call. An Opus run
under max_dollars=5 let ~$25 of real spend through; Anthropic cache
read tokens were billed at full price (overcharging readers 10x) while
cache writes were billed at base rate (undercharging by 25%). These
tests pin the corrected math.
"""
from __future__ import annotations

from maverick.budget import Budget
from maverick.llm import MODEL_OPUS, MODEL_SONNET, MODEL_HAIKU


def test_opus_priced_at_opus_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M input + 1M output on Opus 4.7 (May 2026) = $5 in + $25 out = $30
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_OPUS)
    assert abs(b.dollars - 30.0) < 0.001


def test_sonnet_priced_at_sonnet_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M input + 1M output on Sonnet = $3 in + $15 out = $18
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_SONNET)
    assert abs(b.dollars - 18.0) < 0.001


def test_haiku_priced_at_haiku_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M input + 1M output on Haiku = $0.80 in + $4 out = $4.80
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_HAIKU)
    assert abs(b.dollars - 4.80) < 0.001


def test_unknown_model_falls_back_to_sonnet_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    b.record_tokens(1_000_000, 0, model="provider:unknown-future-model")
    # Sonnet input rate = $3
    assert abs(b.dollars - 3.0) < 0.001


def test_no_model_uses_fallback_rate():
    """Back-compat: callers that don't pass model get the legacy rate."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    b.record_tokens(1_000_000, 0)
    assert abs(b.dollars - 3.0) < 0.001


def test_cache_read_is_one_tenth_of_input():
    """Anthropic bills cache reads at 0.1x of input rate."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M cache reads on Opus 4.7 = $5 * 0.1 = $0.50
    b.record_tokens(0, 0, model=MODEL_OPUS, cache_read_tok=1_000_000)
    assert abs(b.dollars - 0.50) < 0.001


def test_cache_write_is_one_and_a_quarter_input():
    """Anthropic bills cache writes at 1.25x of input rate."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M cache writes on Sonnet = $3 * 1.25 = $3.75
    b.record_tokens(0, 0, model=MODEL_SONNET, cache_write_tok=1_000_000)
    assert abs(b.dollars - 3.75) < 0.001


def test_cache_tokens_tracked_separately_from_input_cap():
    """max_input_tokens measures BILLABLE input only — cache reads/writes
    have their own counters. A heavy-caching workload should not be
    prematurely cap-killed for tokens it's getting at 0.1x rate."""
    b = Budget(max_dollars=100.0, max_input_tokens=2_500_000)
    b.record_tokens(
        1_000_000, 0, model=MODEL_SONNET,
        cache_read_tok=1_000_000, cache_write_tok=500_000,
    )
    assert b.input_tokens == 1_000_000
    assert b.cache_read_tokens == 1_000_000
    assert b.cache_write_tokens == 500_000


def test_opus_run_actually_hits_the_dollar_cap():
    """The whole point of the fix: an Opus call past max_dollars must raise."""
    import pytest
    from maverick.budget import BudgetExceeded
    b = Budget(max_dollars=5.0)
    # 1.5M input on Opus 4.7 = $5 * 1.5 = $7.50 -- should exceed $5 cap.
    with pytest.raises(BudgetExceeded):
        b.record_tokens(1_500_000, 0, model=MODEL_OPUS)
