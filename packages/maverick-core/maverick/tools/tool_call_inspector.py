"""Tool-call inspector (roadmap: 2027 H1 UX — "tool-call inspector").

Reads a run's tool-call log and produces the per-tool summary the inspector
panel shows: how often each tool was called, its error rate, total and average
latency, and the slowest single call — plus a flag on any tool whose error rate
crosses a threshold. Deterministic and offline.

ops:
  - inspect(calls[, error_threshold])  — calls: [{tool, ok?, ms?, error?}].
    'ok' defaults to true unless 'error' is present. Reports the per-tool table
    sorted by call count, with HIGH-ERROR flags.
"""
from __future__ import annotations

from typing import Any

from . import Tool


def _is_ok(c: dict[str, Any]) -> bool:
    if "ok" in c:
        return bool(c["ok"])
    return not c.get("error")


def _inspect(args: dict[str, Any]) -> str:
    calls = args.get("calls")
    if not isinstance(calls, list) or not calls:
        return "ERROR: calls must be a non-empty array of {tool, ok?, ms?, error?}"
    thr = args.get("error_threshold", 0.5)
    if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not 0 <= thr <= 1:
        return "ERROR: error_threshold must be a number in [0, 1]"

    stats: dict[str, dict[str, Any]] = {}
    for c in calls:
        if not isinstance(c, dict) or "tool" not in c:
            return "ERROR: each call needs a 'tool'"
        t = str(c["tool"])
        s = stats.setdefault(t, {"n": 0, "errors": 0, "ms": 0.0, "max_ms": 0.0, "top_error": ""})
        s["n"] += 1
        if not _is_ok(c):
            s["errors"] += 1
            if not s["top_error"] and c.get("error"):
                s["top_error"] = str(c["error"])[:80]
        ms = c.get("ms")
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            s["ms"] += float(ms)
            s["max_ms"] = max(s["max_ms"], float(ms))

    total = sum(s["n"] for s in stats.values())
    total_err = sum(s["errors"] for s in stats.values())
    lines = [f"calls: {total}  tools: {len(stats)}  errors: {total_err} ({total_err / total:.0%})"]
    for t in sorted(stats, key=lambda k: (-stats[k]["n"], k)):
        s = stats[t]
        rate = s["errors"] / s["n"]
        avg = s["ms"] / s["n"] if s["n"] else 0.0
        flag = "  HIGH-ERROR" if rate >= thr and s["errors"] else ""
        row = (
            f"  {t}: n={s['n']} err={s['errors']} ({rate:.0%}) "
            f"avg={avg:g}ms max={s['max_ms']:g}ms{flag}"
        )
        if s["top_error"]:
            row += f"  e.g. {s['top_error']!r}"
        lines.append(row)
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op", "inspect")
    if op != "inspect":
        return f"ERROR: unknown op {op!r}"
    return _inspect(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["inspect"]},
        "calls": {
            "type": "array",
            "description": "tool-call log: [{tool, ok?, ms?, error?}]",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "ms": {"type": "number"},
                    "error": {"type": "string"},
                },
                "required": ["tool"],
            },
        },
        "error_threshold": {"type": "number", "description": "flag tools at/above this error rate (default 0.5)"},
    },
    "required": ["calls"],
}


def tool_call_inspector() -> Tool:
    return Tool(
        name="tool_call_inspector",
        description=(
            "Summarise a run's tool-call log. op=inspect with 'calls' "
            "([{tool, ok?, ms?, error?}]) reports per-tool count, error rate, "
            "avg/max latency, a sample error, and HIGH-ERROR flags above "
            "'error_threshold'. Deterministic; no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
