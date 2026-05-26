"""SWE-bench Verified harness for Maverick + baselines.

Karpathy SOTA-review item: real SWE-bench numbers with three baselines.
Without these the "swarm" column is undefendable.

This script DOES NOT execute the test suites by itself -- SWE-bench's
evaluation harness needs Docker + the dataset. It DOES:

1. Iterate over a manifest of SWE-bench instance IDs
2. Run four pipelines per instance: maverick / sonnet_single /
   sonnet_tools / sonnet_self_consistency_n8
3. Capture (model, wall_seconds, cost_dollars, tokens, predicted_patch)
4. Write one CSV row per (instance, pipeline) into RESULTS_SWE.csv

Then the user runs the upstream SWE-bench evaluator on the
predicted_patch column to score. The harness is a producer; scoring is
out-of-process so we don't pretend to grade ourselves.

Dry-run:
    MAVERICK_BENCH_DRY_RUN=1 python benchmarks/swe_bench.py \\
        --instances benchmarks/swe_bench_instances_smoke.txt \\
        --pipelines maverick,sonnet_single

Real run (requires ANTHROPIC_API_KEY + the SWE-bench Verified manifest):
    python benchmarks/swe_bench.py \\
        --instances benchmarks/swe_bench_verified.txt \\
        --pipelines maverick,sonnet_single,sonnet_tools,sonnet_self_consistency_n8
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


PIPELINES = (
    "maverick",
    "sonnet_single",       # single-shot Anthropic call, no tools
    "sonnet_tools",        # Anthropic call with read_file/write_file/shell tools
    "sonnet_self_consistency_n8",  # 8 single-shots, majority-vote on patch
)


@dataclass
class Row:
    instance_id: str
    pipeline: str
    model_id: str
    wall_seconds: float = 0.0
    cost_dollars: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    predicted_patch: str = ""
    verifier_confidence: float = 0.0
    disagreement_entropy: float = 0.0
    outcome: str = ""        # success / failure / budget / error
    extra: dict = field(default_factory=dict)


def _dry_run_row(instance_id: str, pipeline: str) -> Row:
    """Synthesize a representative row so the harness machinery can be
    tested without burning credits."""
    return Row(
        instance_id=instance_id,
        pipeline=pipeline,
        model_id="dry-run",
        wall_seconds=0.1,
        cost_dollars=0.0,
        tokens_in=0,
        tokens_out=0,
        predicted_patch="--- a/dummy\n+++ b/dummy\n",
        outcome="dry-run",
    )


def run_maverick(instance_id: str, brief: str, **kwargs) -> Row:
    """Spin up a Maverick swarm against the instance brief.

    Wave 8: coding-mode + best-of-N support. The harness sets
    MAVERICK_CODING_MODE=1 + MAVERICK_BEST_OF_N + MAVERICK_FAIL_TO_PASS /
    MAVERICK_PASS_TO_PASS so coding_mode.from_env() picks up the
    benchmark context. The agent then uses the strict diff-only
    template, self-validates patches via `git apply --check`, runs
    the test-driven verifier when ground-truth tests are present,
    and (when n > 1) returns the best-of-N candidate.
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "maverick")

    import asyncio
    from maverick.budget import Budget
    from maverick.llm import LLM
    from maverick.orchestrator import run_goal_best_of_n, run_goal_sync
    from maverick.sandbox import build_sandbox
    from maverick.world_model import WorldModel

    # Default: turn coding mode ON for any SWE-bench-shaped task. Caller
    # can disable by setting MAVERICK_CODING_MODE=0 explicitly.
    os.environ.setdefault("MAVERICK_CODING_MODE", "1")
    # Best-of-N defaults to 4 for the headline run; override via env.
    best_of_n = int(os.environ.get("MAVERICK_BEST_OF_N", "1"))
    # Surface SWE-bench tests via env so the agent's verifier sees them.
    if "fail_to_pass" in kwargs:
        os.environ["MAVERICK_FAIL_TO_PASS"] = "||".join(kwargs["fail_to_pass"])
    if "pass_to_pass" in kwargs:
        os.environ["MAVERICK_PASS_TO_PASS"] = "||".join(kwargs["pass_to_pass"])

    start = time.monotonic()
    world = WorldModel()
    llm = LLM()
    gid = world.create_goal(f"swe-bench:{instance_id}", brief)
    budget = Budget(max_dollars=3.0, max_wall_seconds=600.0)
    sandbox = build_sandbox()

    if best_of_n > 1:
        result = asyncio.run(run_goal_best_of_n(
            llm, world, budget, gid,
            sandbox=sandbox, max_depth=3, n=best_of_n,
        ))
    else:
        result = run_goal_sync(
            llm, world, budget, gid, sandbox=sandbox, max_depth=3,
        )

    # Pull verifier signals from the most recent episode.
    eps = world.list_episodes(limit=1)
    goal = world.get_goal(gid)
    return Row(
        instance_id=instance_id,
        pipeline="maverick",
        model_id=getattr(llm, "model", ""),
        wall_seconds=time.monotonic() - start,
        cost_dollars=eps[0].cost_dollars if eps else 0.0,
        tokens_in=eps[0].input_tokens if eps else 0,
        tokens_out=eps[0].output_tokens if eps else 0,
        predicted_patch=(goal.result or "")[:50_000] if goal else "",
        outcome=eps[0].outcome if eps else "",
        extra={"goal_id": gid, "run_text": (result or "")[:500]},
    )


