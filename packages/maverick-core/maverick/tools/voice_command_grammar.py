"""Voice command grammar (roadmap: 2027 H1 UX — "voice command grammar").

A tiny, deterministic intent parser for the voice channel: the operator
declares a grammar of command templates with ``{slot}`` placeholders, and an
incoming (already-transcribed) utterance is matched to an intent + filled
slots. No model call — the point is a fast, predictable mapping for the
high-frequency commands ("pause goal 12", "set budget to 5 dollars") so they
don't round-trip through the LLM.

ops:
  - parse(grammar, utterance)  — grammar: [{intent, pattern}] where pattern is
    free text with {slot} placeholders. Returns the first matching intent and
    its slot values, or "NO MATCH".
"""
from __future__ import annotations

import re
from typing import Any

from . import Tool

_SLOT = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_WS = re.compile(r"\s+")


def _compile(pattern: str) -> tuple[re.Pattern[str], list[str]] | None:
    """Turn a '{slot}' template into an anchored, case-insensitive regex."""
    slots: list[str] = []
    out: list[str] = []
    last = 0
    for m in _SLOT.finditer(pattern):
        out.append(re.escape(pattern[last:m.start()]))
        name = m.group(1)
        if name in slots:
            return None  # duplicate slot name -> invalid grammar
        slots.append(name)
        out.append(rf"(?P<{name}>.+?)")
        last = m.end()
    out.append(re.escape(pattern[last:]))
    # Collapse escaped runs of whitespace so spacing in the utterance is loose.
    regex = "".join(out).replace(r"\ ", r"\s+")
    return re.compile(rf"^\s*{regex}\s*$", re.IGNORECASE), slots


def _parse(args: dict[str, Any]) -> str:
    grammar = args.get("grammar")
    utterance = args.get("utterance")
    if not isinstance(grammar, list) or not grammar:
        return "ERROR: grammar must be a non-empty array of {intent, pattern}"
    if not isinstance(utterance, str) or not utterance.strip():
        return "ERROR: utterance must be a non-empty string"
    text = _WS.sub(" ", utterance.strip())

    for rule in grammar:
        if not isinstance(rule, dict) or "intent" not in rule or "pattern" not in rule:
            return "ERROR: each grammar rule needs 'intent' and 'pattern'"
        compiled = _compile(str(rule["pattern"]))
        if compiled is None:
            return f"ERROR: duplicate slot in pattern {rule['pattern']!r}"
        rx, slots = compiled
        m = rx.match(text)
        if m:
            lines = [f"intent: {rule['intent']}"]
            if slots:
                filled = ", ".join(f"{s}={m.group(s).strip()}" for s in slots)
                lines.append(f"slots: {filled}")
            return "\n".join(lines)
    return "NO MATCH"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op", "parse")
    if op != "parse":
        return f"ERROR: unknown op {op!r}"
    return _parse(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["parse"]},
        "grammar": {
            "type": "array",
            "description": "command templates: [{intent, pattern}] with {slot} placeholders",
            "items": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["intent", "pattern"],
            },
        },
        "utterance": {"type": "string", "description": "transcribed utterance to match"},
    },
    "required": ["grammar", "utterance"],
}


def voice_command_grammar() -> Tool:
    return Tool(
        name="voice_command_grammar",
        description=(
            "Match a transcribed utterance to a command intent + slots. "
            "op=parse with 'grammar' ([{intent, pattern}], patterns use {slot} "
            "placeholders) and an 'utterance'. Returns the first matching "
            "intent and its slot values, or NO MATCH. Deterministic; no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
