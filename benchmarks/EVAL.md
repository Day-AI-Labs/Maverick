# Correctness-scoring eval harness

`harness.py` measures the **cost / latency** of a goal run. `evals.py` adds
the missing half: **correctness** — did the agent get the right answer? It
reports `pass@1` per benchmark over a small pluggable interface, so GAIA /
terminal-bench / τ²-bench are reported the same way despite different task
shapes.

## Run it

```bash
# Real run (drives `maverick start`; needs a provider key configured):
python benchmarks/run_eval.py gaia --dataset path/to/gaia.jsonl --limit 20

# CI / smoke (no keys, no dataset — uses the shipped offline fixture):
MAVERICK_EVAL_DRY_RUN=1 python benchmarks/run_eval.py gaia
```

Scores append to `benchmarks/SCORES.md` (a markdown table, like `RESULTS.md`).

## The contract (`evals.py`)

A `Benchmark` supplies tasks and a scorer; a `solver` turns a task into the
agent's answer. The solver is **injected** so the whole harness runs in CI
with a deterministic stub — no LLM, no network.

```python
class Benchmark(Protocol):
    name: str
    def load_tasks(self, dataset=None, *, limit=None) -> list[EvalTask]: ...
    def score(self, task: EvalTask, output: str) -> float: ...  # 0.0..1.0

run_benchmark(bench, solver, dataset=..., limit=...) -> {pass_at_1, mean_score, ...}
```

## Benchmarks

| slice | benchmark | status | scorer |
|---|---|---|---|
| general assistant | **GAIA** (`eval_gaia.py`) | ✅ shipped | official normalized exact-match (number / string / list) |
| CLI ops | terminal-bench | follow-up | run the task's `verify` command in a sandbox workdir; pass iff exit 0 |
| tool-agent policy | τ²-bench | follow-up | compare final DB state + actions to the expected trace |

### Adding the next slice

1. Add `eval_<name>.py` exporting a `Benchmark` class (`name`, `load_tasks`,
   `score`).
2. Ship a tiny offline fixture in `eval_fixtures/` and a test in
   `test_evals.py` that runs it with a stub solver.
3. Register it in `run_eval.py`'s `_BENCHMARKS`.

**terminal-bench** fits the contract directly: the task carries a `verify`
shell command, the solver runs the instruction in a workdir, and `score`
runs `verify` through `sandbox.exec()` (CLAUDE.md rule 4) — pass iff exit 0.

**τ²-bench** needs a live **user-simulator** LLM (it's a dual-control
agent↔user setting), which is a separate piece; the *offline* scorer
(comparing the recorded action trace / DB state to the expected one) fits
the contract today.
