"""Rigorous compounding-moat benchmark: a defensible cold-vs-warm protocol.

The first moat benchmark (``moat.py``) compared a *cold task with learning
off* against a *similar warm task with learning on*. That conflates two
variables -- task identity AND learning -- and scores on a mean cost delta
that a single outlier can flip. The honest question is narrower:

    Holding the task fixed, does having relevant PRIOR experience in the
    store make the agent no worse -- and ideally cheaper -- than starting
    cold? And does the relevance gate guarantee that "no worse"?

This module isolates exactly that variable. For each pair (prior task A,
target task B) and each seed:

  * WARM: run A first in a private store (which distills a skill / records
    reflexion), then run the SAME target B against that pre-warmed store.
  * COLD: run the SAME target B against a FRESH, empty store.

Both conditions use identical config (learning ON, builtin library OFF) so
the ONLY difference is whether the store was pre-populated by A. That makes
the delta attributable to retained memory, not to task difficulty.

The headline is deliberately the *bounded, defensible* claim, not a hero
number:

  * ``not_worse_rate`` -- the fraction of observations where WARM cost is
    within tolerance of (or below) COLD. With the relevance gate on, this
    should be 1.0: warm is *never worse* than cold, because irrelevant
    memory is never injected. This is the property the gate buys, and the
    failure the ungated baseline showed (warm MORE expensive than cold).
  * ``median_cost_delta_pct`` -- robust to the outliers that made the mean
    misleading. Negative = warm is typically cheaper (the upside).
  * success parity (warm >= cold) -- learning must not cost reliability.

``aggregate`` / ``format_report`` / ``claim`` are pure and deterministic,
so the methodology is unit-tested offline without spending a cent
(``benchmarks/test_moat_rigorous.py``). ``run_live`` wires the real kernel
for paid runs and is the protocol that produced ``MOAT_RIGOROUS_RESULTS.md``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

# benchmarks/ is a flat, path-loaded script dir; import the sibling for the
# shared RunMetrics shape (cost/tool_calls/wall/success of one run).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from moat import RunMetrics  # noqa: E402

# The orchestrator (the main loop) must COMPLETE these tasks within the cap.
# The product-default Opus orchestrator truncates at a tight cap -- the budget
# refuses the next call before the agent finalizes -- which ALSO starves
# learning (the populate run never succeeds, so distills nothing). So the live
# run pins a cheaper, completing orchestrator, held IDENTICAL across warm and
# cold so the delta still isolates memory (see MOAT_RIGOROUS_RESULTS.md). Pull
# the repo's Sonnet tier rather than a literal id so it cannot drift.
try:
    from maverick.llm import ROLE_MODELS as _ROLE_MODELS
    _COMPLETING_ORCHESTRATOR = _ROLE_MODELS.get("coder", "claude-sonnet-4-6")
except Exception:  # pragma: no cover -- benchmark falls back to a sane default
    _COMPLETING_ORCHESTRATOR = "claude-sonnet-4-6"


@dataclass
class PairSpec:
    """A prior task A and a related target task B. B is what we measure; A is
    the experience that pre-warms the store for the WARM condition. A and B
    are related (same domain) but NOT identical -- a verbatim repeat would
    measure caching, not transferable learning."""
    name: str
    prior_task: str   # A -- run first to populate the warm store
    target_task: str  # B -- the task actually measured, run in both conditions


@dataclass
class Observation:
    """One (pair, seed) outcome: the SAME target B run warm and cold."""
    name: str
    seed: int
    warm: RunMetrics
    cold: RunMetrics


# A live pair runner takes (PairSpec, seed) and returns (warm_B, cold_B).
PairRunFn = Callable[[PairSpec, int], "tuple[RunMetrics, RunMetrics]"]


@dataclass
class RigorousResult:
    observations: list[Observation]
    tol: float = 0.05  # within +/-5% counts as "the same" -- run-to-run noise

    def _cost_delta_pct(self, o: Observation) -> float:
        if o.cold.cost_dollars == 0:
            return 0.0
        return round((o.warm.cost_dollars - o.cold.cost_dollars)
                     / o.cold.cost_dollars * 100.0, 1)

    @property
    def n(self) -> int:
        return len(self.observations)

    @property
    def cost_deltas_pct(self) -> list[float]:
        return [self._cost_delta_pct(o) for o in self.observations]

    @property
    def not_worse_count(self) -> int:
        """WARM cost is at or below COLD, within tolerance (gate => no noise
        injected => no regression)."""
        return sum(
            1 for o in self.observations
            if o.warm.cost_dollars <= o.cold.cost_dollars * (1 + self.tol)
        )

    @property
    def cheaper_count(self) -> int:
        """WARM is strictly cheaper than COLD beyond noise (the upside)."""
        return sum(
            1 for o in self.observations
            if o.warm.cost_dollars < o.cold.cost_dollars * (1 - self.tol)
        )

    @property
    def not_worse_rate(self) -> float:
        return round(self.not_worse_count / self.n, 3) if self.n else 0.0

    @property
    def median_cost_delta_pct(self) -> float:
        return round(statistics.median(self.cost_deltas_pct), 1) if self.n else 0.0

    @property
    def mean_cost_delta_pct(self) -> float:
        return round(statistics.mean(self.cost_deltas_pct), 1) if self.n else 0.0

    @property
    def warm_success_rate(self) -> float:
        return round(sum(o.warm.success for o in self.observations) / self.n, 3) if self.n else 0.0

    @property
    def cold_success_rate(self) -> float:
        return round(sum(o.cold.success for o in self.observations) / self.n, 3) if self.n else 0.0

    @property
    def bounded_moat_demonstrated(self) -> bool:
        """The honest, defensible claim: WARM is NEVER worse than COLD (cost
        not-worse on every observation) AND reliability does not regress. This
        is exactly the "warm never worse than cold" property the relevance
        gate is meant to guarantee."""
        return (
            self.n > 0
            and self.not_worse_count == self.n
            and self.warm_success_rate >= self.cold_success_rate
        )

    @property
    def cheaper_moat_demonstrated(self) -> bool:
        """The stronger claim: bounded AND warm is *typically* cheaper (median
        delta below zero, i.e. the upside shows up more often than not)."""
        return self.bounded_moat_demonstrated and self.median_cost_delta_pct < 0


def aggregate(observations: list[Observation], tol: float = 0.05) -> RigorousResult:
    return RigorousResult(observations=list(observations), tol=tol)


def claim(result: RigorousResult) -> str:
    """The single most-defensible sentence these numbers support -- chosen so
    we never over-state. Order matters: strongest supported claim wins."""
    if result.n == 0:
        return "No valid observations: no claim can be made."
    if result.cheaper_moat_demonstrated:
        return (
            f"Governed learning helps: on seen task classes the warm agent is "
            f"never worse than cold and is typically cheaper "
            f"(median {result.median_cost_delta_pct:+.0f}% cost) with no loss "
            f"of reliability ({result.not_worse_count}/{result.n} not-worse, "
            f"{result.cheaper_count}/{result.n} strictly cheaper)."
        )
    if result.bounded_moat_demonstrated:
        return (
            f"Governed learning does no harm and sometimes helps: the warm "
            f"agent is never worse than cold "
            f"({result.not_worse_count}/{result.n} not-worse, "
            f"{result.cheaper_count}/{result.n} strictly cheaper) with no loss "
            f"of reliability. The relevance gate delivers the 'warm never worse "
            f"than cold' guarantee."
        )
    return (
        f"Bounded moat NOT demonstrated on this run: warm was within-or-below "
        f"cold on only {result.not_worse_count}/{result.n} observations "
        f"(median {result.median_cost_delta_pct:+.0f}% cost). Memory is not yet "
        f"a net positive on these classes -- report the honest negative."
    )


def format_report(result: RigorousResult) -> str:
    lines = [
        "# Rigorous compounding-moat benchmark",
        "",
        "Same target task B run two ways; the ONLY difference is store contents:",
        "- **WARM**: store pre-populated by a related prior task A (learning on).",
        "- **COLD**: fresh, empty store (learning on, nothing to recall).",
        "",
        "Negative cost Δ = warm cheaper. 'not-worse' = warm cost within "
        f"{result.tol:.0%} of (or below) cold.",
        "",
        "| pair | seed | warm $ | cold $ | cost Δ% | warm ok | cold ok |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in result.observations:
        lines.append(
            f"| {o.name} | {o.seed} | {o.warm.cost_dollars:.3f} | "
            f"{o.cold.cost_dollars:.3f} | {result._cost_delta_pct(o):+.1f} | "
            f"{'✓' if o.warm.success else '✗'} | "
            f"{'✓' if o.cold.success else '✗'} |"
        )
    lines += [
        "",
        f"- observations: **{result.n}**",
        f"- warm NOT-worse-than-cold: **{result.not_worse_count}/{result.n}** "
        f"(rate {result.not_worse_rate:.0%}); strictly cheaper: "
        f"{result.cheaper_count}/{result.n}",
        f"- cost Δ: **median {result.median_cost_delta_pct:+.1f}%**, "
        f"mean {result.mean_cost_delta_pct:+.1f}% (median is the robust figure)",
        f"- success: warm {result.warm_success_rate:.0%} vs cold "
        f"{result.cold_success_rate:.0%}",
        "",
        f"**Claim:** {claim(result)}",
    ]
    return "\n".join(lines)


def run_moat_rigorous(pairs: list[PairSpec], seeds: int,
                      pair_run_fn: PairRunFn, tol: float = 0.05) -> RigorousResult:
    """Orchestrate the protocol with an injected pair runner (pure: scripted
    in tests, real kernel in ``run_live``)."""
    obs: list[Observation] = []
    for pair in pairs:
        for seed in range(seeds):
            warm, cold = pair_run_fn(pair, seed)
            obs.append(Observation(name=pair.name, seed=seed, warm=warm, cold=cold))
    return aggregate(obs, tol=tol)


# The default suite: three related (prior -> target) pairs over codebase-
# comprehension tasks, the cheapest faithful task class (read-only, bounded).
DEFAULT_PAIRS = [
    PairSpec(
        name="auth->authz",
        prior_task=("Summarize how user authentication (OIDC / login / tokens) "
                    "works in this codebase, citing the relevant files and "
                    "functions. Max 8 bullets."),
        target_task=("Summarize how authorization and permission checks "
                     "(capabilities) work in this codebase, citing the relevant "
                     "files and functions. Max 8 bullets."),
    ),
    PairSpec(
        name="budget->risk",
        prior_task=("Explain how the Budget enforces token and dollar caps in "
                    "this codebase, citing the relevant files and functions. "
                    "Max 8 bullets."),
        target_task=("Explain how per-tool risk ceilings limit which tools an "
                     "agent may use in this codebase, citing the relevant files "
                     "and functions. Max 8 bullets."),
    ),
    PairSpec(
        name="reflexion->dreaming",
        prior_task=("Explain how the reflexion failure-memory records and "
                    "recalls lessons in this codebase, citing the relevant files "
                    "and functions. Max 8 bullets."),
        target_task=("Explain how the dreaming consolidation loop works in this "
                     "codebase, citing the relevant files and functions. "
                     "Max 8 bullets."),
    ),
]


def _live_pair_runner(cap: float, timeout: int, orchestrator_model: str) -> PairRunFn:  # pragma: no cover -- requires API key
    """Build a pair runner that executes each phase in an isolated subprocess
    (fresh HOME => fresh store), so WARM (pre-warmed by A) and COLD (fresh)
    differ only in store contents. Subprocess isolation avoids in-process
    skill/embedding cache leakage between conditions."""
    import os
    import subprocess
    import tempfile

    worker = Path(__file__).resolve().parent / "_moat_rigorous_worker.py"
    worker.write_text(_WORKER_SRC, encoding="utf-8")

    def _run(home: str, task: str) -> RunMetrics:
        env = dict(os.environ)
        env.update({
            "HOME": home, "USERPROFILE": home,
            "MAVERICK_USE_SKILLS": "1", "MAVERICK_REFLEXION": "1",
            "MAVERICK_AUTO_DISTILL": "1", "MAVERICK_BUILTIN_SKILLS": "0",
            "MAVERICK_MOAT_ALLOW_LOCAL_SANDBOX": "1",
            "MOAT_TASK": task, "MOAT_CAP": str(cap),
            "MOAT_ORCH_MODEL": orchestrator_model,
        })
        os.makedirs(os.path.join(home, ".maverick"), exist_ok=True)
        try:
            r = subprocess.run([sys.executable, str(worker)], env=env,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return RunMetrics(cost_dollars=cap, tool_calls=0, wall_seconds=float(timeout),
                              success=False)
        for ln in r.stdout.splitlines():
            if ln.startswith("RESULT_JSON:"):
                d = json.loads(ln[len("RESULT_JSON:"):])
                return RunMetrics(cost_dollars=d["cost"], tool_calls=d["tools"],
                                  wall_seconds=d.get("wall", 0.0), success=d["ok"])
        return RunMetrics(cost_dollars=0.0, tool_calls=0, wall_seconds=0.0, success=False)

    def pair_run_fn(pair: PairSpec, seed: int) -> tuple[RunMetrics, RunMetrics]:
        warm_home = tempfile.mkdtemp(prefix=f"moat-warm-{seed}-")
        cold_home = tempfile.mkdtemp(prefix=f"moat-cold-{seed}-")
        _run(warm_home, pair.prior_task)          # populate warm store with A
        warm = _run(warm_home, pair.target_task)  # measure B against warm store
        cold = _run(cold_home, pair.target_task)  # measure B against fresh store
        return warm, cold

    return pair_run_fn


# Worker run in an isolated HOME; prints one RESULT_JSON line read by the parent.
_WORKER_SRC = '''\
import json, os, time
from pathlib import Path
# Pin the orchestrator + revisor so the task COMPLETES within the cap (the
# product-default Opus orchestrator truncates and starves learning; see module
# docstring). Held identical across warm and cold, so the delta isolates memory.
_cfg = Path("~/.maverick").expanduser(); _cfg.mkdir(parents=True, exist_ok=True)
_orch = os.environ.get("MOAT_ORCH_MODEL", "").strip()
if _orch:
    (_cfg / "config.toml").write_text(
        '[models]\\norchestrator = "%s"\\nrevisor = "%s"\\n' % (_orch, _orch))
from maverick.budget import Budget
from maverick.llm import LLM
from maverick.orchestrator import run_goal_sync
from maverick.sandbox import build_sandbox
from maverick.world_model import WorldModel
task = os.environ["MOAT_TASK"]; cap = float(os.environ.get("MOAT_CAP", "1.25"))
world = WorldModel(path=Path("~/.maverick/world.db").expanduser())
gid = world.create_goal(task[:80], task); budget = Budget(max_dollars=cap)
t = time.monotonic()
try:
    run_goal_sync(llm=LLM(), world=world, budget=budget, goal_id=gid, sandbox=build_sandbox())
except Exception as e:
    print("RUN_EXC:", type(e).__name__, str(e)[:120])
wall = time.monotonic() - t
nsk = len(list(_cfg.rglob("*.md")))  # distilled skills now in the store
eps = world.list_episodes(goal_id=gid, limit=1)
if eps:
    e = eps[0]
    out = {"cost": float(e.cost_dollars), "tools": int(e.tool_calls),
           "wall": wall, "ok": e.outcome == "success", "skills": nsk}
else:
    out = {"cost": float(getattr(budget, "dollars", 0.0)),
           "tools": int(getattr(budget, "tool_calls", 0)),
           "wall": wall, "ok": False, "skills": nsk}
print("RESULT_JSON:" + json.dumps(out))
'''


def run_live(seeds: int = 2, cap: float = 1.25, timeout: int = 600,
             tol: float = 0.05,
             orchestrator_model: str = _COMPLETING_ORCHESTRATOR) -> RigorousResult:  # pragma: no cover -- requires API key
    """Paid run against the real kernel. Requires ANTHROPIC_API_KEY. Pins the
    orchestrator to a completing model (default: the repo's Sonnet tier) so
    tasks finish within ``cap``; pass ``orchestrator_model=""`` to keep the
    product default (Opus, which truncates at a tight cap -- see docstring)."""
    return run_moat_rigorous(DEFAULT_PAIRS, seeds,
                             _live_pair_runner(cap, timeout, orchestrator_model), tol=tol)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Rigorous compounding-moat benchmark")
    ap.add_argument("--seeds", type=int, default=2, help="repeats per pair")
    ap.add_argument("--cap", type=float, default=1.25, help="$ cap per run")
    ap.add_argument("--orchestrator-model", default=_COMPLETING_ORCHESTRATOR,
                    help="orchestrator model so tasks complete ('' = product default; Opus truncates)")
    ap.add_argument("--out", type=Path, default=Path("benchmarks/MOAT_RIGOROUS_RESULTS.md"))
    ap.add_argument("--json", type=Path, default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- thin CLI wrapper
    args = parse_args(argv)
    result = run_live(seeds=args.seeds, cap=args.cap,
                      orchestrator_model=args.orchestrator_model)
    report = format_report(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")
    if args.json is not None:
        args.json.write_text(
            json.dumps({"observations": [asdict(o) for o in result.observations]}, indent=2),
            encoding="utf-8",
        )
    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
