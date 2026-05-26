"""Anthropic provider client.

Full implementation: prompt caching on system prompt + tool catalog
(ephemeral cache control), extended thinking on demand, streaming with
progress callbacks, sync + async client.

This is the canonical client; other providers translate to/from its
format.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

import anthropic

from ..budget import Budget
from ..llm import LLMResponse, ToolCall
from ..retry import async_retry, sync_retry


def _ephemeral(obj: dict) -> dict:
    # Anthropic regressed the default cache TTL from 1h to 5m in early
    # March 2026 (issue #46829 on anthropics/claude-code). For agent
    # workloads -- where system prompts and tool catalogs are reused
    # across many turns inside a single goal -- 5m is too short and
    # forces ~20% extra spend on re-creates. Explicitly set 1h on every
    # cache control block so we get the discount we expect.
    ttl = os.environ.get("MAVERICK_ANTHROPIC_CACHE_TTL", "1h")
    return {**obj, "cache_control": {"type": "ephemeral", "ttl": ttl}}


def _cached_system(text: str) -> list[dict]:
    return [_ephemeral({"type": "text", "text": text})]


def _cached_tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = _ephemeral(out[-1])
    return out


def _add_messages_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Mark the last user/tool_result message for caching.

    Wave 10: Anthropic prompt caching caches everything up to AND
    including the marked breakpoint. The system prompt + tools are
    already cached; the third breakpoint slot is best spent on the
    most recent stable turn so multi-turn agent loops (which re-send
    the entire history every step) get cache reads instead of writes
    for the message body. Empirically a 40-55% input cost reduction
    on long tool-use trajectories.

    We mutate the last block of the most recent non-final user message
    to add `cache_control`. Anthropic accepts cache_control on text /
    tool_result / image blocks; we target the last block of any kind.
    """
    if not messages or len(messages) < 2:
        return messages
    # Find the most recent user message that's NOT the final one (the
    # final user message changes every turn -- caching it would write
    # a fresh cache entry every call, the OPPOSITE of what we want).
    target_idx = None
    for i in range(len(messages) - 2, -1, -1):
        if messages[i].get("role") == "user":
            target_idx = i
            break
    if target_idx is None:
        return messages
    msg = messages[target_idx]
    content = msg.get("content")
    if isinstance(content, str):
        # String content: convert to a single text block so we can attach
        # cache_control. Anthropic accepts mixed string + block forms.
        new_content = [{"type": "text", "text": content,
                        "cache_control": {"type": "ephemeral",
                                          "ttl": os.environ.get(
                                              "MAVERICK_ANTHROPIC_CACHE_TTL", "1h")}}]
        new_messages = list(messages)
        new_messages[target_idx] = {**msg, "content": new_content}
        return new_messages
    if isinstance(content, list) and content:
        # Block list: copy + mark the LAST block with cache_control.
        new_blocks = [dict(b) for b in content]
        last = new_blocks[-1]
        last["cache_control"] = {
            "type": "ephemeral",
            "ttl": os.environ.get("MAVERICK_ANTHROPIC_CACHE_TTL", "1h"),
        }
        new_blocks[-1] = last
        new_messages = list(messages)
        new_messages[target_idx] = {**msg, "content": new_blocks}
        return new_messages
    return messages


class AnthropicClient:
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=key)
        self.aclient = anthropic.AsyncAnthropic(api_key=key)

    def _build_request(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]],
        max_tokens: int,
        thinking_budget: Optional[int],
        model: Optional[str],
    ) -> dict[str, Any]:
        # Wave 10: cache the most recent stable user message so repeated
        # tool-use turns hit the cache for the history (40-55% input
        # token cost cut on long trajectories). Toggle via env var so
        # the dashboard can A/B it.
        if os.environ.get("MAVERICK_CACHE_MESSAGES", "1") != "0":
            messages_out = _add_messages_cache_breakpoint(messages)
        else:
            messages_out = messages

        kwargs: dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "system": _cached_system(system),
            "messages": messages_out,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _cached_tools(tools)
        if thinking_budget and thinking_budget > 0:
            kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        # Wave 10 (D1): orchestrator best-of-N sets MAVERICK_TEMPERATURE
        # per attempt to force candidate diversity. Wire it through here
        # so the provider actually honours it -- before this fix the env
        # var was set but read by nothing, and best-of-N produced
        # N identical answers.
        # Thinking models reject explicit temperature; gate on
        # thinking_budget being unset.
        temp_str = os.environ.get("MAVERICK_TEMPERATURE")
        if temp_str and not (thinking_budget and thinking_budget > 0):
            try:
                kwargs["temperature"] = float(temp_str)
            except ValueError:
                pass
        return kwargs

    def _parse_response(
        self,
        resp: Any,
        budget: Optional[Budget],
        model: Optional[str] = None,
    ) -> LLMResponse:
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            t = getattr(block, "type", None)
            if t == "text":
                text_parts.append(block.text)
            elif t == "thinking":
                thinking_parts.append(getattr(block, "thinking", ""))
            elif t == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))

        usage = resp.usage
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

        if budget is not None:
            # ``usage.input_tokens`` is non-cached input only. Cache reads
            # and writes are billed separately at different rates.
            budget.record_tokens(
                usage.input_tokens, usage.output_tokens,
                model=model,
                cache_read_tok=cache_read,
                cache_write_tok=cache_creation,
            )

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            thinking="\n".join(thinking_parts).strip() or None,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            raw=resp,
        )

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse:
        kwargs = self._build_request(system, messages, tools, max_tokens, thinking_budget, model)
        if on_delta is None:
            resp = sync_retry(lambda: self.client.messages.create(**kwargs))
            return self._parse_response(resp, budget, model=kwargs.get("model"))

        # Council finding: wrapping the streaming path in sync_retry
        # would replay every on_delta callback after a mid-stream
        # failure, so consumers see duplicate prefixes. Streaming is
        # called from interactive paths (CLI --stream, dashboard chat);
        # surface the error directly and let the caller retry the
        # higher-level request without partial output.
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream.text_stream:
                on_delta(event)
            final = stream.get_final_message()
        return self._parse_response(final, budget, model=kwargs.get("model"))

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        kwargs = self._build_request(system, messages, tools, max_tokens, thinking_budget, model)
        resp = await async_retry(lambda: self.aclient.messages.create(**kwargs))
        return self._parse_response(resp, budget, model=kwargs.get("model"))
