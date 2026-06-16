"""The Cognitive Data Engine -- the crank that turns.

Stages 1-2 (:mod:`maverick.data_engine` triage, :mod:`maverick.negative_knowledge`
fix-mining) are the parts; this is the loop that runs them as one pass over the
captured Operating Record:

    failures  ->  causal triage  ->  mine guardrails  ->  update the registry
              ->  a report (which failures, which rules, the outcome we'd recover)

One ``run_once`` is one turn of the flywheel. Scheduled (a cron / the dashboard /
``maverick`` CLI) it runs between shifts and the workforce compounds from its own
experience -- the Tesla data-engine loop, governed. Later stages drop in here
without changing the shape: **sim-validation** (rehearse a candidate fix in the
world-model before it ships) and **real-outcome measurement** (the Consequence
labeler closes the loop on whether the fix actually lifted reality).

Posture (kernel rule 1): OFF by default. :func:`maybe_run` is the safe entry
point -- a no-op (empty report) unless ``[data_engine]`` is enabled. ``run_once``
is the pure crank (always computes) so it's directly testable; a default
deployment never calls it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import data_engine, negative_knowledge


@dataclass(frozen=True)
class DataEngineReport:
    """One turn of the flywheel: what it found, what it learned, the lift at stake."""

    n_episodes: int
    failure_classes: tuple = field(default_factory=tuple)   # data_engine.FailureClass, ranked
    guardrails: tuple = field(default_factory=tuple)        # negative_knowledge.Guardrail
    predicted_lift: float = 0.0   # outcome recoverable if the learned harms are avoided

    @property
    def acted(self) -> bool:
        return bool(self.guardrails)


def run_once(steps, *, registry=None, failure_threshold: float = 0.5,
             min_support: int = 8, top_k: int = 10) -> DataEngineReport:
    """One pass: triage the corpus, mine guardrails, update the registry, report.

    Pure crank -- always computes (the enabled() gate lives in :func:`maybe_run`).
    """
    steps = list(steps)
    n_eps = len({(s.goal_id, s.episode_id) for s in steps})
    classes = data_engine.triage(
        steps, failure_threshold=failure_threshold, min_support=min_support, top_k=top_k)
    rails = negative_knowledge.mine(classes)
    (registry or negative_knowledge.shared()).update(rails)
    predicted_lift = sum(g.severity for g in rails)
    return DataEngineReport(
        n_episodes=n_eps, failure_classes=tuple(classes), guardrails=tuple(rails),
        predicted_lift=predicted_lift)


def maybe_run(*, registry=None) -> DataEngineReport:
    """Governed entry point: run a turn over the captured Operating Record, or a
    no-op (empty report) when ``[data_engine]`` is disabled. Reads the opt-in
    trajectory store; safe to schedule unconditionally."""
    if not data_engine.enabled():
        return DataEngineReport(n_episodes=0)
    try:
        from .config import get_data_engine
        from .trajectory_store import shared as traj_shared

        cfg = get_data_engine()
        return run_once(
            traj_shared().iter_steps(), registry=registry,
            failure_threshold=float(cfg.get("failure_threshold", 0.5)),
            min_support=int(cfg.get("min_support", 8)),
            top_k=int(cfg.get("top_k", 10)),
        )
    except Exception:  # pragma: no cover -- a maintenance loop must never crash a run
        return DataEngineReport(n_episodes=0)


__all__ = ["DataEngineReport", "run_once", "maybe_run"]
