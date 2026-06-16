"""The Cognitive Data Engine -- causal failure triage (the crank's first stage).

The Tesla autopilot data engine, reborn for a governed AI workforce: production
failures become causally-prioritised, simulation-validated, governance-gated
improvements. This module is the crank's first stage -- turn the raw (opt-in)
trajectory corpus into a RANKED queue of failure classes, ordered by how much
fixing each would lift *real outcomes*.

The whole value of a data engine is **triage**: you can't fix everything, so you
fix the failure that moves reality most. The naive move -- rank by frequency --
is a trap (the most common failure is often harmless noise). So this ranks by
**causal impact**: for each candidate action, estimate its confounder-adjusted
effect on the episode outcome (reusing ``promotion_effect``); the actions that
*provably lower* outcomes, by the most, with confidence, are the top of the
queue. Each class carries failing exemplars for the downstream fix-miner.

Pure + dependency-free + OFF by default (reads only the opt-in trajectory store;
``triage`` on an empty corpus returns ``[]``). The later crank stages
(fix-mining, sim-validation, promotion, real-outcome measurement) build on this.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import promotion_effect as pe


@dataclass(frozen=True)
class FailureClass:
    """A causally-harmful action pattern, ranked for the fix-miner."""

    action: str                 # the tool/action that characterises the class
    count: int                  # failing episodes (outcome < threshold) using it
    mean_outcome: float         # mean terminal outcome of episodes using it
    causal_effect: float        # confounder-adjusted effect on outcome (<0 = hurts)
    ci_low: float
    ci_high: float
    trustworthy: bool           # the estimate cleared the calibration bar
    exemplars: tuple = field(default_factory=tuple)  # (goal_id, episode_id) for fix-mining


def enabled() -> bool:
    """Whether the data engine may run. OFF by default, fail-open."""
    env = os.environ.get("MAVERICK_DATA_ENGINE", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_data_engine

        return bool(get_data_engine().get("enable", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _terminal_outcome(ep) -> float | None:
    """The episode's real outcome: the terminal ``outcome`` (the verifier's
    confidence in the final answer), else the final step's verifier_confidence."""
    for s in reversed(ep):
        if getattr(s, "outcome", None) is not None:
            return float(s.outcome)
        if s.is_final and getattr(s, "verifier_confidence", None) is not None:
            return float(s.verifier_confidence)
    return None


def _episode_role(ep) -> str:
    return next((s.role for s in ep if s.role), "")


def triage(steps, *, failure_threshold: float = 0.5, min_support: int = 8,
           top_k: int = 10) -> list[FailureClass]:
    """Rank candidate actions by how much they causally hurt task outcome.

    For each distinct tool, estimate the confounder-adjusted effect of using it on
    the episode outcome (treatment = episode used the tool, stratum = domain).
    Classes with a *negative* effect are causally harmful; they're ranked by their
    upper confidence bound ascending (most confidently harmful first), with
    trustworthy estimates ahead of untrustworthy ones.
    """
    steps = list(steps)
    if not steps:
        return []

    # Group once so we can attach counts + exemplars without re-scanning per tool.
    episodes: dict = {}
    for s in steps:
        episodes.setdefault((s.goal_id, s.episode_id), []).append(s)
    ordered = {k: sorted(v, key=lambda s: s.step) for k, v in episodes.items()}

    tools = {s.tool for s in steps if s.tool}
    out: list[FailureClass] = []
    for tool in tools:
        units = pe.units_from_trajectories(
            steps,
            treatment_fn=lambda ep, t=tool: 1 if any(s.tool == t for s in ep) else 0,
            outcome_fn=_terminal_outcome,
            stratum_fn=lambda ep: (ep[0].domain,),
        )
        est = pe.estimate_effect(units, adjusted_for=("domain",), min_used=min_support)
        if est.effect >= 0:
            continue  # this action doesn't causally lower outcomes -> not a failure class

        used, fail_outcomes, exemplars = 0, [], []
        for key, ep in ordered.items():
            if not any(s.tool == tool for s in ep):
                continue
            y = _terminal_outcome(ep)
            if y is None:
                continue
            used += 1
            fail_outcomes.append(y)
            if y < failure_threshold:
                exemplars.append(key)
        mean_outcome = sum(fail_outcomes) / len(fail_outcomes) if fail_outcomes else 0.0
        out.append(FailureClass(
            action=tool, count=sum(1 for y in fail_outcomes if y < failure_threshold),
            mean_outcome=mean_outcome, causal_effect=est.effect,
            ci_low=est.ci_low, ci_high=est.ci_high, trustworthy=est.trustworthy,
            exemplars=tuple(exemplars[:20]),
        ))

    # Most confidently harmful first; trustworthy estimates outrank shaky ones.
    out.sort(key=lambda c: (not c.trustworthy, c.ci_high))
    return out[:top_k]


__all__ = ["FailureClass", "enabled", "triage"]
