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
    """Wave 12 hotfix: header policy per Anthropic May 2026 docs.
    Opus 4.7 + Sonnet 4.6 + Haiku 4.5: adaptive thinking is built-in,
    NO header needed (and Opus 4.7 rejects manual `enabled`).
    Sonnet 4.5 / Opus 4.5: header still required to get interleaved.
    """

    def test_header_required_for_sonnet_4_5(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-sonnet-4-5",
        )
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking-2025-05-14" in beta

    def test_header_required_for_opus_4_5(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-opus-4-5",
        )
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking-2025-05-14" in beta

    def test_header_NOT_set_for_sonnet_4_6(self):
        """4.6+ has interleaved automatic in adaptive mode — header would
        be deprecated noise."""
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-sonnet-4-6",
        )
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking" not in beta

    def test_opus_4_7_uses_adaptive_not_enabled(self):
        """Opus 4.7 returns 400 on `thinking={"type":"enabled"}`. We must
        send `adaptive` instead."""
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-opus-4-7",
        )
        thinking = kwargs.get("thinking", {})
        assert thinking.get("type") == "adaptive", (
            f"Opus 4.7 must use adaptive thinking; got {thinking}"
        )
        # No header for 4.7 either.
        beta = kwargs.get("extra_headers", {}).get("anthropic-beta", "")
        assert "interleaved-thinking" not in beta

    def test_opus_4_7_defaults_to_adaptive_even_without_budget(self):
        """Opus 4.7 only supports adaptive — if caller doesn't ask for
        thinking, we still emit adaptive so the model can think when
        it judges it useful."""
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=None,
            model="claude-opus-4-7",
        )
        thinking = kwargs.get("thinking", {})
        assert thinking.get("type") == "adaptive"

    def test_header_not_added_for_legacy_pre_4x_model(self):
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


class TestInterleavedThinkingOrder:
    """May 28 fix: _parse_response must keep the model's ORIGINAL block
    order (thinking interleaved with tool_use) and echo redacted_thinking
    back. Anthropic rejects a rearranged thinking sequence on the next
    request: "thinking blocks in the latest assistant message cannot be
    modified ... must remain as they were in the original response."
    """

    @staticmethod
    def _block(**kw):
        b = type("_Block", (), {})()
        for k, v in kw.items():
            setattr(b, k, v)
        return b

    def test_content_blocks_preserve_interleaved_order(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _Resp:
            usage = None
            stop_reason = "tool_use"

        resp = _Resp()
        resp.content = [
            self._block(type="thinking", thinking="reason A", signature="sigA"),
            self._block(type="tool_use", id="t1", name="shell", input={"cmd": "ls"}),
            self._block(type="redacted_thinking", data="RD=="),
            self._block(type="thinking", thinking="reason B", signature="sigB"),
            self._block(type="tool_use", id="t2", name="read", input={"path": "x"}),
            self._block(type="text", text="done"),
        ]
        out = client._parse_response(resp, None, model="claude-opus-4-7")

        # Original interleaving preserved (the bug hoisted all thinking
        # to the front, producing thinking,thinking,text,tool_use,tool_use).
        types = [b["type"] for b in out.content_blocks]
        assert types == [
            "thinking", "tool_use", "redacted_thinking",
            "thinking", "tool_use", "text",
        ], f"original order not preserved: {types}"
        # Per-block signatures kept.
        assert out.content_blocks[0]["signature"] == "sigA"
        assert out.content_blocks[3]["signature"] == "sigB"
        # redacted_thinking echoed verbatim (was silently dropped before).
        assert out.content_blocks[2] == {"type": "redacted_thinking", "data": "RD=="}
        # Bucketed back-compat fields still populated for other callers.
        assert out.text == "done"
        assert [tc.id for tc in out.tool_calls] == ["t1", "t2"]
        assert [t[0] for t in out.thinking_blocks] == ["reason A", "reason B"]

    def test_thinking_block_without_signature_omits_key(self):
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _Resp:
            usage = None
            stop_reason = "end_turn"

        resp = _Resp()
        resp.content = [
            self._block(type="thinking", thinking="t", signature=None),
            self._block(type="text", text="hi"),
        ]
        out = client._parse_response(resp, None, model="claude-opus-4-7")
        assert "signature" not in out.content_blocks[0]
