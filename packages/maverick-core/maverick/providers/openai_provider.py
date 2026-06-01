"""OpenAI provider client.

Implements the same complete()/complete_async() interface as
AnthropicClient, by translating Anthropic-format messages and tools
into OpenAI's chat format and converting the response back.

Used directly for OpenAI; subclassed by OpenRouter and Ollama, which
are OpenAI-compatible at different base_urls.

v0.1.1 fixes (per council review):
  - tool_result.content may be a list of blocks; extract `text` from each
  - max_completion_tokens for gpt-4o / o1 / o3 (max_tokens deprecated)
  - finish_reason mapped to Anthropic stop_reason vocabulary
  - empty assistant turns emit content="" not None (OpenAI rejects null)
  - missing tool_call_id matches: stub responses so the API doesn't 400
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from ..budget import Budget
from ..llm import LLMResponse, ToolCall
from ..retry import async_retry, sync_retry

log = logging.getLogger(__name__)


# Models that require max_completion_tokens instead of max_tokens.
_MODELS_WANTING_MAX_COMPLETION_TOKENS = (
    "gpt-4o", "gpt-4.1", "o1", "o3", "o4", "gpt-5",
)

# Models with OpenAI automatic prompt caching (gpt-4.1 / o-series / gpt-5).
# The read side already credits usage.prompt_tokens_details.cached_tokens;
# these get the write-side cache-friendly ordering below.
_MODELS_WITH_AUTO_PROMPT_CACHE = (
    "gpt-4.1", "o1", "o3", "o4", "gpt-5",
)

# OpenAI's automatic prompt cache only engages when the stable prefix is
# at least ~1024 tokens. Below this it's a no-op, so the reordering work
# isn't worth doing. Heuristic estimate: 4 chars/token (matches the
# Anthropic provider's estimator).
_MIN_AUTO_CACHE_TOKENS = 1024

# Map OpenAI finish_reason to Anthropic stop_reason vocab.
_FINISH_REASON_MAP = {
    "stop":         "end_turn",
    "tool_calls":   "tool_use",
    "length":       "max_tokens",
    "content_filter": "refusal",
    "function_call": "tool_use",
}


def _extract_tool_result_text(content: Any) -> str:
    """Anthropic's tool_result.content can be a string OR a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content) if content is not None else ""


