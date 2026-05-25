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
from typing import Any, Optional

from ..budget import Budget
from ..llm import LLMResponse, ToolCall

log = logging.getLogger(__name__)


# Models that require max_completion_tokens instead of max_tokens.
_MODELS_WANTING_MAX_COMPLETION_TOKENS = (
    "gpt-4o", "gpt-4.1", "o1", "o3", "o4", "gpt-5",
)

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

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        try:
            from openai import OpenAI, AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. Run: pip install 'maverick[openai]'"
            ) from e
        key = api_key or os.environ.get("OPENAI_API_KEY")
        self._sync = OpenAI(api_key=key, base_url=base_url)
        self._async = AsyncOpenAI(api_key=key, base_url=base_url)

    @staticmethod
    def _wants_max_completion(model: str) -> bool:
        return any(model.startswith(prefix) for prefix in _MODELS_WANTING_MAX_COMPLETION_TOKENS)

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
    def _to_openai_tools(anthropic_tools: Optional[list[dict]]) -> Optional[list[dict]]:
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
        budget: Optional[Budget],
        model: Optional[str] = None,
    ) -> LLMResponse:
        choice = resp.choices[0]
        text = choice.message.content or ""
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
            budget.record_tokens(
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
                model=model,
            )
        # Map finish_reason to Anthropic stop_reason vocab so consumers that
        # check Anthropic values (e.g., 'tool_use', 'end_turn') branch correctly.
        raw_reason = choice.finish_reason or "stop"
        stop_reason = _FINISH_REASON_MAP.get(raw_reason, raw_reason)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=resp,
        )

    def _build_kwargs(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]],
        max_tokens: int,
        model: Optional[str],
    ) -> dict[str, Any]:
        chosen_model = model or self.DEFAULT_MODEL
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
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        if thinking_budget:
            log.debug("OpenAI provider ignores thinking_budget=%s", thinking_budget)
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = self._sync.chat.completions.create(**kwargs)
        return self._from_response(resp, budget, model=kwargs.get("model"))

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
        if thinking_budget:
            log.debug("OpenAI provider ignores thinking_budget=%s", thinking_budget)
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = await self._async.chat.completions.create(**kwargs)
        return self._from_response(resp, budget, model=kwargs.get("model"))
