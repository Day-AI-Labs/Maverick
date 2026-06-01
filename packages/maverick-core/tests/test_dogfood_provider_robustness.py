"""Provider/budget robustness fixes surfaced by dogfooding.

1. `record_tokens` must never crash on a NaN/Inf/None usage count. A flaky
   OpenAI-compatible gateway can return non-finite values in `usage`;
   `int(float("nan") or 0)` RAISES (NaN is truthy), which discarded the
   already-billed response and recorded $0 spent.

2. The Anthropic temperature gate must key off whether `thinking` is actually
   in the request, not off `thinking_budget`. Opus 4.7/4.8 auto-inject adaptive
   thinking with `thinking_budget=None`; the old gate then let `temperature`
   through and the API 400'd ("thinking models reject temperature").
"""
from __future__ import annotations

import os

from maverick.budget import Budget, _coerce_count


def test_coerce_count_handles_non_finite_and_garbage() -> None:
    assert _coerce_count(float("nan")) == 0
    assert _coerce_count(float("inf")) == 0
    assert _coerce_count(float("-inf")) == 0
    assert _coerce_count(None) == 0
    assert _coerce_count("not a number") == 0
    assert _coerce_count(-5) == 0          # counts are non-negative
    assert _coerce_count(3.9) == 3         # finite float truncates
    assert _coerce_count(7) == 7


def test_record_tokens_survives_nan_inf_none() -> None:
    b = Budget(max_dollars=1.0)
    # Must not raise, and must not corrupt the running total.
    b.record_tokens(
        float("nan"), float("inf"),
        model="claude-haiku-4-5",
        cache_read_tok=None, cache_write_tok=float("nan"),
    )
    assert b.dollars == 0.0
    assert b.input_tokens == 0 and b.output_tokens == 0
    # A normal call after a poisoned one still accounts correctly.
    b.record_tokens(1_000_000, 0, model="claude-haiku-4-5")
    assert b.dollars > 0.0


def _client():
    from maverick.providers.anthropic_provider import AnthropicClient
    return AnthropicClient.__new__(AnthropicClient)

def _kwargs(model: str, *, thinking_budget, temp: str):
    os.environ["MAVERICK_TEMPERATURE"] = temp
    try:
        return _client()._build_request(
            system="s", messages=[{"role": "user", "content": "hi"}],
            tools=None, max_tokens=1024, thinking_budget=thinking_budget, model=model,
        )
    finally:
        os.environ.pop("MAVERICK_TEMPERATURE", None)


def test_temperature_dropped_when_thinking_active_opus_default() -> None:
    # Opus 4.8 with no explicit budget auto-injects adaptive thinking; sending
    # temperature alongside it is a 400.
    k = _kwargs("claude-opus-4-8", thinking_budget=None, temp="0.9")
    assert k.get("thinking") == {"type": "adaptive"}
    assert "temperature" not in k


def test_temperature_applied_without_thinking() -> None:
    # A non-thinking model still honors MAVERICK_TEMPERATURE (best-of-N diversity).
    k = _kwargs("claude-haiku-4-5", thinking_budget=None, temp="0.9")
    assert "thinking" not in k
    assert k.get("temperature") == 0.9
