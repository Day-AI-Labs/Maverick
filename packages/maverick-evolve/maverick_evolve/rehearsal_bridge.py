"""Bridge the kernel's dream-time rehearsal queue into the eval harness.

``maverick dream`` queues the biggest recurring failure patterns as practice
cases (``~/.maverick/dreams/rehearsals.ndjson``). This bridge turns that
queue into :class:`~maverick_evolve.eval_harness.EvalCase` objects, so
``evolve_with_eval`` / ``evolve_continuous`` optimize agent configs against
the operator's OWN recurring failures instead of (or alongside) a synthetic
benchmark — the data engine eating its own telemetry.

Grading reuses the kernel's ``rehearsal_completed`` signal when the kernel
is importable, with an identical local fallback, so a case passes here
exactly when ``maverick dream --rehearse`` would count it.
"""
from __future__ import annotations

import json
from pathlib import Path

from .eval_harness import EvalCase

DEFAULT_REHEARSALS = Path.home() / ".maverick" / "dreams" / "rehearsals.ndjson"


def _completed(output: str) -> bool:
    try:
        from maverick.dreaming import rehearsal_completed
        return bool(rehearsal_completed(output))
    except ImportError:  # evolve can run without the kernel installed
        out = (output or "").strip()
        return bool(out) and not out.startswith(
            ("Stopped", "ERROR", "BLOCKED", "⚠"),
        )


def cases_from_rehearsals(
    path: str | Path | None = None, *, max_cases: int = 10,
) -> list[EvalCase]:
    """Load the rehearsal queue as eval cases, biggest evidence first.

    Each case is weighted by its cluster evidence (a failure seen 5x matters
    more to fitness than one seen twice). Empty list when the queue is
    missing or empty — callers fall back to their synthetic case set.
    """
    p = Path(path) if path is not None else DEFAULT_REHEARSALS
    if not p.exists():
        return []
    rows: list[dict] = []
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict) and str(d.get("prompt", "")).strip():
                    rows.append(d)
    except OSError:
        return []
    rows.sort(key=lambda r: -int(r.get("evidence", 1) or 1))
    return [
        EvalCase(
            prompt=str(r["prompt"]),
            check=_completed,
            weight=float(max(1, int(r.get("evidence", 1) or 1))),
        )
        for r in rows[:max(1, max_cases)]
    ]


__all__ = ["DEFAULT_REHEARSALS", "cases_from_rehearsals"]
