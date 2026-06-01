"""Cost / latency / samples tracker for benchmark runs.

Karpathy SOTA-review prescription: every benchmark row needs
`($/task, success, latency, samples_used, verifier_calls)` so we can
plot the cost-vs-accuracy Pareto frontier and defend the swarm's
compute cost against the three baselines.

Producers (harness pipelines like benchmarks/swe_bench.py) call:

    with cost_tracker(task_id, pipeline) as t:
        ...
        t.note_sample()
        t.note_verifier_call()
        t.success = True

The tracker writes one JSONL line per task to `results.jsonl` in the
caller-specified dir; the leaderboard aggregator reads that file.

This intentionally does NOT call the LLM directly. Spend numbers come
from `maverick.budget.Budget`; the tracker just persists them.
"""
from __future__ import annotations

import contextlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class TaskRow:
    task_id: str
    pipeline: str
    success: bool = False
    cost_usd: float = 0.0
    latency_s: float = 0.0
    samples_used: int = 1
    verifier_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model_id: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)


class CostTracker:
    """Context-manager wrapper over a single TaskRow."""

    def __init__(self, row: TaskRow, results_path: Path):
        self.row = row
        self.results_path = results_path
        self._start: float = 0.0

    def __enter__(self) -> CostTracker:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.row.latency_s = time.monotonic() - self._start
        if exc is not None:
            self.row.error = f"{exc_type.__name__}: {exc}"
        self.write()

    def note_sample(self) -> None:
        # Count each additional sample (best-of-N / self-consistency). The old
        # `+= 0` was a no-op, so samples_used was stuck at the default 1 and the
        # Pareto cost-vs-samples analysis was wrong for every multi-sample run.
        self.row.samples_used += 1

    def note_verifier_call(self) -> None:
        self.row.verifier_calls += 1

    def absorb_budget(self, budget) -> None:
        """Copy the budget's accumulators into this row."""
        self.row.cost_usd = float(budget.dollars)
        self.row.tokens_in = int(budget.input_tokens)
        self.row.tokens_out = int(budget.output_tokens)
        self.row.cache_read_tokens = int(getattr(budget, "cache_read_tokens", 0))
        self.row.cache_write_tokens = int(getattr(budget, "cache_write_tokens", 0))

    def write(self) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with self.results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(self.row)) + "\n")


@contextlib.contextmanager
def cost_tracker(
    task_id: str,
    pipeline: str,
    *,
    results_path: Path,
    model_id: str = "",
):
    row = TaskRow(task_id=task_id, pipeline=pipeline, model_id=model_id)
    tracker = CostTracker(row, results_path)
    with tracker:
        yield tracker


def pareto_frontier(
    rows: list[TaskRow],
    *,
    pipelines: list[str] | None = None,
) -> list[tuple[str, float, float]]:
    """Return (pipeline, total_cost, success_rate) for each pipeline.

    Used to render the cost-vs-accuracy table in RESULTS.md.
    """
    pipelines = pipelines or sorted({r.pipeline for r in rows})
    out: list[tuple[str, float, float]] = []
    for p in pipelines:
        group = [r for r in rows if r.pipeline == p]
        if not group:
            continue
        cost = sum(r.cost_usd for r in group)
        rate = sum(1 for r in group if r.success) / len(group)
        out.append((p, cost, rate))
    return out


def load_results(path: Path) -> list[TaskRow]:
    """Read a results.jsonl file back into TaskRow objects."""
    if not path.exists():
        return []
    out: list[TaskRow] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                out.append(TaskRow(**data))
            except (json.JSONDecodeError, TypeError):
                continue
    return out
