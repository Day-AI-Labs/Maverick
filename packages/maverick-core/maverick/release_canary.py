"""Cost/perf canary per release (roadmap: 2028 H2 performance).

A release can pass every test and still quietly get **slower or pricier**.
This is the guard: snapshot a release's cost/perf metrics, and before shipping
the next one, compare it against the recorded baseline and fail on a
regression beyond tolerance. It's the perf analogue of a test gate.

The comparison is **direction-aware** — for cost / latency / error-rate lower
is better, for success-rate / throughput higher is better — and relative, so a
metric is flagged only when it moves the wrong way by more than ``tolerance``.
Pure and deterministic (plain metric dicts in, verdicts out); the snapshot
store is an atomic JSON file keyed by release tag. ``maverick canary
record/compare`` drives it; a non-zero exit on regression gates a release.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Metrics where a HIGHER value is better; everything else is lower-is-better
# (cost, latency, error rate, tokens, ...).
HIGHER_IS_BETTER = frozenset({
    "success_rate", "pass_rate", "accuracy", "throughput", "cache_hit_rate",
})
DEFAULT_TOLERANCE = 0.10   # 10% worse = regression


@dataclass(frozen=True)
class MetricVerdict:
    metric: str
    baseline: float
    candidate: float
    rel_change: float       # (candidate - baseline) / |baseline|
    verdict: str            # "regressed" | "improved" | "ok" | "new"


@dataclass(frozen=True)
class CanaryResult:
    verdicts: list[MetricVerdict]

    @property
    def regressions(self) -> list[MetricVerdict]:
        return [v for v in self.verdicts if v.verdict == "regressed"]

    @property
    def passed(self) -> bool:
        return not self.regressions


def _classify(metric: str, base: float, cand: float, tol: float) -> MetricVerdict:
    higher_better = metric in HIGHER_IS_BETTER
    denom = abs(base) if base else 0.0
    rel = (cand - base) / denom if denom else (0.0 if cand == base else float("inf"))
    # Worse-direction movement beyond tolerance is a regression.
    if higher_better:
        verdict = "regressed" if rel < -tol else ("improved" if rel > tol else "ok")
    else:
        verdict = "regressed" if rel > tol else ("improved" if rel < -tol else "ok")
    return MetricVerdict(metric, float(base), float(cand), round(rel, 4), verdict)


def compare(baseline: dict, candidate: dict, *,
            tolerance: float = DEFAULT_TOLERANCE) -> CanaryResult:
    """Compare two metric snapshots into per-metric verdicts.

    Only metrics present in BOTH are judged; a candidate-only metric is marked
    ``new`` (informational, never a regression). ``tolerance`` is the relative
    move (e.g. 0.10) allowed before flagging.
    """
    verdicts: list[MetricVerdict] = []
    for metric, cand in candidate.items():
        if not isinstance(cand, (int, float)):
            continue
        if metric not in baseline or not isinstance(baseline[metric], (int, float)):
            verdicts.append(MetricVerdict(metric, 0.0, float(cand), 0.0, "new"))
            continue
        verdicts.append(_classify(metric, float(baseline[metric]), float(cand), tolerance))
    verdicts.sort(key=lambda v: v.metric)
    return CanaryResult(verdicts)


class CanaryStore:
    """Atomic JSON store of ``release -> metrics``."""

    def __init__(self, path=None):
        self._explicit = path

    @property
    def path(self):
        from pathlib import Path
        if self._explicit is not None:
            return Path(self._explicit)
        from .paths import data_dir
        return data_dir("release_canary.json")

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, p)

    def record(self, release: str, metrics: dict) -> None:
        data = self._load()
        data[release] = {k: float(v) for k, v in metrics.items()
                         if isinstance(v, (int, float))}
        self._save(data)

    def get(self, release: str) -> dict | None:
        return self._load().get(release)

    def releases(self) -> list[str]:
        return sorted(self._load())


def render(result: CanaryResult) -> str:
    lines = ["CANARY: " + ("PASS" if result.passed else "FAIL")]
    for v in result.verdicts:
        mark = {"regressed": "✗", "improved": "↑", "ok": "·", "new": "+"}.get(v.verdict, "?")
        lines.append(f"  {mark} {v.metric}: {v.baseline:g} -> {v.candidate:g} "
                     f"({v.rel_change:+.1%}) [{v.verdict}]")
    return "\n".join(lines)


__all__ = ["MetricVerdict", "CanaryResult", "compare", "CanaryStore", "render",
           "HIGHER_IS_BETTER", "DEFAULT_TOLERANCE"]
