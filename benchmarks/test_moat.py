"""Tests for the compounding-moat benchmark.

The measurement pipeline is exercised with a scripted runner so it runs
offline (no API spend) while proving the cold/warm orchestration, the
delta math, the aggregate, and the report rendering.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

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
    run_with_maverick,
)


def _install_fake_maverick(monkeypatch, sandbox):
    """Install tiny fake maverick modules for run_with_maverick tests."""
    calls = {}

    class FakeBudget:
        def __init__(self, max_dollars):
            self.max_dollars = max_dollars
            self.dollars = 0.0
            self.tool_calls = 0

    class FakeLLM:
        pass

    class FakeWorldModel:
        def __init__(self, path):
            self.path = path

        def create_goal(self, _title, _text):
            return "goal-1"

        def list_episodes(self, goal_id, limit):
            calls["listed"] = (goal_id, limit)
            return []

    class FakeLocalBackend:
        pass

    def fake_run_goal_sync(**kwargs):
        calls["run_kwargs"] = kwargs
        calls["learning_env"] = {
            key: os.environ.get(key)
            for key in (
                "MAVERICK_USE_SKILLS",
                "MAVERICK_REFLEXION",
                "MAVERICK_AUTO_DISTILL",
            )
        }

    def fake_build_sandbox():
        return sandbox

    maverick_pkg = types.ModuleType("maverick")
    maverick_pkg.__path__ = []
    budget_mod = types.ModuleType("maverick.budget")
    budget_mod.Budget = FakeBudget
    llm_mod = types.ModuleType("maverick.llm")
    llm_mod.LLM = FakeLLM
    orchestrator_mod = types.ModuleType("maverick.orchestrator")
    orchestrator_mod.run_goal_sync = fake_run_goal_sync
    sandbox_mod = types.ModuleType("maverick.sandbox")
    sandbox_mod.LocalBackend = FakeLocalBackend
    sandbox_mod.build_sandbox = fake_build_sandbox
    world_model_mod = types.ModuleType("maverick.world_model")
    world_model_mod.WorldModel = FakeWorldModel

    for name, module in {
        "maverick": maverick_pkg,
        "maverick.budget": budget_mod,
        "maverick.llm": llm_mod,
        "maverick.orchestrator": orchestrator_mod,
        "maverick.sandbox": sandbox_mod,
        "maverick.world_model": world_model_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    return calls, FakeLocalBackend


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


class TestLiveRunnerSandbox:
    def test_live_runner_passes_configured_sandbox_and_restores_learning_env(self, monkeypatch):
        sandbox = object()
        calls, _local_backend = _install_fake_maverick(monkeypatch, sandbox)
        monkeypatch.setenv("MAVERICK_USE_SKILLS", "previous")
        monkeypatch.delenv("MAVERICK_REFLEXION", raising=False)
        monkeypatch.delenv("MAVERICK_AUTO_DISTILL", raising=False)

        metrics = run_with_maverick("inspect the repo", learning_enabled=True)

        assert calls["run_kwargs"]["sandbox"] is sandbox
        assert calls["learning_env"] == {
            "MAVERICK_USE_SKILLS": "1",
            "MAVERICK_REFLEXION": "1",
            "MAVERICK_AUTO_DISTILL": "1",
        }
        assert os.environ["MAVERICK_USE_SKILLS"] == "previous"
        assert "MAVERICK_REFLEXION" not in os.environ
        assert "MAVERICK_AUTO_DISTILL" not in os.environ
        assert metrics == RunMetrics(cost_dollars=0.0, tool_calls=0, wall_seconds=metrics.wall_seconds, success=False)

    def test_live_runner_refuses_local_sandbox_without_explicit_opt_in(self, monkeypatch):
        calls, LocalBackend = _install_fake_maverick(monkeypatch, None)
        local_sandbox = LocalBackend()
        sys.modules["maverick.sandbox"].build_sandbox = lambda: local_sandbox
        monkeypatch.setenv("MAVERICK_REFLEXION", "previous")
        monkeypatch.delenv("MAVERICK_MOAT_ALLOW_LOCAL_SANDBOX", raising=False)

        with pytest.raises(RuntimeError, match="refusing to run.*'local'"):
            run_with_maverick("inspect the repo", learning_enabled=False)

        assert "run_kwargs" not in calls
        assert os.environ["MAVERICK_REFLEXION"] == "previous"

    def test_live_runner_allows_local_sandbox_with_explicit_opt_in(self, monkeypatch):
        calls, LocalBackend = _install_fake_maverick(monkeypatch, None)
        local_sandbox = LocalBackend()
        sys.modules["maverick.sandbox"].build_sandbox = lambda: local_sandbox
        monkeypatch.setenv("MAVERICK_MOAT_ALLOW_LOCAL_SANDBOX", "1")

        run_with_maverick("inspect the repo", learning_enabled=False)

        assert calls["run_kwargs"]["sandbox"] is local_sandbox
        assert calls["learning_env"] == {
            "MAVERICK_USE_SKILLS": "0",
            "MAVERICK_REFLEXION": "0",
            "MAVERICK_AUTO_DISTILL": "0",
        }