class OpenAIClient:
    DEFAULT_MODEL = "gpt-4o"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        allow_openai_env_fallback: bool = True,
    ):
        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. Run: pip install 'maverick-agent[openai]'"
            ) from e
        key = api_key
        if key is None and allow_openai_env_fallback:
            key = os.environ.get("OPENAI_API_KEY")
        # Strip whitespace: a trailing newline (`echo $KEY > file`) or stray
        # spaces otherwise 401 every call. Covers every OpenAI-compatible
        # provider (openrouter/deepseek/ollama/moonshot/xai/tgi/vllm), which
        # all pass their key through here. Matches AnthropicClient.
        if key is not None:
            key = key.strip() or None
        if key is None and not allow_openai_env_fallback:
            raise RuntimeError(
                "OpenAI-compatible provider requires a non-empty API key; "
                "refusing to fall back to OPENAI_API_KEY for this base_url."
            )
        from .base import llm_http_timeout
        kw: dict = {"api_key": key, "base_url": base_url}
        timeout = llm_http_timeout()
        if timeout is not None:
            kw["timeout"] = timeout
        self._sync = OpenAI(**kw)
        self._async = AsyncOpenAI(**kw)
        # Expose the resolved endpoint for introspection (doctor / logs) and so
        # the OpenAI-compatible subclasses (vllm / tgi / bedrock /
        # openai_compatible) and their tests can read where they're actually
        # pointed. ``None`` means the OpenAI SDK's own default base_url.
        self.base_url = base_url

    @staticmethod
    def _wants_max_completion(model: str) -> bool:
        return any(model.startswith(prefix) for prefix in _MODELS_WANTING_MAX_COMPLETION_TOKENS)

    @staticmethod
    def _has_auto_prompt_cache(model: str) -> bool:
        return any(model.startswith(prefix) for prefix in _MODELS_WITH_AUTO_PROMPT_CACHE)

    @staticmethod
    def _cache_friendly_tools(tools: list[dict] | None) -> list[dict] | None:
        """Stable tool ordering for OpenAI's automatic prompt cache.

        OpenAI auto-caches the longest common prefix of a request (system
        + tools + leading messages). The tools array is part of that
        prefix, so a non-deterministic order silently busts the cache on
        every call. Sorting by name makes the prefix byte-identical across
        calls so the cache actually hits — same reasoning as the Anthropic
        provider's ``_cached_tools``. Coerce the key via str() so a
        malformed tool name=None doesn't blow sorted() with TypeError.
        """
        if not tools:
            return tools
        return sorted(tools, key=lambda t: str(t.get("name") or ""))

    @staticmethod
    def _to_openai_messages(system: str, anthropic_messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for msg in anthropic_messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "user":
                if isinstance(content, str):
                    out.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    # Two passes preserves block order in the resulting messages.
                    text_buf: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            text_buf.append(str(block))
                            continue
                        bt = block.get("type")
                        if bt == "tool_result":
                            # Flush any buffered text first.
                            if text_buf:
                                out.append({"role": "user", "content": "\n".join(text_buf)})
                                text_buf = []
                            out.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": _extract_tool_result_text(block.get("content")),
                            })
                        elif bt == "text":
                            text_buf.append(block.get("text", ""))
                        else:
                            text_buf.append(str(block))
                    if text_buf:
                        out.append({"role": "user", "content": "\n".join(text_buf)})

            elif role == "assistant":
                if isinstance(content, str):
                    out.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    text_parts: list[str] = []
                    tool_calls: list[dict] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        bt = block.get("type")
                        if bt == "text":
                            text_parts.append(block.get("text", ""))
                        elif bt == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })
                        # thinking blocks are dropped (OpenAI has no equivalent)
                    msg_out: dict[str, Any] = {"role": "assistant"}
                    # Empty content must be "" (OpenAI rejects null when no tool_calls).
                    msg_out["content"] = "\n".join(text_parts) if text_parts else ""
                    if tool_calls:
                        msg_out["tool_calls"] = tool_calls
                        # Stub missing tool_result responses by walking the next user msg.
                        # Caller is responsible for providing them; we don't synthesize here.
                    # Skip purely-empty assistant turns (no text AND no tool_calls).
                    if msg_out["content"] or tool_calls:
                        out.append(msg_out)
        return out

    @staticmethod
    def _to_openai_tools(anthropic_tools: list[dict] | None) -> list[dict] | None:
        if not anthropic_tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object"}),
                },
            }
            for t in anthropic_tools
        ]

    @staticmethod
    def _from_response(
        resp: Any,
        budget: Budget | None,
        model: str | None = None,
    ) -> LLMResponse:
        choice = resp.choices[0]
        text = choice.message.content or ""
        # DeepSeek reasoner and Gemini-thinking (via the OpenAI-compat shim)
        # return the chain-of-thought in a separate reasoning_content field,
        # never in content. Hard-coding thinking=None discarded it entirely.
        thinking = getattr(choice.message, "reasoning_content", None) or None
        tool_calls: list[ToolCall] = []
        if getattr(choice.message, "tool_calls", None):
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id, name=tc.function.name, input=args,
                ))
        if budget is not None and getattr(resp, "usage", None):
            usage = resp.usage
            # Extract cached-token counts where the provider reports
            # them. Vendors expose this on the usage object under
            # different field names; we try the known shapes and fall
            # back to 0:
            #   - OpenAI:   usage.prompt_tokens_details.cached_tokens
            #   - DeepSeek: usage.prompt_cache_hit_tokens (and _miss_tokens)
            #   - Gemini OpenAI-compat: prompt_tokens_details.cached_tokens
            # When a cached count is reported, the BILLABLE prompt
            # tokens (full rate) is prompt_tokens - cached_tokens.
            cache_read_tok = 0
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cache_read_tok = int(getattr(details, "cached_tokens", 0) or 0)
            if cache_read_tok == 0:
                cache_read_tok = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
            full_in = int(getattr(usage, "prompt_tokens", 0) or 0)
            billable_in = max(full_in - cache_read_tok, 0)
            budget.record_tokens(
                billable_in,
                int(getattr(usage, "completion_tokens", 0) or 0),
                model=model,
                cache_read_tok=cache_read_tok,
            )
        # Map finish_reason to Anthropic stop_reason vocab so consumers that
        # check Anthropic values (e.g., 'tool_use', 'end_turn') branch correctly.
        raw_reason = choice.finish_reason or "stop"
        stop_reason = _FINISH_REASON_MAP.get(raw_reason, raw_reason)
        return LLMResponse(
            text=text,
            thinking=thinking,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=resp,
        )

    def _build_kwargs(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        max_tokens: int,
        model: str | None,
    ) -> dict[str, Any]:
        chosen_model = model or self.DEFAULT_MODEL
        # Write-side prompt-cache friendliness for gpt-4.1 / o-series / gpt-5,
        # which auto-cache the longest common prefix (>= ~1024 tokens) of a
        # request. The stable prefix (system + tools schema) must lead and be
        # byte-identical across calls for the cache to hit; the volatile user
        # turn already trails since _to_openai_messages keeps system first and
        # appends history in order. The one source of cache-busting we control
        # is tool ordering, so sort it to a stable order. Skipped when the
        # prefix is too small to cache (heuristic 4 chars/token estimate) or
        # the model has no auto-cache, to keep behaviour unchanged elsewhere.
        sys_tok = len(system or "") // 4
        tools_tok = sum(len(str(t)) for t in (tools or [])) // 4
        if (
            self._has_auto_prompt_cache(chosen_model)
            and sys_tok + tools_tok >= _MIN_AUTO_CACHE_TOKENS
        ):
            tools = self._cache_friendly_tools(tools)
        kwargs: dict[str, Any] = {
            "model": chosen_model,
            "messages": self._to_openai_messages(system, messages),
        }
        # max_tokens vs max_completion_tokens (latter for gpt-4o/o1/o3/gpt-5+)
        if self._wants_max_completion(chosen_model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        oai_tools = self._to_openai_tools(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools
        return kwargs

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        # on_delta accepted for Provider-protocol parity; this client doesn't
        # stream token deltas (the Anthropic client does). Ignored, not error.
        if thinking_budget:
            log.debug("OpenAI provider ignores thinking_budget=%s", thinking_budget)
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = sync_retry(lambda: self._sync.chat.completions.create(**kwargs))
        return self._from_response(resp, budget, model=kwargs.get("model"))

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        if thinking_budget:
            log.debug("OpenAI provider ignores thinking_budget=%s", thinking_budget)
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = await async_retry(lambda: self._async.chat.completions.create(**kwargs))
        return self._from_response(resp, budget, model=kwargs.get("model"))
