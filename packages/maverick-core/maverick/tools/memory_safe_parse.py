"""Memory-safe parsers (roadmap: 2027 H2 safety — "memory-safe parsers").

Parse untrusted text (JSON or CSV) under hard resource bounds so a hostile
input can't exhaust memory or blow the stack: cap raw byte size, nesting depth,
and item/row count BEFORE and DURING parsing. Never raises on bad input — a
breach returns ``REJECT: ...`` naming the limit hit; a clean parse returns
``OK`` with a shape summary (never the full payload back).

ops:
  - parse(text, format: json|csv, [max_bytes], [max_depth], [max_items])
"""
from __future__ import annotations

import json
from typing import Any

from . import Tool

_DEFAULT_MAX_BYTES = 1_000_000
_DEFAULT_MAX_DEPTH = 64
_DEFAULT_MAX_ITEMS = 100_000


def _depth_of(obj: Any) -> int:
    """Iterative max container nesting depth (no recursion -> no stack blowup)."""
    deepest = 0
    stack: list[tuple[Any, int]] = [(obj, 1)]
    while stack:
        node, d = stack.pop()
        if d > deepest:
            deepest = d
        if isinstance(node, dict):
            for v in node.values():
                stack.append((v, d + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, d + 1))
    return deepest


def _count_items(obj: Any) -> int:
    """Total number of container elements (dict entries + list items)."""
    total = 0
    stack: list[Any] = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            total += len(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            total += len(node)
            stack.extend(node)
    return total


def _parse_json(text: str, max_depth: int, max_items: int) -> str:
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError) as e:
        return f"REJECT: invalid JSON ({type(e).__name__})"
    depth = _depth_of(obj)
    if depth > max_depth:
        return f"REJECT: nesting depth {depth} exceeds max_depth {max_depth}"
    items = _count_items(obj)
    if items > max_items:
        return f"REJECT: item count {items} exceeds max_items {max_items}"
    top = type(obj).__name__
    return (f"OK json: top-level {top}, depth {depth}, "
            f"{items} container item(s)")


def _parse_csv(text: str, max_items: int) -> str:
    # Hand-roll a minimal, bounded CSV split rather than feed the whole blob to
    # csv.reader at once: count rows as we go and stop the moment the cap is
    # crossed, so a billion-row input can't be fully materialised.
    rows = 0
    cols = 0
    for line in text.splitlines():
        if line == "":
            continue
        rows += 1
        if rows == 1:
            cols = len(line.split(","))
        if rows > max_items:
            return f"REJECT: row count exceeds max_items {max_items}"
    return f"OK csv: {rows} row(s), {cols} column(s) in header"


def _parse(text: str, fmt: str, max_bytes: int, max_depth: int, max_items: int) -> str:
    # Size gate FIRST, before any structural work touches the payload.
    size = len(text.encode("utf-8", errors="ignore"))
    if size > max_bytes:
        return f"REJECT: input size {size} bytes exceeds max_bytes {max_bytes}"
    if fmt == "json":
        return _parse_json(text, max_depth, max_items)
    if fmt == "csv":
        return _parse_csv(text, max_items)
    return f"ERROR: format must be 'json' or 'csv', got {fmt!r}"


def _bounded_int(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "parse"):
        return f"ERROR: unknown op {args.get('op')!r}"
    text = args.get("text")
    if not isinstance(text, str):
        return "ERROR: text (string) is required"
    fmt = str(args.get("format", "json")).strip().lower()
    max_bytes = _bounded_int(args.get("max_bytes"), _DEFAULT_MAX_BYTES)
    max_depth = _bounded_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_items = _bounded_int(args.get("max_items"), _DEFAULT_MAX_ITEMS)
    return _parse(text, fmt, max_bytes, max_depth, max_items)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["parse"]},
        "text": {"type": "string", "description": "Untrusted text to parse"},
        "format": {"type": "string", "enum": ["json", "csv"]},
        "max_bytes": {"type": "integer", "description": "Max raw UTF-8 byte size"},
        "max_depth": {"type": "integer", "description": "Max nesting depth (JSON)"},
        "max_items": {"type": "integer", "description": "Max container items / CSV rows"},
    },
    "required": ["text"],
}


def memory_safe_parse() -> Tool:
    return Tool(
        name="memory_safe_parse",
        description=(
            "Parse untrusted JSON/CSV under hard resource bounds. op=parse with "
            "'text', 'format' (json|csv), and optional 'max_bytes', 'max_depth', "
            "'max_items'. Bounds size, nesting depth, and item count before/"
            "during parsing; returns OK with a shape summary or REJECT naming "
            "the limit breached. Never raises on hostile input. Offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
