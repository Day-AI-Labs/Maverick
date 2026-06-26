"""Deconfounded effect estimation for the promotion ladder.

The self-improvement controller promotes a change when its evidence beats
baseline (``candidate_score - baseline_score``). Today that evidence is a
*correlational* aggregate -- a tool's raw success rate, a before/after eval mean
-- and in a system that rewrites **itself**, correlational credit is a
superstition pump: a change that merely co-occurs with success (because it was
tried on easier sub-goals, or alongside the decision that actually mattered)
gets promoted, reinforced, and compounded.

This module turns that evidence from a correlation into a **causal effect**. It
estimates the effect of a candidate change on task outcome from the logged
trajectory population, adjusting for confounders by *stratification*: within each
cell of comparable context, compare treated vs untreated outcomes, then average
the per-cell effects weighted by cell size (the subclassification estimator). A
cell with no overlap (only treated, or only untreated) carries no causal
information and is dropped -- and the fraction of data we *can* compare on
(``overlap``) is reported, never hidden.

It is deliberately distinct from :mod:`maverick.credit` (CSCA), which does
*online, per-swarm* leave-one-out Shapley credit for sub-agents. This is
*offline, corpus-level* effect estimation for **promotion** decisions, and the
two compose (CSCA can weight which sub-trajectories feed this estimator).

Posture (kernel rule 1): OFF by default. The estimator is a pure function
(usable anywhere), but the controller only consults a causal effect when the
``[self_improvement] causal_promotion`` knob is on. Crucially it is **fail-safe
by calibration**: an estimate built on too little overlap, or one that leaks a
non-zero effect under a placebo (treatment permuted within strata, which *must*
be ~0), is marked ``trustworthy=False`` -- and the producer refuses to promote
on an untrustworthy estimate. Promote only what you can show *caused* the win.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .config import env_flag

# Two-sided 95% normal quantile.
_Z95 = 1.959963984540054
_PLACEBO_PERMUTATIONS = 64


@dataclass(frozen=True)
class Unit:
    """One episode reduced to a causal record.

    ``treatment`` is 1 when the candidate change was present, 0 when absent;
    ``outcome`` is the episode's task outcome in [0, 1] (e.g. the terminal
    verifier confidence / success label); ``stratum`` is the confounder cell --
    a hashable key of the comparable-context features (domain, depth bucket,
    ...). Episodes only compare *within* a stratum.
    """

    treatment: int
    outcome: float
    stratum: tuple


@dataclass(frozen=True)
class EffectEstimate:
    """A confounder-adjusted effect with everything needed to trust (or not) it."""

    effect: float
    ci_low: float
    ci_high: float
    n_used: int
    n_total: int
    strata_used: int
    overlap: float
    naive_effect: float
    placebo_effect: float
    trustworthy: bool
    adjusted_for: tuple[str, ...] = field(default_factory=tuple)


def enabled() -> bool:
    """Whether the controller should consult causal effects. OFF by default."""
    _v = env_flag("MAVERICK_CAUSAL_PROMOTION")
    if _v is not None:
        return _v
    try:
        from .config import get_self_improvement

        return bool(get_self_improvement().get("causal_promotion", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _mean_var(xs: list[float]) -> tuple[float, float, int]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / n
    return m, v, n


def _strata(units: list[Unit]) -> dict:
    """Group outcomes by stratum and treatment arm."""
    out: dict = {}
    for u in units:
        arms = out.setdefault(u.stratum, ([], []))  # (control, treated)
        arms[1 if u.treatment else 0].append(float(u.outcome))
    return out


def _stratified_ate(strata: dict) -> tuple[float, float, int, int]:
    """Subclassification ATE + its variance over overlapping strata.

    Returns ``(ate, variance, n_used, strata_used)``. Only strata with both a
    treated and a control observation contribute (positivity / overlap).
    """
    weighted_effect = 0.0
    weighted_var = 0.0
    total_w = 0
    strata_used = 0
    for control, treated in strata.values():
        if not control or not treated:
            continue  # no overlap in this cell -> no causal information
        m1, v1, n1 = _mean_var(treated)
        m0, v0, n0 = _mean_var(control)
        w = n1 + n0
        tau = m1 - m0
        # Variance of the difference of means within the stratum.
        var_s = (v1 / n1 if n1 else 0.0) + (v0 / n0 if n0 else 0.0)
        weighted_effect += w * tau
        weighted_var += (w ** 2) * var_s
        total_w += w
        strata_used += 1
    if total_w == 0:
        return 0.0, 0.0, 0, 0
    ate = weighted_effect / total_w
    var = weighted_var / (total_w ** 2)
    return ate, var, total_w, strata_used


def _naive_difference(units: list[Unit]) -> float:
    treated = [u.outcome for u in units if u.treatment]
    control = [u.outcome for u in units if not u.treatment]
    m1, _, n1 = _mean_var(treated)
    m0, _, n0 = _mean_var(control)
    if n1 == 0 or n0 == 0:
        return 0.0
    return m1 - m0


def _placebo_effect(strata: dict, *, seed: int, permutations: int = _PLACEBO_PERMUTATIONS) -> float:
    """Mean ATE after permuting treatment labels *within* each stratum.

    Permuting inside strata preserves the confounding structure but severs any
    real treatment->outcome link, so a faithful estimator must return ~0. A
    materially non-zero placebo means the estimate is an artifact, not an effect.
    """
    rng = random.Random(seed)
    # Only overlapping strata matter (they're the ones that carry the estimate).
    pools = [
        (control + treated, len(treated))
        for control, treated in strata.values()
        if control and treated
    ]
    if not pools:
        return 0.0
    acc = 0.0
    for _ in range(permutations):
        weighted_effect = 0.0
        total_w = 0
        for pool, n1 in pools:
            shuffled = pool[:]
            rng.shuffle(shuffled)
            fake_treated = shuffled[:n1]
            fake_control = shuffled[n1:]
            m1, _, _ = _mean_var(fake_treated)
            m0, _, _ = _mean_var(fake_control)
            w = len(pool)
            weighted_effect += w * (m1 - m0)
            total_w += w
        acc += weighted_effect / total_w if total_w else 0.0
    return acc / permutations


def estimate_effect(
    units: list[Unit],
    *,
    adjusted_for: tuple[str, ...] = (),
    min_overlap: float = 0.5,
    min_used: int = 8,
    placebo_tol: float = 0.05,
    placebo_seed: int = 0,
) -> EffectEstimate:
    """Estimate the confounder-adjusted effect of a change on task outcome.

    ``trustworthy`` is the calibration gate: it requires enough overlapping data
    (``overlap >= min_overlap`` and ``n_used >= min_used``) and a placebo effect
    within ``placebo_tol`` of zero. The producer refuses to promote when it is
    False (fail-closed).
    """
    n_total = len(units)
    if n_total == 0:
        return EffectEstimate(0.0, 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, False, adjusted_for)
    strata = _strata(units)
    ate, var, n_used, strata_used = _stratified_ate(strata)
    half = _Z95 * math.sqrt(var) if var > 0 else 0.0
    overlap = n_used / n_total if n_total else 0.0
    placebo = _placebo_effect(strata, seed=placebo_seed)
    trustworthy = (
        n_used >= min_used
        and overlap >= min_overlap
        and strata_used >= 1
        and abs(placebo) <= placebo_tol
    )
    return EffectEstimate(
        effect=ate,
        ci_low=ate - half,
        ci_high=ate + half,
        n_used=n_used,
        n_total=n_total,
        strata_used=strata_used,
        overlap=overlap,
        naive_effect=_naive_difference(units),
        placebo_effect=placebo,
        trustworthy=trustworthy,
        adjusted_for=tuple(adjusted_for),
    )


def units_from_trajectories(
    steps,
    *,
    treatment_fn,
    outcome_fn,
    stratum_fn,
) -> list[Unit]:
    """Build causal units from a flat trajectory step stream (one per episode).

    ``steps`` is any iterable of :class:`maverick.trajectory_store.TrajectoryStep`
    (e.g. ``store.iter_steps()``). Steps are grouped by ``(goal_id, episode_id)``;
    each callback receives that episode's ordered steps and returns the
    treatment (0/1 or None to skip), the outcome (float or None to skip), and the
    stratum key. Episodes where any callback returns None are dropped.
    """
    episodes: dict = {}
    for s in steps:
        episodes.setdefault((s.goal_id, s.episode_id), []).append(s)
    units: list[Unit] = []
    for key in episodes:
        ep = sorted(episodes[key], key=lambda s: s.step)
        t = treatment_fn(ep)
        y = outcome_fn(ep)
        stratum = stratum_fn(ep)
        if t is None or y is None or stratum is None:
            continue
        units.append(Unit(treatment=1 if t else 0, outcome=float(y), stratum=tuple(stratum)))
    return units


__all__ = [
    "Unit",
    "EffectEstimate",
    "enabled",
    "estimate_effect",
    "units_from_trajectories",
]
