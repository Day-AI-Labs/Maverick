"""The flywheel -- one cycle that turns every engine together.

This is the live wire-up of the Cognitive Data Engine: a single pass over the
captured Operating Record that runs the whole loop, grounded in real outcomes.

    ground   -- prefer the REAL consequence (Consequence Engine) over the verifier
                proxy wherever reality has reported back, so everything below
                learns from what actually happened.
    triage   -- rank failure classes by causal impact (data_engine).
    guard    -- mine self-correcting guardrails from the harmful classes and
                refresh the registry (negative_knowledge).
    remember -- consolidate the beneficial habits into procedural memory, with the
                reinforce/forget curve (procedural_memory / the Hippocampus).
    discover -- propose swaps (harmful -> beneficial) and, if a world-model is
                supplied, validate them in simulation (operations_scientist).

``run_once`` is one turn of the flywheel; scheduled between shifts (``maverick
flywheel`` / a cron / the dashboard) the workforce compounds from its own
experience. OFF by default: ``maybe_run`` is the safe entry point, a no-op empty
report unless ``[data_engine]`` is enabled.

(This supersedes the earlier standalone ``data_engine_runner``: it composes
*every* engine, not just triage->mine.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import (
    consequence,
    data_engine,
    negative_knowledge,
    operations_scientist,
    procedural_memory,
)
from .data_engine import _terminal_outcome


@dataclass(frozen=True)
class FlywheelReport:
    """One turn of the flywheel: what it found, learned, and proposes."""

    n_episodes: int
    failure_classes: tuple = field(default_factory=tuple)   # data_engine.FailureClass
    guardrails: tuple = field(default_factory=tuple)        # negative_knowledge.Guardrail
    memories: tuple = field(default_factory=tuple)          # procedural_memory.Memory
    hypotheses: tuple = field(default_factory=tuple)        # operations_scientist.Hypothesis
    simulations: tuple = field(default_factory=tuple)       # operations_scientist.SimResult
    predicted_lift: float = 0.0   # outcome recoverable from the learned guardrails

    @property
    def acted(self) -> bool:
        return bool(self.guardrails or self.memories or self.hypotheses)


def grounded_outcome_fn():
    """An episode -> outcome resolver that prefers the REAL consequence.

    Falls back to the verifier-confidence proxy where reality hasn't reported back
    (and is a pure proxy passthrough unless ``[consequence]`` is enabled)."""
    def of(ep):
        proxy = _terminal_outcome(ep)
        if not ep:
            return proxy
        s0 = ep[0]
        return consequence.grounded_outcome(s0.goal_id, s0.episode_id, proxy)
    return of


def run_once(steps, *, guardrails=None, memory=None, world_model=None, start_states=None,
             failure_threshold: float = 0.5, min_support: int = 8,
             top_k: int = 10) -> FlywheelReport:
    """One grounded turn of the flywheel (pure -- always computes)."""
    steps = list(steps)
    n_eps = len({(s.goal_id, s.episode_id) for s in steps})
    outcome_fn = grounded_outcome_fn()

    classes = data_engine.triage(
        steps, failure_threshold=failure_threshold, min_support=min_support,
        top_k=top_k, outcome_fn=outcome_fn)

    rails = negative_knowledge.mine(classes)
    (guardrails or negative_knowledge.shared()).update(rails)

    mem_store = memory or procedural_memory.shared()
    mems = procedural_memory.consolidate(
        steps, prior=mem_store.recall(top_k=128), min_support=min_support,
        outcome_fn=outcome_fn)
    mem_store.update(mems)

    hyps = operations_scientist.propose(classes, mems, top_k=top_k)
    sims: tuple = ()
    if world_model is not None and start_states:
        sims = tuple(operations_scientist.simulate(h, world_model, start_states)
                     for h in hyps)

    return FlywheelReport(
        n_episodes=n_eps, failure_classes=tuple(classes), guardrails=tuple(rails),
        memories=tuple(mems), hypotheses=tuple(hyps), simulations=sims,
        predicted_lift=sum(g.severity for g in rails))


def maybe_run() -> FlywheelReport:
    """Governed entry point: turn the flywheel over the captured Operating Record,
    or a no-op (empty report) when ``[data_engine]`` is disabled."""
    if not data_engine.enabled():
        return FlywheelReport(n_episodes=0)
    try:
        from .config import get_data_engine
        from .trajectory_store import shared as traj_shared

        cfg = get_data_engine()
        steps = list(traj_shared().iter_steps())
        return run_once(
            steps,
            failure_threshold=float(cfg.get("failure_threshold", 0.5)),
            min_support=int(cfg.get("min_support", 8)),
            top_k=int(cfg.get("top_k", 10)),
        )
    except Exception:  # pragma: no cover -- a maintenance loop must never crash a run
        return FlywheelReport(n_episodes=0)


__all__ = ["FlywheelReport", "grounded_outcome_fn", "run_once", "maybe_run"]
