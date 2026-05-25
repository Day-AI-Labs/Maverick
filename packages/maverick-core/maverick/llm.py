"""Anthropic adapter — state of the art.

Features:
- Prompt caching on system prompt + tool definitions (ephemeral cache control)
- Extended thinking on demand (orchestrator planning / verification)
- Streaming with progress callbacks
- Per-role model routing (Opus for hard reasoning, Sonnet for workers, Haiku for cheap)
- Vision-ready content blocks (pass image dicts through unchanged)
- Async-friendly: `complete_async` for parallel worker dispatch
- Per-role model choice driven by ``~/.maverick/config.toml`` (see ``maverick.config``)

The ``model_for_role`` function consults user config first and falls back to
``ROLE_MODELS`` defaults below. Future commits add provider dispatch
(OpenAI / OpenRouter / Ollama) by parsing ``provider:model-id`` specs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import anthropic

from .budget import Budget


# Latest Claude family as of 2026-05.
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"

DEFAULT_MODEL = MODEL_SONNET


# Per-role default model picks. Tuned for quality/$ on long-horizon work.
# Users can override any of these via ``[models]`` in their config.toml.
ROLE_MODELS: dict[str, str] = {
    "orchestrator": MODEL_OPUS,    # planning + verify need depth
    "researcher":   MODEL_SONNET,
    "coder":        MODEL_SONNET,
    "writer":       MODEL_SONNET,
    "analyst":      MODEL_SONNET,
    "revisor":      MODEL_OPUS,    # second pass after verify failure
    "summarizer":   MODEL_HAIKU,   # cheap distillation
    "skill_distiller": MODEL_SONNET,
}


# Anthropic pricing per million tokens (2026 list prices, no caching discount).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    MODEL_OPUS:   (15.0, 75.0),
    MODEL_SONNET: (3.0, 15.0),
    MODEL_HAIKU:  (0.80, 4.0),
}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    thinking: Optional[str]
    tool_calls: list[ToolCall]
    stop_reason: str
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    raw: Any = None


def model_for_role(role: str) -> str:
    """Return the model id for a role.

    Resolution order:
      1. User config (``~/.maverick/config.toml`` -> ``[models]``).
         Spec format is ``provider:model-id``; the model-id portion is returned.
      2. ``ROLE_MODELS`` defaults above.
      3. ``DEFAULT_MODEL``.
    """
    try:
        from .config import get_role_model
        spec = get_role_model(role)
        if spec:
            return spec.split(":", 1)[-1]
    except Exception:
        pass
    return ROLE_MODELS.get(role, DEFAULT_MODEL)


def _ephemeral(obj: dict) -> dict:
    return {**obj, "cache_control": {"type": "ephemeral"}}


def _cached_system(text: str) -> list[dict]:
    """Static system prompts are cached. Place dynamic context in messages."""
    return [_ephemeral({"type": "text", "text": text})]


def _cached_tools(tools: list[dict]) -> list[dict]:
    """Cache the tool catalog. The last tool carries the cache breakpoint."""
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = _ephemeral(out[-1])
    return out


class LLM:
    """Sync + async client with caching, thinking, and streaming."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None):
        self.model = model
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
            "model": model or self.model,
            "system": _cached_system(system),
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _cached_tools(tools)
        if thinking_budget and thinking_budget > 0:
            # max_tokens must exceed thinking budget.
            kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        return kwargs

    def _parse_response(self, resp: Any, budget: Optional[Budget]) -> LLMResponse:
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
            budget.record_tokens(usage.input_tokens, usage.output_tokens)

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
            return self._parse_response(resp, budget)

        # Streaming path.
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream.text_stream:
                on_delta(event)
            final = stream.get_final_message()
        return self._parse_response(final, budget)

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
        return self._parse_response(resp, budget)
