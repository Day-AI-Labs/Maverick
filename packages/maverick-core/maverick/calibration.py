"""Verifier calibration: keep the evaluator honest before the system learns.

Self-improvement closes the loop between the evaluator and the policy. The
verifier's confidence is the *label* the trajectory-donation flywheel
(:func:`maverick.donation.should_donate`) and the skill distiller learn from.
If the verifier drifts -- starts assigning high confidence to wrong answers --
the system trains on its own mistakes and compounds them (reward hacking /
model collapse). The single most important guardrail for safe self-improvement
is therefore: the evaluator must keep *discriminating* correct from incorrect,
and learning must FREEZE if it stops.

This module is that interlock. It mirrors the standard "judge calibration set"
pattern: hold a set of ``(verifier_confidence, ground_truth)`` samples and
require that the verifier's mean confidence on correct answers exceeds its mean
on incorrect answers by a margin, over enough samples. When an assessment finds
the verifier inadequate, :func:`learning_frozen` returns True and
``donation.write_record`` refuses to harvest new trajectories.

Samples come from a labeled set the operator feeds (``maverick calibrate
--sample ...``) or any ground-truth source (e.g. coding-mode test outcomes
paired with the verifier's confidence). The producer is deliberately decoupled
from the consumer so any ground-truth signal can drive it.

OFF by default and fail-open (kernel rule 1): the freeze only engages when
enforcement is enabled AND an assessment has actually run and found the
verifier inadequate. Any error here leaves learning exactly as it was -- this
gate can only make the system MORE cautious about what it learns, never a new
way to block a run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import env_flag

log = logging.getLogger(__name__)

# Legacy/global fallback locations (single-tenant). Multi-tenant deployments
# resolve these per-tenant at call time via :func:`_samples_path`/:func:`_verdict_path`
# so one tenant's calibration samples and learning-freeze verdict never bleed
# into another's self-improvement loop. With no active tenant these resolve to
# exactly the historical paths below (single-tenant behaviour unchanged).
SAMPLES_PATH = Path.home() / ".maverick" / "calibration.ndjson"
VERDICT_PATH = Path.home() / ".maverick" / "calibration_verdict.json"


def _samples_path() -> Path:
    """Tenant-scoped calibration-sample ledger (legacy root when no tenant active)."""
    try:
        from .paths import data_dir
        return data_dir("calibration.ndjson")
    except Exception:  # pragma: no cover -- never let path resolution block a run
        return SAMPLES_PATH


def _verdict_path() -> Path:
    """Tenant-scoped learning-freeze verdict (legacy root when no tenant active)."""
    try:
        from .paths import data_dir
        return data_dir("calibration_verdict.json")
    except Exception:  # pragma: no cover -- never let path resolution block a run
        return VERDICT_PATH

# Last-resort defaults; live values come from ``[calibration]`` (config.get_calibration).
_DEFAULTS = {
    "enforce": False,
    "min_samples": 20,
    "min_discrimination": 0.15,
    "collect_from_coding": False,
}

_lock = threading.Lock()


def _settings() -> dict:
    try:
        from .config import get_calibration
        return get_calibration()
    except Exception:  # pragma: no cover -- config must never block a run
        return dict(_DEFAULTS)


def collect_from_coding_enabled() -> bool:
    """Whether to auto-record calibration samples from coding-mode runs.

    When a coding-mode run has ground truth (tests pass/fail), the agent loop
    can also ask the LLM verifier and record ``(confidence, correct)`` so the
    interlock learns whether the judge still tracks reality -- without an
    operator hand-feeding a labeled set. Off by default (it costs one extra
    verifier call per coding FINAL). ``MAVERICK_CALIBRATION_COLLECT_CODING``
    overrides ``[calibration] collect_from_coding``.
    """
    _v = env_flag("MAVERICK_CALIBRATION_COLLECT_CODING")
    if _v is not None:
        return _v
    return bool(_settings().get("collect_from_coding", False))


@dataclass
class CalibrationSample:
    confidence: float
    correct: bool
    ts: float = 0.0
    source: str = ""


@dataclass
class CalibrationReport:
    """The outcome of assessing a set of calibration samples.

    ``discrimination`` is mean(confidence | correct) - mean(confidence |
    incorrect): how much higher the verifier scores answers that were actually
    right. ``brier`` is the mean squared error of confidence vs. outcome
    (lower is better). ``adequate`` is the verdict the freeze gate reads.
    """
    n: int
    n_correct: int
    n_incorrect: int
    discrimination: float
    brier: float
    adequate: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": time.time(),
            "n": self.n,
            "n_correct": self.n_correct,
            "n_incorrect": self.n_incorrect,
            "discrimination": round(self.discrimination, 4),
            "brier": round(self.brier, 4),
            "adequate": self.adequate,
            "reason": self.reason,
        }


def assess(
    samples: list[CalibrationSample],
    *,
    min_samples: int | None = None,
    min_discrimination: float | None = None,
) -> CalibrationReport:
    """Assess whether verifier confidence still discriminates correct answers.

    Adequate requires: at least ``min_samples`` total, BOTH classes present
    (you cannot judge discrimination with only correct or only incorrect
    samples), and ``discrimination >= min_discrimination``. The thresholds
    default to the ``[calibration]`` config.
    """
    s = _settings()
    min_n = s["min_samples"] if min_samples is None else min_samples
    min_disc = s["min_discrimination"] if min_discrimination is None else min_discrimination

    n = len(samples)
    correct = [x for x in samples if x.correct]
    incorrect = [x for x in samples if not x.correct]
    nc, ni = len(correct), len(incorrect)

    def _mean(xs: list[CalibrationSample]) -> float:
        return sum(_clamp01(x.confidence) for x in xs) / len(xs) if xs else 0.0

    mean_c = _mean(correct)
    mean_i = _mean(incorrect)
    discrimination = mean_c - mean_i
    brier = (
        sum((_clamp01(x.confidence) - (1.0 if x.correct else 0.0)) ** 2 for x in samples) / n
        if n else 1.0
    )

    if n < min_n:
        return CalibrationReport(
            n, nc, ni, discrimination, brier, adequate=False,
            reason=f"not enough samples ({n} < {min_n}); cannot assess calibration",
        )
    if nc == 0 or ni == 0:
        return CalibrationReport(
            n, nc, ni, discrimination, brier, adequate=False,
            reason="need both correct and incorrect samples to judge discrimination",
        )
    if discrimination < min_disc:
        return CalibrationReport(
            n, nc, ni, discrimination, brier, adequate=False,
            reason=(
                f"verifier discrimination {discrimination:.2f} below floor "
                f"{min_disc:.2f}: confidence no longer separates correct from "
                "incorrect; learning frozen"
            ),
        )
    return CalibrationReport(
        n, nc, ni, discrimination, brier, adequate=True,
        reason=f"verifier discriminates by {discrimination:.2f} over {n} samples",
    )


def _clamp01(v: float) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def record_sample(
    confidence: float, correct: bool, *, source: str = "",
    path: Path | None = None,
) -> bool:
    """Append one ``(confidence, ground_truth)`` calibration sample. Never raises."""
    if path is None:
        path = _samples_path()
    entry = CalibrationSample(
        confidence=_clamp01(confidence), correct=bool(correct),
        ts=time.time(), source=str(source or "")[:120],
    )
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.__dict__) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except OSError as e:
            log.warning("calibration: sample write failed: %s", e)
            return False


def load_samples(path: Path | None = None) -> list[CalibrationSample]:
    """Read the calibration-sample ledger (most recent last). Never raises."""
    if path is None:
        path = _samples_path()
    if not path.exists():
        return []
    out: list[CalibrationSample] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    if not isinstance(d, dict):
                        continue
                    out.append(CalibrationSample(
                        confidence=float(d.get("confidence", 0.0)),
                        correct=bool(d.get("correct", False)),
                        ts=float(d.get("ts", 0.0) or 0.0),
                        source=str(d.get("source", "")),
                    ))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return out


def run_assessment(
    *, samples_path: Path | None = None, verdict_path: Path | None = None,
) -> CalibrationReport:
    """Assess the ledger and persist the verdict that :func:`learning_frozen` reads."""
    if samples_path is None:
        samples_path = _samples_path()
    if verdict_path is None:
        verdict_path = _verdict_path()
    report = assess(load_samples(samples_path))
    with _lock:
        try:
            verdict_path.parent.mkdir(parents=True, exist_ok=True)
            verdict_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
            try:
                os.chmod(verdict_path, 0o600)
            except OSError:
                pass
        except OSError as e:  # pragma: no cover -- persistence is best-effort
            log.warning("calibration: verdict write failed: %s", e)
    return report


def _load_verdict(path: Path | None = None) -> dict | None:
    if path is None:
        path = _verdict_path()
    if not path.exists():
        return None
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return verdict if isinstance(verdict, dict) else None


def learning_frozen(*, verdict_path: Path | None = None) -> bool:
    """Whether self-improvement should be frozen because the verifier drifted.

    True only when enforcement is enabled AND a persisted assessment exists and
    found the verifier inadequate. With enforcement off, or no assessment yet,
    returns False (learning proceeds as today). Fail-open.

    The verdict is resolved per-tenant: a freeze raised by one tenant's drifting
    verifier does not freeze learning for other tenants.
    """
    s = _settings()
    if not s["enforce"]:
        return False
    if verdict_path is None:
        verdict_path = _verdict_path()
    verdict = _load_verdict(verdict_path)
    if verdict is None:
        # No assessment has run: we have no evidence of drift, so don't freeze.
        return False
    return not bool(verdict.get("adequate", True))


__all__ = [
    "CalibrationSample",
    "CalibrationReport",
    "assess",
    "collect_from_coding_enabled",
    "record_sample",
    "load_samples",
    "run_assessment",
    "learning_frozen",
    "SAMPLES_PATH",
    "VERDICT_PATH",
]
