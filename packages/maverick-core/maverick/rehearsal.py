"""Pre-execution rehearsal -- the governance half of the Operating Twin.

The same world-model that powers counterfactual *credit* (``counterfactual_rollout``)
also powers counterfactual *foresight*: before an agent commits a risky plan,
rehearse it against the model and gate on what the model predicts.

The point is to flip governance from a brake into a capability. A blanket
approval gate slows *every* high-risk action equally. Rehearsal lets the agent be
**bold where the twin is confident it's safe**, and escalates only where the
prediction is poor or -- crucially -- where the twin *doesn't know*. The
world-model admitting its own ignorance is the whole safety case: an action in a
state/with an action the model has never seen is not waved through and not
silently blocked; it is escalated to a human / canary, because a simulator that
bluffs is worse than no simulator.

``rehearse`` is a pure function over a fitted
:class:`~maverick.counterfactual_rollout.TransitionModel`: it Monte-Carlo rolls
the plan forward and returns a :class:`RehearsalVerdict` with the predicted
outcome, an uncertainty (epistemic = no support; aleatoric = rollout spread), and
a gate decision. ``gate_action`` is the governed entry point.

Posture (kernel rule 1): OFF by default. When off, ``gate_action`` is a no-op
that returns ``proceed`` (fail-open -- a disabled safety aid never blocks a run).
When ON it fails toward caution: an unknown context, an over-uncertain rollout,
or an internal error escalates rather than proceeding; a confidently-poor
prediction blocks. Thresholds come from ``[rehearsal]`` config so the wizard can
tune them. Pure, dependency-free, deterministic given a seed.
"""
from __future__ import annotations

import logging
import math
import random
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

from .config import env_flag

log = logging.getLogger(__name__)

PROCEED = "proceed"
ESCALATE = "escalate"
BLOCK = "block"

_DEFAULTS = {
    "enable": False,
    "outcome_floor": 0.5,    # predicted outcome below this (when confident) -> block
    "min_support": 5,        # (state, action) observations needed to "know"
    "max_uncertainty": 0.25, # rollout std above this -> escalate
    "horizon": 8,
    "rollouts": 200,
}


@dataclass(frozen=True)
class RehearsalVerdict:
    """What the twin foresees for a plan, and the gate decision it implies."""

    decision: str            # PROCEED | ESCALATE | BLOCK
    predicted_outcome: float # E[Y] under the plan (smoothed prior when unknown)
    uncertainty: float       # 0..1; 1.0 when the model has no support (unknown)
    support: int             # model support for (state, first action)
    known: bool              # whether support cleared the floor
    reason: str = ""

    @property
    def proceed(self) -> bool:
        return self.decision == PROCEED


def _settings() -> dict:
    try:
        from .config import get_rehearsal

        return get_rehearsal()
    except Exception:  # pragma: no cover -- config never blocks a run
        return dict(_DEFAULTS)


def enabled() -> bool:
    """Whether rehearsal may gate actions. OFF by default, fail-open."""
    _v = env_flag("MAVERICK_REHEARSAL")
    if _v is not None:
        return _v
    return bool(_settings().get("enable", False))


def rehearse(
    model,
    state: tuple,
    plan: Sequence[Hashable],
    *,
    outcome_floor: float = 0.5,
    min_support: int = 5,
    max_uncertainty: float = 0.25,
    horizon: int = 8,
    rollouts: int = 200,
    seed: int = 0,
) -> RehearsalVerdict:
    """Rehearse ``plan`` from ``state`` against the world-model (pure)."""
    plan = list(plan)
    if not plan:
        return RehearsalVerdict(ESCALATE, 0.5, 1.0, 0, False, "empty plan")

    support = model.support(state, plan[0])
    known = support >= min_support
    if not known:
        # The twin has never seen this move here -> it cannot vouch for it.
        return RehearsalVerdict(
            ESCALATE, 0.5, 1.0, support, False,
            "world-model has no support for this action in this state",
        )

    rng = random.Random(seed)
    outcomes = [model.rollout_plan(state, plan, horizon=horizon, rng=rng)
                for _ in range(rollouts)]
    n = len(outcomes)
    mean = sum(outcomes) / n
    std = math.sqrt(sum((o - mean) ** 2 for o in outcomes) / n)

    if std > max_uncertainty:
        return RehearsalVerdict(
            ESCALATE, mean, std, support, True,
            f"rehearsal outcome too uncertain (std {std:.3f} > {max_uncertainty:.3f})",
        )
    if mean < outcome_floor:
        return RehearsalVerdict(
            BLOCK, mean, std, support, True,
            f"rehearsal predicts a poor outcome ({mean:.3f} < floor {outcome_floor:.3f})",
        )
    return RehearsalVerdict(
        PROCEED, mean, std, support, True,
        f"rehearsal predicts a good, confident outcome ({mean:.3f})",
    )


def gate_action(model, state: tuple, plan: Sequence[Hashable], *, seed: int = 0) -> RehearsalVerdict:
    """Governed entry point. No-op (``proceed``) while disabled; fails toward
    caution (``escalate``) on any internal error when enabled."""
    if not enabled():
        return RehearsalVerdict(PROCEED, 0.5, 0.0, 0, False, "rehearsal disabled")
    s = _settings()
    try:
        return rehearse(
            model, state, plan, seed=seed,
            outcome_floor=float(s.get("outcome_floor", 0.5)),
            min_support=int(s.get("min_support", 5)),
            max_uncertainty=float(s.get("max_uncertainty", 0.25)),
            horizon=int(s.get("horizon", 8)),
            rollouts=int(s.get("rollouts", 200)),
        )
    except Exception:  # pragma: no cover -- a safety aid that errors must not bluff
        log.warning("rehearsal errored; escalating for safety", exc_info=True)
        return RehearsalVerdict(ESCALATE, 0.5, 1.0, 0, False, "rehearsal error")


__all__ = [
    "RehearsalVerdict",
    "PROCEED",
    "ESCALATE",
    "BLOCK",
    "enabled",
    "rehearse",
    "gate_action",
]
