"""Audit round 11: _response_call_cost overpriced OpenAI-family cache hits.

OpenAI-compatible usage folds cached-prompt tokens INTO ``prompt_tokens`` and the
provider doesn't surface them on the LLMResponse, so _response_call_cost (which
feeds provider-health routing + the budget_dollars metric) priced the full,
cache-inclusive prompt at the full input rate -- no discount. The real billing
path (Budget.record_tokens) already splits billable_in = prompt - cached and
prices the cached part at 0.5x; this brings the metrics path in line.

(Anthropic's input_tokens already excludes cache reads, which ride on the
response as cache_read_tokens, so that path is unaffected.)
"""
from __future__ import annotations

import pytest
from maverick.llm import _response_call_cost


class _Details:
    def __init__(self, cached):
        self.cached_tokens = cached


class _UsageOpenAI:
    def __init__(self, prompt, completion, cached):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = _Details(cached)


class _UsageDeepSeek:
    def __init__(self, prompt, completion, cache_hit):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_cache_hit_tokens = cache_hit


class _UsageAnthropic:
    def __init__(self, inp, out):
        self.input_tokens = inp
        self.output_tokens = out


class _Raw:
    def __init__(self, usage):
        self.usage = usage


class _Resp:
    def __init__(self, usage, *, cache_read=0, cache_creation=0):
        self.raw = _Raw(usage)
        self.cache_read_tokens = cache_read
        self.cache_creation_tokens = cache_creation


def test_openai_cache_hit_is_discounted_not_full_rate():
    # gpt-5.4 = (3.0 in, 12.0 out) per Mtok. 100k prompt of which 80k cached.
    resp = _Resp(_UsageOpenAI(prompt=100_000, completion=1_000, cached=80_000))
    cost = _response_call_cost("gpt-5.4", resp)
    # billable 20k @ $3 + cached 80k @ $3*0.5 + 1k out @ $12.
    expected = (20_000 / 1e6) * 3.0 + (80_000 / 1e6) * 3.0 * 0.5 + (1_000 / 1e6) * 12.0
    assert cost == pytest.approx(expected, rel=1e-9)
    # And strictly cheaper than the old no-discount pricing of the full prompt.
    no_discount = (100_000 / 1e6) * 3.0 + (1_000 / 1e6) * 12.0
    assert cost < no_discount


def test_deepseek_prompt_cache_hit_tokens_discounted():
    # deepseek-chat = (0.27, 1.10). prompt_cache_hit_tokens path (no details obj).
    resp = _Resp(_UsageDeepSeek(prompt=50_000, completion=500, cache_hit=40_000))
    cost = _response_call_cost("deepseek-chat", resp)
    expected = (10_000 / 1e6) * 0.27 + (40_000 / 1e6) * 0.27 * 0.5 + (500 / 1e6) * 1.10
    assert cost == pytest.approx(expected, rel=1e-9)


def test_no_cache_is_plain_full_rate():
    resp = _Resp(_UsageOpenAI(prompt=10_000, completion=2_000, cached=0))
    cost = _response_call_cost("gpt-5.4", resp)
    expected = (10_000 / 1e6) * 3.0 + (2_000 / 1e6) * 12.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_anthropic_path_unaffected():
    # input_tokens already excludes cache reads; cache_read rides on the response
    # at 0.1x. The OpenAI split must NOT engage (cache_read != 0).
    resp = _Resp(_UsageAnthropic(inp=30_000, out=3_000), cache_read=50_000)
    cost = _response_call_cost("claude-sonnet-4-6", resp)  # (3.0, 15.0)
    expected = (30_000 / 1e6) * 3.0 + (50_000 / 1e6) * 3.0 * 0.1 + (3_000 / 1e6) * 15.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_anthropic_cache_write_priced_at_configured_ttl(monkeypatch):
    # Audit (llm unit): cache_creation_tokens are surfaced only by the Anthropic
    # provider, which writes breakpoints at the configured TTL. The interactive
    # default is "1h" (2.0x write surcharge) -- the authoritative
    # Budget.record_tokens bills it at 2.0x. _response_call_cost previously
    # hardcoded the 5m 1.25x rate, under-counting 1h cache-write spend by ~37.5%
    # in the cross-run provider-cap ledger. Force the interactive default TTL.
    monkeypatch.delenv("MAVERICK_ANTHROPIC_CACHE_TTL", raising=False)
    monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)  # -> "1h"
    resp = _Resp(_UsageAnthropic(inp=1_000, out=100), cache_creation=2_000_000)
    cost = _response_call_cost("claude-opus-4-8", resp)  # (5.0, 25.0)
    # 1h TTL bills cache writes at 2.0x, not 1.25x.
    expected = (
        (1_000 / 1e6) * 5.0
        + (2_000_000 / 1e6) * 5.0 * 2.0  # cache write @ 1h surcharge
        + (100 / 1e6) * 25.0
    )
    assert cost == pytest.approx(expected, rel=1e-9)
    # Guard against the old 1.25x-everywhere behaviour.
    wrong = (
        (1_000 / 1e6) * 5.0
        + (2_000_000 / 1e6) * 5.0 * 1.25
        + (100 / 1e6) * 25.0
    )
    assert cost != pytest.approx(wrong, rel=1e-9)


def test_anthropic_cache_write_respects_explicit_5m_ttl(monkeypatch):
    # An explicit 5m TTL override must still price writes at 1.25x.
    monkeypatch.setenv("MAVERICK_ANTHROPIC_CACHE_TTL", "5m")
    resp = _Resp(_UsageAnthropic(inp=1_000, out=100), cache_creation=2_000_000)
    cost = _response_call_cost("claude-opus-4-8", resp)  # (5.0, 25.0)
    expected = (
        (1_000 / 1e6) * 5.0
        + (2_000_000 / 1e6) * 5.0 * 1.25  # cache write @ 5m surcharge
        + (100 / 1e6) * 25.0
    )
    assert cost == pytest.approx(expected, rel=1e-9)
