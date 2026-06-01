"""Tests for the compounding-moat benchmark.

The measurement pipeline is exercised with a scripted runner so it runs
offline (no API spend) while proving the cold/warm orchestration, the
delta math, the aggregate, and the report rendering.
"""
from __future__ import annotations

import sys
from pathlib import Path

# benchmarks/ is not a package; import the sibling module directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moat import (  # noqa: E402
    DEFAULT_PAIRS,
    MoatResult,
    PairResult,
    RunMetrics,
    TaskPair,
    format_report,
    run_moat_benchmark,
)


def _scripted_runner(cold: RunMetrics, warm: RunMetrics):
    """Returns a run_fn that yields ``cold`` on the cold call (learning
    off) and ``warm`` on the warm call (learning on)."""
    def run_fn(task_text: str, learning_enabled: bool) -> RunMetrics:
        return warm if learning_enabled else cold

    return run_fn


class TestDeltaMath:
    def test_negative_cost_delta_when_warm_cheaper(self):
        cold = RunMetrics(cost_dollars=1.0, tool_calls=10, wall_seconds=100, success=True)
        warm = RunMetrics(cost_dollars=0.6, tool_calls=6, wall_seconds=80, success=True)
        pr = PairResult(name="x", cold=cold, warm=warm)
        assert pr.cost_delta_pct == -40.0
        assert pr.tool_calls_delta_pct == -40.0
        assert pr.wall_delta_pct == -20.0

    def test_zero_baseline_does_not_divide_by_zero(self):
        cold = RunMetrics(cost_dollars=0.0, tool_calls=0, wall_seconds=0, success=False)
        warm = RunMetrics(cost_dollars=0.5, tool_calls=3, wall_seconds=5, success=True)
        pr = PairResult(name="x", cold=cold, warm=warm)
        assert pr.cost_delta_pct == 0.0
        assert pr.tool_calls_delta_pct == 0.0


class TestRunOrchestration:
    def test_cold_then_warm_called_per_pair(self):
        seen = []

        def run_fn(task_text, learning_enabled):
            seen.append((task_text, learning_enabled))
            return RunMetrics(1.0, 5, 10, True)

        pairs = [TaskPair("p", "cold task", "warm task")]
        run_moat_benchmark(pairs, run_fn)
        assert seen == [("cold task", False), ("warm task", True)]

    def test_result_has_one_pairresult_per_pair(self):
        run_fn = _scripted_runner(
            RunMetrics(1.0, 10, 100, True), RunMetrics(0.5, 5, 50, True),
        )
        result = run_moat_benchmark(DEFAULT_PAIRS, run_fn)
        assert len(result.pairs) == len(DEFAULT_PAIRS)


class TestAggregate:
    def _result(self, cold, warm) -> MoatResult:
        run_fn = _scripted_runner(cold, warm)
        return run_moat_benchmark(
            [TaskPair("a", "c", "w"), TaskPair("b", "c", "w")], run_fn,
        )

    def test_moat_demonstrated_when_cheaper_and_reliable(self):
        r = self._result(
            RunMetrics(1.0, 10, 100, True), RunMetrics(0.4, 4, 60, True),
        )
        assert r.mean_cost_delta_pct == -60.0
        assert r.cold_success_rate == 1.0
        assert r.warm_success_rate == 1.0
        assert r.moat_demonstrated is True

    def test_moat_not_demonstrated_when_warm_more_expensive(self):
        r = self._result(
            RunMetrics(0.5, 5, 50, True), RunMetrics(0.9, 9, 90, True),
        )
        assert r.mean_cost_delta_pct > 0
        assert r.moat_demonstrated is False

    def test_moat_not_demonstrated_when_warm_less_reliable(self):
        # Cheaper but the warm run failed -> not a moat.
        r = self._result(
            RunMetrics(1.0, 10, 100, True), RunMetrics(0.3, 3, 30, False),
        )
        assert r.mean_cost_delta_pct < 0
        assert r.warm_success_rate < r.cold_success_rate
        assert r.moat_demonstrated is False


class TestReport:
    def test_report_contains_table_and_verdict(self):
        run_fn = _scripted_runner(
            RunMetrics(1.0, 10, 100, True), RunMetrics(0.5, 5, 50, True),
        )
        result = run_moat_benchmark([TaskPair("demo", "c", "w")], run_fn)
        report = format_report(result)
        assert "Compounding-moat benchmark" in report
        assert "| demo |" in report
        assert "Moat demonstrated" in report

    def test_empty_result_is_safe(self):
        result = MoatResult(pairs=[])
        assert result.mean_cost_delta_pct == 0.0
        assert result.cold_success_rate == 0.0
        assert result.moat_demonstrated is False
        # Report still renders.
        assert "Compounding-moat benchmark" in format_report(result)