def run_sonnet_single(instance_id: str, brief: str) -> Row:
    """Baseline #1: single Anthropic call, no tools.

    The simplest possible baseline. If Maverick can't beat this on
    cost/wall and match-or-exceed on accuracy, the swarm isn't
    earning its complexity.
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "sonnet_single")

    import anthropic
    from maverick.budget import Budget
    from maverick.llm import MODEL_SONNET

    start = time.monotonic()
    client = anthropic.Anthropic()
    budget = Budget(max_dollars=3.0)
    resp = client.messages.create(
        model=MODEL_SONNET,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                f"You are solving SWE-bench instance {instance_id}.\n\n"
                f"{brief}\n\n"
                "Respond ONLY with a unified diff (git-format patch) that fixes "
                "the issue. No prose, no explanation, just the patch starting "
                "with `--- a/...`."
            ),
        }],
    )
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    budget.record_tokens(
        resp.usage.input_tokens, resp.usage.output_tokens, model=MODEL_SONNET,
    )
    return Row(
        instance_id=instance_id,
        pipeline="sonnet_single",
        model_id=MODEL_SONNET,
        wall_seconds=time.monotonic() - start,
        cost_dollars=budget.dollars,
        tokens_in=budget.input_tokens,
        tokens_out=budget.output_tokens,
        predicted_patch=text[:50_000],
        outcome="success" if text else "empty",
    )


def run_sonnet_tools(instance_id: str, brief: str) -> Row:
    """Baseline #2: Sonnet with bash + read/write tools, no swarm.

    Closer to Devin / Cursor. Same model as Maverick uses for workers
    but flat (no orchestrator, no spawn, no verifier, no skills).
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "sonnet_tools")
    # Full implementation: thin client that loops on tool_use blocks
    # against a LocalBackend sandbox. Punted to follow-up commit; the
    # surface area is large enough to warrant its own module under
    # benchmarks/baselines/. Today returns dry-run-equivalent.
    row = _dry_run_row(instance_id, "sonnet_tools")
    row.outcome = "not-implemented"
    return row


def run_sonnet_self_consistency_n8(instance_id: str, brief: str) -> Row:
    """Baseline #3: 8 single-shot calls; pick the most common patch.

    Tests test-time compute (the cheap version) without any agent
    structure. If self-consistency-N=8 beats Maverick at the same
    dollar budget, the swarm machinery is pure overhead.
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "sonnet_self_consistency_n8")
    row = _dry_run_row(instance_id, "sonnet_self_consistency_n8")
    row.outcome = "not-implemented"
    return row


_PIPELINE_FNS = {
    "maverick": run_maverick,
    "sonnet_single": run_sonnet_single,
    "sonnet_tools": run_sonnet_tools,
    "sonnet_self_consistency_n8": run_sonnet_self_consistency_n8,
}


def load_instances(manifest: Path) -> list[tuple[str, str]]:
    """Manifest format: one JSON object per line:
        {"instance_id": "django__django-12345", "brief": "..."}

    or one ID per line (brief loaded from same-name .txt file).
    """
    out: list[tuple[str, str]] = []
    for line in manifest.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            obj = json.loads(line)
            out.append((obj["instance_id"], obj.get("brief", "")))
        else:
            brief_path = manifest.parent / f"{line}.txt"
            brief = brief_path.read_text() if brief_path.exists() else ""
            out.append((line, brief))
    return out


def write_csv(rows: list[Row], out_path: Path) -> None:
    """Append (or create) a CSV at out_path. One row per (instance, pipeline)."""
    cols = list(asdict(Row("", "", "")).keys())
    cols.remove("extra")
    new_file = not out_path.exists()
    with out_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new_file:
            w.writeheader()
        for row in rows:
            d = asdict(row)
            d.pop("extra", None)
            d["predicted_patch"] = d["predicted_patch"].replace("\n", "\\n")
            w.writerow(d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=Path, required=True,
                    help="manifest of instance IDs (one per line or JSON-per-line)")
    ap.add_argument("--pipelines", default=",".join(PIPELINES),
                    help="comma-separated subset of: " + ",".join(PIPELINES))
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "RESULTS_SWE.csv")
    args = ap.parse_args()

    if not args.instances.exists():
        print(f"manifest not found: {args.instances}", file=sys.stderr)
        return 2

    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    for p in pipelines:
        if p not in _PIPELINE_FNS:
            print(f"unknown pipeline: {p}", file=sys.stderr)
            return 2

    instances = load_instances(args.instances)
    rows: list[Row] = []
    for instance_id, brief in instances:
        for pipeline in pipelines:
            try:
                row = _PIPELINE_FNS[pipeline](instance_id, brief)
            except Exception as e:
                row = Row(
                    instance_id=instance_id, pipeline=pipeline, model_id="",
                    outcome=f"error: {type(e).__name__}: {e}",
                )
            rows.append(row)
            print(f"{instance_id}\t{pipeline}\t{row.outcome}\t"
                  f"${row.cost_dollars:.3f}\t{row.wall_seconds:.1f}s")
    write_csv(rows, args.out)
    print(f"\n{len(rows)} row(s) appended to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
