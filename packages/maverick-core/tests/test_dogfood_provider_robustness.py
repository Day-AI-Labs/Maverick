"""Provider/budget robustness fixes surfaced by dogfooding.

1. `record_tokens` must preserve null-safety for missing counts, but
   NaN/Inf/garbage usage from a paid provider response must fail closed instead
   of being silently accounted as zero-cost usage.

2. The Anthropic temperature gate must key off whether `thinking` is actually
   in the request, not off `thinking_budget`. Opus 4.7/4.8 auto-inject adaptive
   thinking with `thinking_budget=None`; the old gate then let `temperature`
   through and the API 400'd ("thinking models reject temperature").
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from maverick.budget import Budget, BudgetExceeded, _coerce_count


def test_coerce_count_handles_none_and_valid_counts() -> None:
    assert _coerce_count(None) == 0
    assert _coerce_count(0) == 0
    assert _coerce_count(3.9) == 3         # finite float truncates
    assert _coerce_count(7) == 7


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "not a number", -5])
def test_coerce_count_fails_closed_on_invalid_counts(bad) -> None:
    with pytest.raises(BudgetExceeded, match="invalid token usage count"):
        _coerce_count(bad)


def test_record_tokens_survives_none_usage_counts() -> None:
    b = Budget(max_dollars=1.0)
    # None remains a tolerated missing count, and must not corrupt totals.
    b.record_tokens(
        None, None,
        model="claude-haiku-4-5",
        cache_read_tok=None, cache_write_tok=None,
    )
    assert b.dollars == 0.0
    assert b.input_tokens == 0 and b.output_tokens == 0
    # A normal call after a missing-count one still accounts correctly.
    b.record_tokens(1_000_000, 0, model="claude-haiku-4-5")
    assert b.dollars > 0.0


@pytest.mark.parametrize("kwargs", [
    {"in_tok": float("nan"), "out_tok": 0},
    {"in_tok": 0, "out_tok": float("inf")},
    {"in_tok": 0, "out_tok": 0, "cache_read_tok": "bad-cache"},
    {"in_tok": 0, "out_tok": 0, "cache_write_tok": -1},
])
def test_record_tokens_fails_closed_on_invalid_usage_counts(kwargs) -> None:
    b = Budget(max_dollars=1.0)

    with pytest.raises(BudgetExceeded, match="invalid token usage count"):
        b.record_tokens(model="claude-haiku-4-5", **kwargs)

    assert b.dollars == 0.0
    assert b.input_tokens == 0 and b.output_tokens == 0


def _openai_response_with_usage(**usage_fields):
    choice = SimpleNamespace(
        message=SimpleNamespace(content="hi", tool_calls=None),
        finish_reason="stop",
    )
    usage = SimpleNamespace(**usage_fields)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_openai_provider_fails_closed_on_malformed_usage() -> None:
    from maverick.providers.openai_provider import OpenAIClient

    b = Budget(max_dollars=1.0)
    resp = _openai_response_with_usage(
        prompt_tokens=float("nan"),
        completion_tokens=float("inf"),
        prompt_tokens_details=SimpleNamespace(cached_tokens="bad-cache"),
    )

    with pytest.raises(BudgetExceeded, match="invalid OpenAI usage"):
        OpenAIClient._from_response(resp, b, model="gpt-5.4")

    assert b.input_tokens == 0
    assert b.output_tokens == 0
    assert b.cache_read_tokens == 0
    assert b.dollars == 0.0


def test_openai_provider_fails_closed_when_usage_missing() -> None:
    from maverick.providers.openai_provider import OpenAIClient

    b = Budget(max_dollars=1.0)
    resp = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="hi", tool_calls=None),
            finish_reason="stop",
        )],
        usage=None,
    )

    with pytest.raises(BudgetExceeded, match="missing token usage"):
        OpenAIClient._from_response(resp, b, model="gpt-5.4")

    assert b.dollars == 0.0


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


def _kwargs_ctx(model: str, *, thinking_budget, temp):
    from maverick.providers.base import (
        reset_sampling_temperature,
        set_sampling_temperature,
    )
    tok = set_sampling_temperature(temp)
    try:
        return _client()._build_request(
            system="s", messages=[{"role": "user", "content": "hi"}],
            tools=None, max_tokens=1024, thinking_budget=thinking_budget, model=model,
        )
    finally:
        reset_sampling_temperature(tok)


def test_temperature_from_contextvar_applied_without_thinking() -> None:
    # best-of-N now sets the per-attempt temperature via a ContextVar (race-free
    # across concurrent goals), not os.environ.
    k = _kwargs_ctx("claude-haiku-4-5", thinking_budget=None, temp=0.85)
    assert "thinking" not in k
    assert k.get("temperature") == 0.85


def test_contextvar_temperature_takes_precedence_over_env(monkeypatch) -> None:
    monkeypatch.setenv("MAVERICK_TEMPERATURE", "0.1")
    from maverick.providers.base import (
        reset_sampling_temperature,
        set_sampling_temperature,
    )
    tok = set_sampling_temperature(0.85)
    try:
        k = _client()._build_request(
            system="s", messages=[{"role": "user", "content": "hi"}],
            tools=None, max_tokens=1024, thinking_budget=None, model="claude-haiku-4-5",
        )
    finally:
        reset_sampling_temperature(tok)
    assert k.get("temperature") == 0.85   # contextvar wins over the env fallback


def test_contextvar_temperature_dropped_when_thinking_active() -> None:
    k = _kwargs_ctx("claude-opus-4-8", thinking_budget=None, temp=0.9)
    assert k.get("thinking") == {"type": "adaptive"}
    assert "temperature" not in k
