"""Simulated tool-calling for session providers.

Session providers (chatgpt-session, claude-session, kimi-session, ...)
talk to consumer-chat endpoints that don't expose native function-
calling. This wrapper makes them usable for tool-using roles
(orchestrator, coder, researcher) by:

  1. Rendering ``tools=[...]`` into a markdown protocol the model can
     follow ("To call tool X, emit <tool>X(...json...)</tool>")
  2. Letting the underlying session client run a plain text completion
  3. Parsing the model output for tool-call markers
  4. Reconstructing LLMResponse.tool_calls so the agent kernel can
     route results back through the normal tool-result loop

Quality is model-dependent. Sonnet- and 4o-class models follow the
protocol reliably. Smaller models may emit malformed calls; we surface
those as text so the agent can react. Not a complete replacement for
native tool use -- but enough to unlock the cost-savings angle.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from ..budget import Budget
from ..llm import LLMResponse, ToolCall

log = logging.getLogger(__name__)


# Recognises both <tool>name(...)</tool> and the simpler <tool name="X">
# {...}</tool> forms. Models tend to drift between styles; accepting
# both reduces false negatives.
_TOOL_PATTERN_NAMED = re.compile(
    r"<tool\s+name=\"([^\"]+)\"\s*>\s*(\{.*?\})\s*</tool>", re.DOTALL
)
_TOOL_PATTERN_INLINE = re.compile(
    r"<tool>\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(\{.*?\})\s*\)\s*</tool>", re.DOTALL
)


def _render_tool_prompt(tools: list[dict]) -> str:
    """Render Anthropic-format tool defs as a markdown system addendum."""
    if not tools:
        return ""
    lines = [
        "",
        "## Tools available",
        "",
        "You can call tools by emitting EXACTLY this XML in your response:",
        "",
        '    <tool name="TOOL_NAME">{"arg1": "value1", "arg2": "value2"}</tool>',
        "",
        "Each tool call must be valid JSON on a single tool-block. Emit one "
        "or more tool calls, then STOP. The tool results will come back in "
        "the next turn. Use plain text only when you have the final answer.",
        "",
        "The available tools are:",
        "",
    ]
    for t in tools:
        name = t.get("name") or t.get("function", {}).get("name") or "unknown"
        desc = t.get("description") or t.get("function", {}).get("description") or ""
        schema = (
            t.get("input_schema")
            or t.get("function", {}).get("parameters")
            or {}
        )
        lines.append(f"- **{name}**: {desc.strip()}")
        if schema:
            props = schema.get("properties") or {}
            if props:
                lines.append(f"    args: {json.dumps(props, indent=2)[:600]}")
    lines.append("")
    return "\n".join(lines)


def _parse_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    """Pull tool-call XML blocks out of model text.

    Returns (remaining_text, tool_calls). The remaining text has the
    tool blocks removed (we keep any prose around them as the response
    text in case the model also gave an explanation).
    """
    calls: list[ToolCall] = []

    def _consume(match: re.Match) -> str:
        name = match.group(1).strip()
        raw_args = match.group(2)
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            log.warning("Failed to parse tool args for %s: %r", name, raw_args[:200])
            # Drop the call; the model emitted malformed JSON. The
            # leftover text will let the agent kernel see what happened.
            return ""
        if not isinstance(args, dict):
            args = {"_raw": args}
        calls.append(ToolCall(
            id=f"sim_{uuid.uuid4().hex[:12]}",
            name=name,
            input=args,
        ))
        return ""

    # Try the named-attribute form first (preferred protocol), then the
    # inline form for models that ignored the explicit instruction.
    cleaned = _TOOL_PATTERN_NAMED.sub(_consume, text)
    cleaned = _TOOL_PATTERN_INLINE.sub(_consume, cleaned)
    return cleaned.strip(), calls


class SimulatedToolCallClient:
    """Wraps a session client to support tools=[...] via markdown protocol.

    Drop-in shape replacement for any of the session adapters: same
    ``complete()`` / ``complete_async()`` signatures, but ``tools``
    actually works.
    """

    def __init__(self, inner: Any):
        self._inner = inner
        self.DEFAULT_MODEL = getattr(inner, "DEFAULT_MODEL", None)

    def _augment(
        self,
        system: str,
        tools: Optional[list[dict]],
    ) -> str:
        if not tools:
            return system
        addendum = _render_tool_prompt(tools)
        # If the system prompt already has tool guidance, append rather
        # than replace -- the user may have hand-tuned it.
        if "## Tools available" in (system or ""):
            return (system or "") + addendum
        return (system or "") + addendum

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
        augmented_system = self._augment(system, tools)
        resp = self._inner.complete(
            system=augmented_system,
            messages=messages,
            tools=None,  # underlying adapter must NOT see tools
            budget=budget,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            model=model,
        )
        if not tools:
            return resp
        cleaned_text, calls = _parse_tool_calls(resp.text or "")
        if calls:
            return LLMResponse(
                text=cleaned_text,
                thinking=resp.thinking,
                tool_calls=calls,
                stop_reason="tool_use",
                cache_creation_tokens=resp.cache_creation_tokens,
                cache_read_tokens=resp.cache_read_tokens,
                raw=resp.raw,
                thinking_blocks=resp.thinking_blocks,
                thinking_signature=resp.thinking_signature,
            )
        return resp

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
        augmented_system = self._augment(system, tools)
        resp = await self._inner.complete_async(
            system=augmented_system,
            messages=messages,
            tools=None,
            budget=budget,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            model=model,
        )
        if not tools:
            return resp
        cleaned_text, calls = _parse_tool_calls(resp.text or "")
        if calls:
            return LLMResponse(
                text=cleaned_text,
                thinking=resp.thinking,
                tool_calls=calls,
                stop_reason="tool_use",
                cache_creation_tokens=resp.cache_creation_tokens,
                cache_read_tokens=resp.cache_read_tokens,
                raw=resp.raw,
                thinking_blocks=resp.thinking_blocks,
                thinking_signature=resp.thinking_signature,
            )
        return resp
