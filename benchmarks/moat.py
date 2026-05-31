"""Compounding-moat benchmark: does Maverick get better at a task the
SECOND time it sees it?

This is the benchmark for Maverick's core differentiator vs. stateless
agents (OpenAI/Google assistants): a persistent world model + skill
auto-distillation + reflexion. The claim is that a warm agent — one that
has already done a similar task and retained what it learned — solves the
next one more cheaply and/or more reliably than a cold agent starting
from scratch.

The benchmark makes that claim *measurable*:

  * COLD phase: run each task against a fresh world model with learning
    OFF (no skills, no reflexion). This is the stateless baseline — what a
    memoryless competitor does on every request.
  * WARM phase: run a SIMILAR task against the SAME world model with
    learning ON, so the agent can recall the distilled skill / reflexion
    from the cold phase.

It then reports the deltas: cost, tool calls, wall time, and success
rate. A real moat shows a negative cost/tool delta (cheaper) and a
non-negative success delta (no worse, ideally better) on the warm phase.

Design: all measurement logic is pure and takes an injected ``run_fn``,
so the pipeline is fully testable offline (see ``benchmarks/test_moat.py``)
without spending a cent. ``run_with_maverick`` wires the real kernel for
live runs that require ``ANTHROPIC_API_KEY``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class RunMetrics:
    """Outcome of one task run, as read from the world model episode."""
    cost_dollars: float
    tool_calls: int
    wall_seconds: float
    success: bool


# A runner takes (task_text, learning_enabled) and returns RunMetrics.
# ``learning_enabled`` toggles skills + reflexion + world-model recall.
RunFn = Callable[[str, bool], RunMetrics]


@dataclass
class TaskPair:
    """A cold task and a SIMILAR warm task. The warm task should be
    solvable by recalling what the cold task taught — same shape,
    different specifics — not a verbatim repeat (that would measure cache,
    not learning)."""
    name: str
    cold_task: str
    warm_task: str


@dataclass
class PairResult:
    name: str
    cold: RunMetrics
    warm: RunMetrics

    def _delta_pct(self, cold_v: float, warm_v: float) -> float:
        """Signed percentage change warm-vs-cold. Negative = warm is
        cheaper/fewer. Guards divide-by-zero (returns 0.0 when the cold
        baseline is 0)."""
        if cold_v == 0:
            return 0.0
        return round((warm_v - cold_v) / cold_v * 100.0, 1)

    @property
    def cost_delta_pct(self) -> float:
        return self._delta_pct(self.cold.cost_dollars, self.warm.cost_dollars)

    @property
    def tool_calls_delta_pct(self) -> float:
        return self._delta_pct(self.cold.tool_calls, self.warm.tool_calls)

    @property
    def wall_delta_pct(self) -> float:
        return self._delta_pct(self.cold.wall_seconds, self.warm.wall_seconds)


@dataclass
class MoatResult:
    pairs: list[PairResult]

    @property
    def mean_cost_delta_pct(self) -> float:
        return round(statistics.mean(p.cost_delta_pct for p in self.pairs), 1) if self.pairs else 0.0

    @property
    def mean_tool_calls_delta_pct(self) -> float:
        return round(statistics.mean(p.tool_calls_delta_pct for p in self.pairs), 1) if self.pairs else 0.0

    @property
    def mean_wall_delta_pct(self) -> float:
        return round(statistics.mean(p.wall_delta_pct for p in self.pairs), 1) if self.pairs else 0.0

    @property
    def cold_success_rate(self) -> float:
        return round(sum(p.cold.success for p in self.pairs) / len(self.pairs), 3) if self.pairs else 0.0

    @property
    def warm_success_rate(self) -> float:
        return round(sum(p.warm.success for p in self.pairs) / len(self.pairs), 3) if self.pairs else 0.0

    @property
    def moat_demonstrated(self) -> bool:
        """A moat is demonstrated when the warm phase is cheaper (mean cost
        delta < 0) AND no less reliable (warm success rate >= cold)."""
        return (
            self.mean_cost_delta_pct < 0
            and self.warm_success_rate >= self.cold_success_rate
        )


def run_moat_benchmark(pairs: list[TaskPair], run_fn: RunFn) -> MoatResult:
    """Run each pair cold-then-warm and collect the deltas.

    The runner is responsible for the actual cold/warm semantics; this
    function only orchestrates and aggregates, so it is deterministic and
    testable with a scripted runner.
    """
    results: list[PairResult] = []
    for pair in pairs:
        cold = run_fn(pair.cold_task, False)
        warm = run_fn(pair.warm_task, True)
        results.append(PairResult(name=pair.name, cold=cold, warm=warm))
    return MoatResult(pairs=results)


def format_report(result: MoatResult) -> str:
    """Render a MoatResult as a markdown report."""
    lines = [
        "# Compounding-moat benchmark",
        "",
        "Cold = fresh world model, learning OFF (stateless baseline).",
        "Warm = same world model, learning ON (skills + reflexion recall).",
        "Negative cost/tool/wall delta = warm is cheaper/faster.",
        "",
        "| pair | cost Δ% | tool-calls Δ% | wall Δ% | cold ok | warm ok |",
        "|---|---|---|---|---|---|",
    ]
    for p in result.pairs:
        lines.append(
            f"| {p.name} | {p.cost_delta_pct:+.1f} | "
            f"{p.tool_calls_delta_pct:+.1f} | {p.wall_delta_pct:+.1f} | "
            f"{'✓' if p.cold.success else '✗'} | "
            f"{'✓' if p.warm.success else '✗'} |"
        )
    lines += [
        "",
        f"**Mean cost Δ: {result.mean_cost_delta_pct:+.1f}%**, "
        f"tool-calls Δ: {result.mean_tool_calls_delta_pct:+.1f}%, "
        f"wall Δ: {result.mean_wall_delta_pct:+.1f}%",
        f"Success rate — cold {result.cold_success_rate:.0%}, "
        f"warm {result.warm_success_rate:.0%}",
        "",
        (
            "✅ **Moat demonstrated**: the warm agent is cheaper and no less "
            "reliable."
            if result.moat_demonstrated
            else "⚠️ Moat not demonstrated on this run."
        ),
    ]
    return "\n".join(lines)


# The default suite. Each pair: a cold task that teaches something, and a
# similar (not identical) warm task that benefits from that lesson.
DEFAULT_PAIRS = [
    TaskPair(
        name="csv-summary",
        cold_task=(
            "Read data/sales_q1.csv and write a 3-bullet summary of the "
            "top product categories by revenue to reports/q1.md."
        ),
        warm_task=(
            "Read data/sales_q2.csv and write a 3-bullet summary of the "
            "top product categories by revenue to reports/q2.md."
        ),
    ),
    TaskPair(
        name="api-client",
        cold_task=(
            "Write a typed Python client for the /users endpoint of the "
            "REST API documented in docs/api.md, with retry on 5xx."
        ),
        warm_task=(
            "Write a typed Python client for the /orders endpoint of the "
            "REST API documented in docs/api.md, with retry on 5xx."
        ),
    ),
    TaskPair(
        name="repo-onboard",
        cold_task=(
            "Summarize how authentication works in this codebase, citing "
            "the relevant files and functions."
        ),
        warm_task=(
            "Summarize how authorization (permissions) works in this "
            "codebase, citing the relevant files and functions."
        ),
    ),
]


def run_with_maverick(task_text: str, learning_enabled: bool) -> RunMetrics:  # pragma: no cover -- requires API key
    """Real runner: execute a task through the kernel and read its episode
    metrics from the world model. Requires ANTHROPIC_API_KEY. Learning is
    toggled via the MAVERICK_USE_SKILLS / MAVERICK_REFLEXION env vars and a
    shared world-model DB across the cold+warm phases of a process.
    """
    import os
    import time

    from maverick.budget import Budget
    from maverick.llm import LLM
    from maverick.orchestrator import run_goal_sync
    from maverick.world_model import WorldModel

    os.environ["MAVERICK_USE_SKILLS"] = "1" if learning_enabled else "0"
    os.environ["MAVERICK_REFLEXION"] = "1" if learning_enabled else "0"
    os.environ["MAVERICK_AUTO_DISTILL"] = "1" if learning_enabled else "0"

    db_path = Path(os.environ.get("MAVERICK_MOAT_DB", "~/.maverick/moat.db")).expanduser()
    world = WorldModel(path=db_path)
    gid = world.create_goal(task_text[:80], task_text)
    budget = Budget(max_dollars=float(os.environ.get("MAVERICK_MOAT_MAX_DOLLARS", "2.0")))

    start = time.monotonic()
    run_goal_sync(llm=LLM(), world=world, budget=budget, goal_id=gid)
    wall = time.monotonic() - start

    eps = world.list_episodes(goal_id=gid, limit=1)
    if eps:
        e = eps[0]
        return RunMetrics(
            cost_dollars=e.cost_dollars,
            tool_calls=e.tool_calls,
            wall_seconds=e.duration_seconds or wall,
            success=e.outcome == "success",
        )
    return RunMetrics(cost_dollars=budget.dollars, tool_calls=budget.tool_calls,
                      wall_seconds=wall, success=False)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Compounding-moat benchmark")
    ap.add_argument("--out", type=Path, default=Path("benchmarks/MOAT_RESULTS.md"),
                    help="where to write the markdown report")
    ap.add_argument("--json", type=Path, default=None,
                    help="optional path to also dump the raw result as JSON")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover -- thin CLI wrapper
    args = parse_args(argv)
    result = run_moat_benchmark(DEFAULT_PAIRS, run_with_maverick)
    report = format_report(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")
    if args.json is not None:
        args.json.write_text(
            json.dumps({"pairs": [asdict(p) for p in result.pairs]}, indent=2),
            encoding="utf-8",
        )
    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
