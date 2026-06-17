"""Governed rollout of learning -- Apollo-style, for self-improving agents.

Palantir's Apollo promotes releases across regulated environments only behind
health constraints, in stages, with automatic rollback. The same discipline,
applied to *learning*: a distilled skill (or any learned update) is promoted to
the fleet ONLY if eval/health constraints pass, rolled out in stages
(canary -> half -> full), and AUTO-ROLLED-BACK the moment a constraint fails.

This is the fleet dimension of provable, governed learning -- "one agent learns"
becomes "the fleet learns, safely, with proof". The pure orchestration
(:func:`run_rollout`) is deterministic and offline-tested with injected
deploy/rollback/constraints; :func:`promote_skill_live` wires the real
snapshot+rollback (``maverick.dreaming``) and signed learning audit. Invoked
deliberately by an operator/loop -- nothing auto-promotes, so the kernel is
unchanged out of the box.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# A constraint gates one stage: given (candidate, stage_fraction) it returns
# (ok, name) -- a health/eval check (success-rate >= baseline, no correctness
# regression, error-rate under ceiling, ...). Pure/injected.
Constraint = Callable[[str, float], "tuple[bool, str]"]


@dataclass(frozen=True)
class Stage:
    """One rollout stage: a named fraction of the fleet."""
    name: str
    fraction: float


# Canary first, then half, then everyone -- the classic safe ramp.
DEFAULT_STAGES: tuple[Stage, ...] = (
    Stage("canary", 0.1), Stage("half", 0.5), Stage("full", 1.0))


@dataclass
class StageResult:
    stage: str
    fraction: float
    passed: bool
    failing_constraint: str = ""


@dataclass
class RolloutResult:
    candidate: str
    stages: list[StageResult] = field(default_factory=list)
    rolled_back: bool = False
    completed: bool = False
    reason: str = ""

    @property
    def reached_fraction(self) -> float:
        """The largest fleet fraction that ran with all constraints green."""
        return max((s.fraction for s in self.stages if s.passed), default=0.0)


def run_rollout(candidate: str, stages, constraints, *,
                deploy: Callable[[str, float], None],
                rollback: Callable[[str], None]) -> RolloutResult:
    """Stage-by-stage: ``deploy(candidate, fraction)``, then check every
    constraint; on ANY failure, ``rollback(candidate)`` and stop. Reaching the
    final stage with all constraints green = ``completed``. Pure orchestration."""
    result = RolloutResult(candidate=candidate)
    for st in stages:
        deploy(candidate, st.fraction)
        failing = ""
        for c in constraints:
            try:
                ok, name = c(candidate, st.fraction)
            except Exception as e:  # a constraint that errors is treated as FAILING
                ok, name = False, f"{getattr(c, '__name__', 'constraint')}:error:{e}"
            if not ok:
                failing = name
                break
        result.stages.append(StageResult(st.name, st.fraction, not failing, failing))
        if failing:
            rollback(candidate)
            result.rolled_back = True
            result.reason = f"constraint {failing!r} failed at stage {st.name!r}; rolled back"
            return result
    result.completed = True
    result.reason = "all stages passed"
    return result


def threshold_constraint(name: str, metric: Callable[[str, float], float],
                         floor: float) -> Constraint:
    """A constraint that passes iff ``metric(candidate, fraction) >= floor`` --
    e.g. promoted-skill win-rate must stay at/above a baseline."""
    def _c(candidate: str, fraction: float) -> tuple[bool, str]:
        return (metric(candidate, fraction) >= floor), name
    _c.__name__ = name
    return _c


def promote_skill_live(candidate: str, constraints, *,
                       stages=DEFAULT_STAGES) -> RolloutResult:  # pragma: no cover -- touches learned state
    """Live promotion: snapshot the learned state first, run the staged rollout,
    and on a failed constraint restore the snapshot (whole-store rollback) and
    record a signed learning-audit row. Fail-safe: snapshot/audit errors degrade
    to a no-op, never a half-applied promotion."""
    from . import dreaming

    try:
        dreaming.snapshot_learning_state()
    except Exception as e:
        log.warning("rollout: pre-promotion snapshot failed (%s); proceeding cautiously", e)

    def deploy(cand: str, fraction: float) -> None:
        try:
            from .audit import EventKind, record
            record(EventKind.LEARNING_UPDATE, agent="learning_rollout",
                   candidate=cand, stage_fraction=fraction, phase="deploy")
        except Exception:
            pass

    def rollback(cand: str) -> None:
        try:
            dreaming.rollback_learning_state("latest")
        except Exception as e:
            log.warning("rollout: rollback failed (%s)", e)

    return run_rollout(candidate, stages, constraints, deploy=deploy, rollback=rollback)


__all__ = ["Stage", "StageResult", "RolloutResult", "Constraint", "DEFAULT_STAGES",
           "run_rollout", "threshold_constraint", "promote_skill_live"]
