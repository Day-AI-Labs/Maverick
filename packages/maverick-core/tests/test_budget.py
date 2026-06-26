"""Budget cap tests."""
from __future__ import annotations

import pytest
from maverick.budget import Budget, BudgetExceeded


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
