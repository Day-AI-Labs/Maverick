"""Latency heatmap (roadmap: 2027 H1 UX — "latency heatmap").

Turns a flat list of per-tool latency samples into a tool × latency-band grid
— the data behind the dashboard's heatmap cell. Each row is a tool; each
column a latency band (<10ms, <100ms, <1s, <10s, ≥10s); each cell the count of
samples in that band, rendered with a shaded block so the hot spots read at a
glance. Deterministic and offline.

ops:
  - render(samples)  — samples: [{tool, ms}]. Renders the grid plus a p50/p95
    column per tool.
"""
from __future__ import annotations

from typing import Any

from . import Tool

# (upper-bound-exclusive-ms, label). Last band is the overflow bucket.
_BANDS = [(10, "<10ms"), (100, "<100ms"), (1000, "<1s"), (10000, "<10s"), (float("inf"), "≥10s")]
_BLOCKS = " ▁▂▃▄▅▆▇█"


def _band_index(ms: float) -> int:
    for i, (upper, _) in enumerate(_BANDS):
        if ms < upper:
            return i
    return len(_BANDS) - 1


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _shade(count: int, peak: int) -> str:
    if count == 0 or peak == 0:
        return _BLOCKS[0]
    idx = 1 + int((len(_BLOCKS) - 2) * (count / peak))
    return _BLOCKS[min(idx, len(_BLOCKS) - 1)]


def _render(args: dict[str, Any]) -> str:
    samples = args.get("samples")
    if not isinstance(samples, list) or not samples:
        return "ERROR: samples must be a non-empty array of {tool, ms}"

    by_tool: dict[str, list[float]] = {}
    for s in samples:
        if not isinstance(s, dict) or "tool" not in s or "ms" not in s:
            return "ERROR: each sample needs 'tool' and 'ms'"
        ms = s["ms"]
        if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms < 0:
            return f"ERROR: ms must be a number >= 0 (got {ms!r})"
        by_tool.setdefault(str(s["tool"]), []).append(float(ms))

    grids = {t: [0] * len(_BANDS) for t in by_tool}
    for t, vals in by_tool.items():
        for v in vals:
            grids[t][_band_index(v)] += 1
    peak = max((c for row in grids.values() for c in row), default=0)

    name_w = max(len(t) for t in by_tool)
    header = " " * (name_w + 2) + "  ".join(lbl for _, lbl in _BANDS)
    lines = [header]
    for t in sorted(by_tool):
        vals = sorted(by_tool[t])
        cells = "  ".join(
            f"{_shade(grids[t][i], peak)}{grids[t][i]:<{max(1, len(lbl) - 1)}}"
            for i, (_, lbl) in enumerate(_BANDS)
        )
        lines.append(
            f"{t:<{name_w}}  {cells}   p50={_pct(vals, 0.5):g}ms p95={_pct(vals, 0.95):g}ms"
        )
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op", "render")
    if op != "render":
        return f"ERROR: unknown op {op!r}"
    return _render(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["render"]},
        "samples": {
            "type": "array",
            "description": "latency samples: [{tool, ms}]",
            "items": {
                "type": "object",
                "properties": {"tool": {"type": "string"}, "ms": {"type": "number"}},
                "required": ["tool", "ms"],
            },
        },
    },
    "required": ["samples"],
}


def latency_heatmap() -> Tool:
    return Tool(
        name="latency_heatmap",
        description=(
            "Render a tool × latency-band heatmap from samples. op=render with "
            "'samples' ([{tool, ms}]) bins each tool's latencies into bands "
            "(<10ms…≥10s) with shaded counts and a p50/p95 column. Deterministic; "
            "no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
