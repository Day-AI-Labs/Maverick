"""Offline tests for the rigorous moat aggregation -- pure, no API key, runs
in CI. Guards the methodology: the "warm never worse than cold" rate, the
median-is-robust-to-outliers headline, success parity, and the honest claim
selector that must never over-state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moat_rigorous as MR  # noqa: E402
from moat import RunMetrics  # noqa: E402


def _obs(name, seed, warm_cost, cold_cost, warm_ok=True, cold_ok=True,
         warm_correct=None, cold_correct=None):
    return MR.Observation(
        name=name, seed=seed,
        warm=RunMetrics(cost_dollars=warm_cost, tool_calls=0, wall_seconds=0.0, success=warm_ok),
        cold=RunMetrics(cost_dollars=cold_cost, tool_calls=0, wall_seconds=0.0, success=cold_ok),
        warm_correct=warm_correct, cold_correct=cold_correct,
    )


def test_not_worse_and_cheaper_counts():
    r = MR.aggregate([
        _obs("a", 0, 0.5, 1.0),   # warm much cheaper -> not-worse + cheaper
        _obs("b", 0, 1.0, 1.0),   # equal           -> not-worse, not cheaper
        _obs("c", 0, 1.04, 1.0),  # +4% within tol  -> not-worse, not cheaper
        _obs("d", 0, 1.5, 1.0),   # +50% worse      -> neither
    ])
    assert r.not_worse_count == 3
    assert r.cheaper_count == 1
    assert r.not_worse_rate == 0.75


def test_median_is_robust_to_a_single_outlier():
    # Three runs where warm is cheaper, one pathological outlier. The MEAN is
    # dragged positive (the trap the old benchmark fell into); the MEDIAN still
    # reports the typical case (warm cheaper). This is why median is the headline.
    r = MR.aggregate([
        _obs("a", 0, 0.5, 1.0),  # -50%
        _obs("b", 0, 0.6, 1.0),  # -40%
        _obs("c", 0, 0.7, 1.0),  # -30%
        _obs("d", 0, 5.0, 1.0),  # +400% outlier
    ])
    assert r.median_cost_delta_pct == -35.0   # robust: typically cheaper
    assert r.mean_cost_delta_pct == 70.0      # fragile: outlier-driven positive
    # the outlier correctly breaks the bounded guarantee (not every run not-worse)
    assert r.not_worse_count == 3
    assert r.bounded_moat_demonstrated is False


def test_bounded_moat_requires_every_observation_not_worse():
    good = MR.aggregate([_obs("a", 0, 0.9, 1.0), _obs("a", 1, 1.02, 1.0)])
    assert good.not_worse_count == good.n
    assert good.bounded_moat_demonstrated is True
    bad = MR.aggregate([_obs("a", 0, 0.9, 1.0), _obs("a", 1, 1.5, 1.0)])
    assert bad.bounded_moat_demonstrated is False


def test_cheaper_moat_requires_negative_median():
    # All within tolerance (bounded holds) but median >= 0 -> "does no harm",
    # NOT "typically cheaper".
    bounded_only = MR.aggregate([
        _obs("a", 0, 1.0, 1.0), _obs("b", 0, 1.03, 1.0),
        _obs("c", 0, 0.99, 1.0), _obs("d", 0, 1.04, 1.0),
    ])
    assert bounded_only.bounded_moat_demonstrated is True
    assert bounded_only.cheaper_moat_demonstrated is False
    assert "never worse than cold" in MR.claim(bounded_only)


def test_success_regression_breaks_bounded_even_if_cheaper():
    # Warm is cheaper but LESS reliable -> learning cost reliability -> not a moat.
    r = MR.aggregate([_obs("a", 0, 0.5, 1.0, warm_ok=False, cold_ok=True)])
    assert r.warm_success_rate < r.cold_success_rate
    assert r.bounded_moat_demonstrated is False


def test_claim_picks_the_strongest_supported_wording():
    cheaper = MR.aggregate([_obs("a", 0, 0.5, 1.0), _obs("b", 0, 0.6, 1.0)])
    assert "typically cheaper" in MR.claim(cheaper)

    not_demo = MR.aggregate([_obs("a", 0, 2.0, 1.0), _obs("b", 0, 0.5, 1.0)])
    assert "NOT demonstrated" in MR.claim(not_demo)

    empty = MR.aggregate([])
    assert "No valid observations" in MR.claim(empty)


def test_orchestration_calls_runner_per_pair_and_seed():
    calls = []

    def fake_runner(pair, seed):
        calls.append((pair.name, seed))
        # warm always a touch cheaper than cold in this fake
        return (RunMetrics(0.8, 1, 1.0, True), RunMetrics(1.0, 2, 1.5, True))

    pairs = [MR.PairSpec("p1", "A1", "B1"), MR.PairSpec("p2", "A2", "B2")]
    result = MR.run_moat_rigorous(pairs, seeds=2, pair_run_fn=fake_runner)
    assert len(calls) == 4                      # 2 pairs x 2 seeds
    assert result.n == 4
    assert result.bounded_moat_demonstrated is True


def test_correctness_regression_blocks_moat_and_claim():
    # Warm is cheaper but LESS correct than cold -> not a moat; claim says STOP.
    r = MR.aggregate([
        _obs("a", 0, 0.5, 1.0, warm_correct=False, cold_correct=True),
        _obs("b", 0, 0.5, 1.0, warm_correct=True, cold_correct=True),
    ])
    assert r.warm_correct_rate == 0.5 and r.cold_correct_rate == 1.0
    assert r.correctness_regressed is True
    assert r.bounded_moat_demonstrated is False
    assert "hurt correctness" in MR.claim(r)


def test_correctness_parity_allows_moat():
    r = MR.aggregate([
        _obs("a", 0, 0.5, 1.0, warm_correct=True, cold_correct=True),
        _obs("b", 0, 0.6, 1.0, warm_correct=True, cold_correct=False),
    ])
    assert r.correctness_regressed is False
    assert r.bounded_moat_demonstrated is True  # cheaper AND correctness not worse


def test_ungraded_correctness_is_neutral():
    # No grader -> correctness rates None -> never blocks (back-compat).
    r = MR.aggregate([_obs("a", 0, 0.8, 1.0)])
    assert r.warm_correct_rate is None and r.cold_correct_rate is None
    assert r.correctness_regressed is False
    assert r.bounded_moat_demonstrated is True


def test_format_report_renders_table_and_claim():
    r = MR.aggregate([_obs("auth->authz", 0, 0.8, 1.0)])
    report = MR.format_report(r)
    assert "# Rigorous compounding-moat benchmark" in report
    assert "auth->authz" in report
    assert "**Claim:**" in report
