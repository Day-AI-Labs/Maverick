"""Wave 12 (council F13): Anthropic API fixes.

  - F13a: cache TTL must be consistent across system/tools/messages
    breakpoints (was hardcoded "1h" for messages).
  - F13b: interleaved-thinking beta header set when thinking enabled.
  - F13c: nullsafe usage.input_tokens / output_tokens.
  - F13d: tools[] sorted before sending for deterministic cache key.
"""
from __future__ import annotations


class TestCacheTtlConsistent:
    def test_messages_breakpoint_uses_default_ttl_5m_in_coding(self, monkeypatch):
        from maverick.providers.anthropic_provider import (
            _add_messages_cache_breakpoint,
        )
        monkeypatch.delenv("MAVERICK_ANTHROPIC_CACHE_TTL", raising=False)
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        msgs = [
            {"role": "user", "content": "first turn"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second turn"},
        ]
        out = _add_messages_cache_breakpoint(msgs)
        # The first user message gets the breakpoint.
        target = out[0]
        cc = target["content"][0]["cache_control"]
        assert cc["ttl"] == "5m", (
            "in coding mode the messages breakpoint should also be 5m, "
            "matching system/tools — prior code hardcoded 1h here, "
            "causing Budget over-bill on write surcharge"
        )

    def test_messages_breakpoint_uses_1h_in_normal_mode(self, monkeypatch):
        from maverick.providers.anthropic_provider import (
            _add_messages_cache_breakpoint,
        )
        monkeypatch.delenv("MAVERICK_ANTHROPIC_CACHE_TTL", raising=False)
        monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "second"},
        ]
        out = _add_messages_cache_breakpoint(msgs)
        cc = out[0]["content"][0]["cache_control"]
        assert cc["ttl"] == "1h"

    def test_explicit_env_var_wins(self, monkeypatch):
        from maverick.providers.anthropic_provider import (
            _add_messages_cache_breakpoint,
        )
        monkeypatch.setenv("MAVERICK_ANTHROPIC_CACHE_TTL", "1h")
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")  # would default to 5m
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ]
        out = _add_messages_cache_breakpoint(msgs)
        cc = out[0]["content"][0]["cache_control"]
        assert cc["ttl"] == "1h"


class TestToolsSorted:
    def test_tools_sorted_for_cache_determinism(self):
        from maverick.providers.anthropic_provider import _cached_tools
        tools = [
            {"name": "zebra", "input_schema": {}},
            {"name": "apple", "input_schema": {}},
            {"name": "mango", "input_schema": {}},
        ]
        out = _cached_tools(tools)
        names = [t["name"] for t in out]
        assert names == ["apple", "mango", "zebra"]

    def test_tools_sort_is_stable_across_calls(self):
        from maverick.providers.anthropic_provider import _cached_tools
        a = [{"name": "x"}, {"name": "y"}, {"name": "z"}]
        b = [{"name": "z"}, {"name": "y"}, {"name": "x"}]
        # Same input set, different order → same canonical output.
        ax = _cached_tools(a)
        bx = _cached_tools(b)
        assert [t["name"] for t in ax] == [t["name"] for t in bx]

    def test_last_tool_after_sort_gets_cache_control(self):
        from maverick.providers.anthropic_provider import _cached_tools
        tools = [
            {"name": "zebra"},
            {"name": "apple"},
        ]
        out = _cached_tools(tools)
        # After sort, last is "zebra" — must carry the cache breakpoint.
        assert out[-1]["name"] == "zebra"
        assert "cache_control" in out[-1]
        # Earlier ones don't have it.
        assert "cache_control" not in out[0]


class TestInterleavedThinkingHeader:
    def test_header_added_when_thinking_enabled(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        # Construct without making a real network call; only need
        # _build_request.
        client = AnthropicClient.__new__(AnthropicClient)
        # _build_request doesn't touch self.client/aclient.
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-sonnet-4-6",
        )
        assert "extra_headers" in kwargs
        beta = kwargs["extra_headers"].get("anthropic-beta", "")
        assert "interleaved-thinking-2025-05-14" in beta

    def test_header_added_for_opus_sonnet4_without_explicit_budget(self):
        """Wave 12 hardening: the header is added whenever the model is
        in a thinking-capable family (Opus 4.x, Sonnet 4.x), even when
        the caller doesn't pass thinking_budget. Without this, Opus
        runs default — which use thinking — were missing the beta."""
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=None,
            model="claude-sonnet-4-6",
        )
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking-2025-05-14" in beta

    def test_header_not_added_for_legacy_model(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=None,
            model="claude-3-5-sonnet-20241022",
        )
        # Legacy model (pre-4.x family) — no thinking support, no header.
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking" not in beta


class TestNullsafeUsage:
    def test_record_handles_none_usage_fields(self, monkeypatch):
        """If Anthropic returns None in usage fields (streaming refusal),
        _parse_response must not crash."""
        from maverick.budget import Budget
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _FakeUsage:
            input_tokens = None
            output_tokens = None
            cache_creation_input_tokens = None
            cache_read_input_tokens = None

        class _FakeResp:
            content = []
            usage = _FakeUsage()
            stop_reason = "end_turn"

        budget = Budget(max_dollars=10.0)
        resp = client._parse_response(_FakeResp(), budget, model="claude-sonnet-4-6")
        # Should not raise; budget records 0 spend.
        assert budget.dollars == 0.0
        assert resp.text == ""
