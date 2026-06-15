"""Tests for the compounding metric (cold -> warm improvement signal)."""
from __future__ import annotations

from maverick.compounding_metric import Row, compute, report_from_world


def _rows(cls, costs, successes=None):
    successes = successes or [True] * len(costs)
    return [Row(task_class=cls, cost=c, success=s, ts=float(i))
            for i, (c, s) in enumerate(zip(costs, successes))]


def test_improving_class_is_flagged():
    # Cost falls from ~2.0 to ~0.5 over time, reliability holds.
    rows = _rows("research", [2.0, 2.1, 1.9, 1.0, 0.6, 0.5])
    [rep] = compute(rows, window=2, min_runs=4)
    assert rep.improving
    assert rep.cost_delta_pct < 0  # warm cheaper
    assert rep.success_delta >= 0


def test_non_improving_class_is_not_flagged():
    rows = _rows("flaky", [0.5, 0.6, 1.9, 2.0])  # got more expensive
    [rep] = compute(rows, window=2, min_runs=4)
    assert not rep.improving
    assert rep.cost_delta_pct > 0


def test_reliability_regression_blocks_improving():
    # Cheaper but less reliable -> NOT improving (the guard that matters).
    rows = _rows("risky", [2.0, 2.0, 0.5, 0.5], successes=[True, True, False, False])
    [rep] = compute(rows, window=2, min_runs=4)
    assert not rep.improving


def test_thin_classes_are_skipped():
    assert compute(_rows("x", [1.0, 1.0]), min_runs=4) == []


class _Ep:
    def __init__(self, cost, outcome, ts):
        self.cost_dollars, self.outcome, self.started_at = cost, outcome, ts


class _Goal:
    def __init__(self, gid, title):
        self.id, self.title, self.domain = gid, title, ""


class _World:
    def __init__(self):
        self._g = [_Goal(i, "research thing") for i in range(6)]
        self._e = {i: [_Ep(2.0 - i * 0.3, "done", float(i))] for i in range(6)}

    def list_goals(self, *, limit=2000):
        return self._g

    def list_episodes(self, *, goal_id):
        return self._e[goal_id]


def test_report_from_world_groups_by_verb():
    reps = report_from_world(_World(), window=2, min_runs=4)
    assert reps and reps[0].task_class == "research"
    assert reps[0].improving
