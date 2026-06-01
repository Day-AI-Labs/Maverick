"""Budget must bound the dollar overshoot from concurrent sub-agent calls.

`Budget.check()` only raises once `dollars` ALREADY exceeds `max_dollars`. With a
wide parallel fan-out, N sub-agent calls sharing one budget each pass an
individual check while `dollars` is still low, then collectively overshoot --
a real $2.50-cap run reached $6+ with parallel Opus/Sonnet researchers on
200k-token contexts. `Budget.reserve()/release()` hold each call's projected
cost so concurrent callers see the accumulated holds; the LLM layer reserves
before dispatch and releases once the spend lands.
"""
from __future__ import annotations

import threading

import pytest
from maverick.budget import Budget, BudgetExceeded


def test_check_projected_refuses_call_that_would_exceed_cap():
    b = Budget(max_dollars=1.0)
    b.dollars = 0.9
    with pytest.raises(BudgetExceeded):
        b.check_projected(0.2)   # 0.9 + 0.2 > 1.0
    b.check_projected(0.05)      # 0.9 + 0.05 <= 1.0 -> fine
    b.check_projected(0)         # non-positive est -> no-op


def test_estimate_call_cost_scales_with_input():
    from maverick.llm import _estimate_call_cost
    small = _estimate_call_cost(
        "claude-sonnet-4-6", "sys", [{"role": "user", "content": "hi"}], None, 100)
    big = _estimate_call_cost(
        "claude-sonnet-4-6", "sys", [{"role": "user", "content": "x" * 800_000}], None, 100)
    assert big > small > 0


def test_reserve_bounds_total_holds_to_cap():
    b = Budget(max_dollars=1.0)
    held = []
    for _ in range(5):
        try:
            held.append(b.reserve(0.4))
        except BudgetExceeded:
            pass
    assert len(held) == 2          # 0.4 + 0.4 fit; the third (1.2) is refused
    assert b._reserved == pytest.approx(0.8)
    b.release(held[0])
    assert b._reserved == pytest.approx(0.4)
    b.reserve(0.4)                 # frees up room -> fits again
    assert b._reserved == pytest.approx(0.8)
    b.reserve(0.0)                 # non-positive -> no-op, returns 0
    assert b._reserved == pytest.approx(0.8)


def test_reserve_is_threadsafe_and_bounds_concurrent_holds():
    b = Budget(max_dollars=10.0)
    ok = []
    lk = threading.Lock()

    def worker():
        try:
            h = b.reserve(1.0)
            with lk:
                ok.append(h)
        except BudgetExceeded:
            pass

    ts = [threading.Thread(target=worker) for _ in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # At most 10 holds of $1 fit under a $10 cap -- never more, regardless of
    # how the 50 threads interleaved.
    assert len(ok) == 10
    assert b._reserved == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_complete_async_refuses_overbudget_before_calling_provider(monkeypatch):
    from maverick.llm import LLM
    llm = LLM(model="anthropic:claude-sonnet-4-6")

    class _Client:
        async def complete_async(self, **kw):
            raise AssertionError("provider must NOT be called when the budget refuses")

    monkeypatch.setattr(llm, "_get_client", lambda provider: _Client())
    b = Budget(max_dollars=1.0)
    b.dollars = 0.95
    # ~800k chars -> ~200k input tokens -> ~$0.60 on Sonnet -> projected > cap.
    with pytest.raises(BudgetExceeded):
        await llm.complete_async(
            system="s",
            messages=[{"role": "user", "content": "x" * 800_000}],
            budget=b,
            max_tokens=100,
        )
