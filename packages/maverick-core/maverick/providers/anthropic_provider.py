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


def _ephemeral(obj: dict) -> dict:
    return {**obj, "cache_control": {"type": "ephemeral"}}


def _cached_system(text: str) -> list[dict]:
    return [_ephemeral({"type": "text", "text": text})]


def _cached_tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = _ephemeral(out[-1])
    return out


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
        kwargs: dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "system": _cached_system(system),
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _cached_tools(tools)
        if thinking_budget and thinking_budget > 0:
            kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
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
            resp = self.client.messages.create(**kwargs)
            return self._parse_response(resp, budget, model=kwargs.get("model"))
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
        resp = await self.aclient.messages.create(**kwargs)
        return self._parse_response(resp, budget, model=kwargs.get("model"))
