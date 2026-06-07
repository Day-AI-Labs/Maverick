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
from typing import Any

from ..budget import Budget
from ..llm import LLMResponse, ToolCall

log = logging.getLogger(__name__)


# A tool block in either drift form the models use:
#   <tool name="NAME">{...json...}</tool>   (preferred, named-attribute)
#   <tool>NAME({...json...})</tool>          (inline, function-call style)
# We capture the inner content up to the first </tool>, then pull the JSON args
# out with a balance-aware scan (see _args_from_region) so NESTED objects
# survive -- the old lazy `\{.*?\}` truncated at the first '}' and silently
# dropped any call whose arguments contained a nested object.
_TOOL_BLOCK = re.compile(
    r"<tool(?:\s+name=\"([^\"]+)\")?\s*>(.*?)</tool>", re.DOTALL
)
_INLINE_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)")


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


def _extract_json_object(s: str, start: int) -> str | None:
    """Return the balanced ``{...}`` beginning at ``s[start]`` (which must be
    ``{``), respecting string literals and escapes so a brace *inside* a JSON
    string isn't counted. ``None`` if the object never balances.
    """
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _loads_tolerant(raw: str) -> Any | None:
    """``json.loads`` with two cheap repairs for common model drift: strip a
    surrounding code fence, then drop trailing commas. ``None`` if still invalid.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[A-Za-z0-9]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def _args_from_region(region: str) -> dict | None:
    """Extract a call's JSON args from the inner-tag text.

    Finds the first ``{`` and takes the *balanced* object from there (so nested
    objects survive), parsing it tolerantly. A block with no ``{`` is a valid
    no-argument call -> ``{}``. Returns ``None`` only when a JSON object is
    present but genuinely unparseable, so the caller drops the call.
    """
    brace = region.find("{")
    if brace == -1:
        return {}
    obj = _extract_json_object(region, brace)
    if obj is None:
        return None
    parsed = _loads_tolerant(obj)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        return {"_raw": parsed}
    return parsed


def _parse_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    """Pull tool-call blocks out of model text.

    Returns (remaining_text, tool_calls). The tool blocks are removed (any prose
    around them is kept as the response text). Handles both protocol forms,
    nested-JSON arguments, no-arg calls, and common JSON drift (code fences /
    trailing commas); a block whose JSON is genuinely malformed is dropped
    (logged) so the agent sees the leftover text rather than a crash.
    """
    calls: list[ToolCall] = []

    def _consume(match: re.Match) -> str:
        named = match.group(1)
        inner = match.group(2) or ""
        if named:
            name, region = named.strip(), inner
        else:
            m = _INLINE_NAME.match(inner)
            if not m:
                return ""  # no routable tool name -> drop
            name, region = m.group(1), inner[m.end():]
        if not name:
            return ""
        args = _args_from_region(region)
        if args is None:
            log.warning("Failed to parse tool args for %s: %r", name, region[:200])
            # Drop the call; the model emitted malformed JSON. The leftover
            # text lets the agent kernel see what happened.
            return ""
        calls.append(ToolCall(
            id=f"sim_{uuid.uuid4().hex[:12]}",
            name=name,
            input=args,
        ))
        return ""

    cleaned = _TOOL_BLOCK.sub(_consume, text)
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
        tools: list[dict] | None,
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
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
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
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
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
