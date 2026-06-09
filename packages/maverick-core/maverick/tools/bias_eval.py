"""Bias evaluation suite (roadmap: 2028 H1 safety).

Given a set of decision outcomes labelled by group, compute the selection
(favorable-outcome) rate per group, the disparate-impact ratio (lowest rate /
highest rate), and whether it clears the 80%-rule (four-fifths) threshold of
0.8. Deterministic statistics, pure stdlib — the standard adverse-impact screen
used in fairness audits.

ops:
  - evaluate(outcomes[, threshold])  — per-group rates + DI ratio + PASS/FAIL.

``outcomes`` is a list of ``{group, favorable}`` where ``favorable`` is a bool.
The default threshold is 0.8 (the four-fifths rule); it may be overridden.
"""
from __future__ import annotations

from typing import Any

from . import Tool

_DEFAULT_THRESHOLD = 0.8


def _evaluate(outcomes: list[dict], threshold: float) -> str:
    totals: dict[str, int] = {}
    favorable: dict[str, int] = {}
    order: list[str] = []
    for o in outcomes:
        if not isinstance(o, dict):
            return "ERROR: each outcomes[] entry must be an object {group, favorable}"
        group = str(o.get("group") or "").strip()
        if not group:
            return "ERROR: each outcomes[] entry needs a non-empty 'group'"
        if group not in totals:
            totals[group] = 0
            favorable[group] = 0
            order.append(group)
        totals[group] += 1
        if o.get("favorable") is True:
            favorable[group] += 1

    rates = {g: favorable[g] / totals[g] for g in order}
    lines = ["selection rates:"]
    for g in order:
        lines.append(f"- {g}: {rates[g]:.4f} ({favorable[g]}/{totals[g]})")

    hi = max(rates.values())
    lo = min(rates.values())
    if hi == 0.0:
        ratio = 1.0  # no group selected at all -> no disparity
    else:
        ratio = lo / hi
    lines.append(f"disparate-impact ratio (min/max): {ratio:.4f}")
    lines.append(f"threshold (four-fifths rule): {threshold:g}")
    lines.append("result: " + ("PASS" if ratio >= threshold else "FAIL — adverse impact"))
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "evaluate"):
        return f"ERROR: unknown op {args.get('op')!r} (expected evaluate)"
    outcomes = args.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return "ERROR: outcomes (non-empty array of {group, favorable}) is required"
    try:
        threshold = float(args.get("threshold", _DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        return "ERROR: threshold must be a number"
    if not 0.0 < threshold <= 1.0:
        return "ERROR: threshold must be in (0, 1]"
    return _evaluate(outcomes, threshold)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["evaluate"]},
        "outcomes": {
            "type": "array",
            "description": "decision outcomes; each {group, favorable}",
            "items": {
                "type": "object",
                "properties": {
                    "group": {"type": "string"},
                    "favorable": {"type": "boolean"},
                },
                "required": ["group", "favorable"],
            },
        },
        "threshold": {
            "type": "number",
            "description": "DI-ratio pass threshold (default 0.8, the four-fifths rule)",
        },
    },
    "required": ["outcomes"],
}


def bias_eval() -> Tool:
    return Tool(
        name="bias_eval",
        description=(
            "Adverse-impact bias screen. op=evaluate with 'outcomes' (each "
            "{group, favorable}) and optional 'threshold' (default 0.8). "
            "Computes the favorable-selection rate per group, the disparate-"
            "impact ratio (min rate / max rate), and PASS/FAIL against the "
            "80%-rule (four-fifths) threshold. Deterministic statistics, pure "
            "stdlib."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
