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
    b = Budget(max_dollars=200.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # Wave 12 fix: Opus 4.7 May 2026 list = $15 in + $75 out per Mtok.
    # 1M input + 1M output = $15 + $75 = $90 (was 3x under-billed at $30
    # while the file claimed (5.0, 25.0)).
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_OPUS)
    assert abs(b.dollars - 90.0) < 0.001


def test_sonnet_priced_at_sonnet_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M input + 1M output on Sonnet = $3 in + $15 out = $18
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_SONNET)
    assert abs(b.dollars - 18.0) < 0.001


def test_haiku_priced_at_haiku_rate():
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # Wave 12 fix: Haiku 4.5 May 2026 list = $1.00 in + $5.00 out per Mtok.
    # 1M input + 1M output = $1 + $5 = $6 (was under-reported at $4.80
    # while the file claimed (0.80, 4.0)).
    b.record_tokens(1_000_000, 1_000_000, model=MODEL_HAIKU)
    assert abs(b.dollars - 6.0) < 0.001


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
    # 1M cache reads on Opus 4.7 = $15 * 0.1 = $1.50
    b.record_tokens(0, 0, model=MODEL_OPUS, cache_read_tok=1_000_000)
    assert abs(b.dollars - 1.5) < 0.001


def test_cache_write_5m_is_one_and_a_quarter_input():
    """Anthropic bills 5m-TTL cache writes at 1.25x of input rate."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M cache writes on Sonnet = $3 * 1.25 = $3.75
    b.record_tokens(0, 0, model=MODEL_SONNET, cache_write_tok=1_000_000)
    assert abs(b.dollars - 3.75) < 0.001


def test_cache_write_1h_is_two_x_input():
    """Wave 12: Anthropic bills 1h-TTL cache writes at 2.0x (not 1.25x)."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # 1M cache writes on Sonnet at 1h = $3 * 2.0 = $6.00
    b.record_tokens(
        0, 0, model=MODEL_SONNET,
        cache_write_tok=1_000_000, cache_write_ttl="1h",
    )
    assert abs(b.dollars - 6.0) < 0.001


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
    # Wave 12: 0.5M input on Opus 4.7 @ $15/Mtok = $7.50 -- should exceed $5 cap.
    with pytest.raises(BudgetExceeded):
        b.record_tokens(500_000, 0, model=MODEL_OPUS)


def test_nullsafe_record_tokens_handles_none():
    """Wave 12: Anthropic occasionally returns None in usage on streaming
    refusals. The prior code raised TypeError and the instance counted
    as $0 spent (silent under-bill)."""
    b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
    # Should not raise even though both tokens are None.
    b.record_tokens(None, None, model=MODEL_SONNET)  # type: ignore[arg-type]
    assert b.dollars == 0.0
    assert b.input_tokens == 0
    assert b.output_tokens == 0


def test_wall_clock_uses_monotonic_clock():
    """Wave 12: budget.elapsed() must use a monotonic clock so NTP jumps
    don't bypass max_wall_seconds."""
    import time
    b = Budget(max_dollars=5.0, max_wall_seconds=3600.0)
    # elapsed() must be >= 0 even if wall clock has jumped backward.
    # Hard to simulate NTP jump in a unit test, but at least ensure the
    # implementation exists and returns sensible numbers.
    elapsed1 = b.elapsed()
    time.sleep(0.01)
    elapsed2 = b.elapsed()
    assert elapsed2 >= elapsed1
    assert elapsed1 >= 0.0


def test_record_tokens_thread_safe():
    """Wave 12 (council F12b): concurrent record_tokens calls must not
    lose updates. Without the lock, `self.dollars += ...` races and
    silently undercounts (it's a load-then-store, not atomic)."""
    import threading
    from maverick.llm import MODEL_SONNET

    b = Budget(
        max_dollars=1000.0,
        max_input_tokens=100_000_000,
        max_output_tokens=100_000_000,
        max_tool_calls=100_000,
    )

    def worker():
        for _ in range(100):
            b.record_tokens(1000, 100, model=MODEL_SONNET)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 8 threads × 100 iterations × 1000 input tokens = 800_000 input tokens.
    assert b.input_tokens == 800_000, (
        f"input_tokens race detected: expected 800000, got {b.input_tokens}"
    )
    # 8 × 100 × 100 = 80_000 output tokens.
    assert b.output_tokens == 80_000


def test_record_tool_call_thread_safe():
    import threading
    b = Budget(max_dollars=100.0, max_tool_calls=100_000)

    def worker():
        for _ in range(500):
            b.record_tool_call()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert b.tool_calls == 2_000
