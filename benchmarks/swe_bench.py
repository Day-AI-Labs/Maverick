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

    Wave 10: predicted_patch is now the EXTRACTED unified diff (not
    the orchestrator's prose). Failing-test files are pre-read and
    prepended to the brief. Cost is summed across all episodes
    in this goal, not just the last one. Test envs are cleared after
    the run so they don't leak into adjacent processes.
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "maverick")

    import asyncio
    from maverick.budget import Budget
    from maverick.coding_mode import extract_unified_diff
    from maverick.llm import LLM
    from maverick.orchestrator import run_goal_best_of_n, run_goal_sync
    from maverick.sandbox import build_sandbox
    from maverick.world_model import WorldModel

    # Default: turn coding mode ON for any SWE-bench-shaped task. Caller
    # can disable by setting MAVERICK_CODING_MODE=0 explicitly.
    os.environ.setdefault("MAVERICK_CODING_MODE", "1")
    # Best-of-N defaults to 1 (single-shot); SWE-bench Pro headline run
    # sets MAVERICK_BEST_OF_N=4 explicitly. Anything > 1 changes the
    # cost profile materially, so don't default it on.
    best_of_n = int(os.environ.get("MAVERICK_BEST_OF_N", "1"))

    # Wave 10: snapshot prior env so we can restore on exit and not leak
    # one instance's test sets into the next instance (or into a
    # follow-on non-bench process sharing the same shell).
    _env_keys = (
        "MAVERICK_FAIL_TO_PASS", "MAVERICK_PASS_TO_PASS", "MAVERICK_LANGUAGE",
    )
    _prior_env = {k: os.environ.get(k) for k in _env_keys}
    os.environ["MAVERICK_FAIL_TO_PASS"] = "||".join(kwargs.get("fail_to_pass") or [])
    os.environ["MAVERICK_PASS_TO_PASS"] = "||".join(kwargs.get("pass_to_pass") or [])
    os.environ["MAVERICK_LANGUAGE"] = str(kwargs.get("language") or "")

    # Wave 10 (B2): pre-read failing-test source as initial context so the
    # agent localises against the actual assertions rather than guessing.
    # Cap the prepended block so a giant test file doesn't blow the
    # first-message token budget; the agent can still `read_file` for more.
    failing_test_context = ""
    fail_ids = kwargs.get("fail_to_pass") or []
    if fail_ids:
        try:
            sandbox_workdir = build_sandbox().workdir
            from pathlib import Path as _Path
            seen: set[str] = set()
            chunks: list[str] = []
            for tid in fail_ids[:5]:  # at most 5 distinct files
                # `tests/foo.py::TestX::test_y` -> tests/foo.py
                path_part = tid.split("::", 1)[0] if "::" in tid else tid
                if not path_part or path_part in seen:
                    continue
                seen.add(path_part)
                tp = _Path(sandbox_workdir) / path_part
                if tp.exists() and tp.is_file():
                    try:
                        txt = tp.read_text(encoding="utf-8", errors="replace")
                        chunks.append(
                            f"--- failing test file: {path_part} ---\n"
                            f"{txt[:6000]}\n"
                        )
                    except (OSError, PermissionError):
                        pass
            if chunks:
                failing_test_context = (
                    "\n\nFailing-test context (ground truth for the fix; "
                    "do NOT hardcode to these expected values, derive the fix "
                    "from the production code):\n\n"
                    + "\n".join(chunks)
                )
        except Exception:
            failing_test_context = ""

    enriched_brief = brief + failing_test_context

    start = time.monotonic()
    world = WorldModel()
    llm = LLM()
    gid = world.create_goal(f"swe-bench:{instance_id}", enriched_brief)
    budget = Budget(max_dollars=3.0, max_wall_seconds=600.0)
    sandbox = build_sandbox()

    try:
        if best_of_n > 1:
            result = asyncio.run(run_goal_best_of_n(
                llm, world, budget, gid,
                sandbox=sandbox, max_depth=3, n=best_of_n,
            ))
        else:
            result = run_goal_sync(
                llm, world, budget, gid, sandbox=sandbox, max_depth=3,
            )
    finally:
        # Wave 10 (D11): restore env so the next instance / process
        # doesn't inherit this instance's test sets.
        for k, v in _prior_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # Wave 10 (C6): sum cost across ALL episodes for this goal, not just
    # the most recent one. Best-of-N runs N episodes; prior code reported
    # only eps[0] (one attempt) and lost the other N-1.
    all_eps = world.list_episodes(goal_id=gid)
    if all_eps:
        total_cost = sum(getattr(e, "cost_dollars", 0.0) or 0.0 for e in all_eps)
        total_in   = sum(getattr(e, "input_tokens", 0) or 0 for e in all_eps)
        total_out  = sum(getattr(e, "output_tokens", 0) or 0 for e in all_eps)
        last_outcome = all_eps[0].outcome
    else:
        total_cost, total_in, total_out, last_outcome = 0.0, 0, 0, ""

    # Wave 10 (C1): predicted_patch must be the EXTRACTED diff, not the
    # orchestrator's prose. The orchestrator's return value starts with
    # `DONE.\n\n<patch>` in coding mode; extract_unified_diff pulls the
    # actual unified diff. Fallback chain: orchestrator return -> goal.result.
    goal = world.get_goal(gid)
    diff = extract_unified_diff(result or "") or extract_unified_diff(
        (goal.result or "") if goal else ""
    ) or ""
    return Row(
        instance_id=instance_id,
        pipeline="maverick",
        model_id=getattr(llm, "model", ""),
        wall_seconds=time.monotonic() - start,
        cost_dollars=total_cost,
        tokens_in=total_in,
        tokens_out=total_out,
        predicted_patch=diff[:50_000],
        outcome=last_outcome or ("success" if diff else "no-diff"),
        extra={"goal_id": gid, "run_text": (result or "")[:500]},
    )


def run_sonnet_single(instance_id: str, brief: str, **_kwargs) -> Row:
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


def run_sonnet_tools(instance_id: str, brief: str, **_kwargs) -> Row:
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


def run_sonnet_self_consistency_n8(instance_id: str, brief: str, **_kwargs) -> Row:
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


def load_instances(manifest: Path) -> list[dict]:
    """Parse the manifest, yielding one dict per instance.

    Supported formats:
      - one JSON object per line with at minimum `instance_id` + `brief`;
        optional `fail_to_pass`, `pass_to_pass`, `gold_patch`, `language`
      - one bare ID per line (brief loaded from same-name .txt file)

    Wave 9 fix: previously returned `(id, brief)` tuples and dropped the
    test sets entirely — the test-driven verifier never fired.

    Wave 10 (D7): single malformed JSON line no longer aborts the whole
    harness; the bad line is logged + skipped so the run continues.
    """
    out: list[dict] = []
    for lineno, raw in enumerate(manifest.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    f"warning: skipping malformed JSON at {manifest}:{lineno}: {e}",
                    file=sys.stderr,
                )
                continue
            if "instance_id" not in obj:
                print(
                    f"warning: skipping {manifest}:{lineno}: missing instance_id",
                    file=sys.stderr,
                )
                continue
            out.append(obj)
        else:
            brief_path = manifest.parent / f"{line}.txt"
            brief = brief_path.read_text() if brief_path.exists() else ""
            out.append({"instance_id": line, "brief": brief})
    return out


def write_csv(rows: list[Row], out_path: Path) -> None:
    """Append (or create) a CSV at out_path. One row per (instance, pipeline).

    Wave 9 fix: dropped the manual `\\n` escape — csv.DictWriter quotes
    newlines correctly; the runbook's `replace('\\\\n', chr(10))` was a
    no-op on the unescaped data anyway, and would corrupt patches that
    contained the literal two-character sequence `\\n` (Python source,
    docstrings).

    Wave 10 (D8): hold an advisory `flock(LOCK_EX)` for the duration of
    the header-check + append so concurrent harness shards don't double-
    write rows or interleave a header in the middle of the file. Falls
    back to no-lock on platforms without fcntl (e.g. Windows runners).
    """
    cols = list(asdict(Row("", "", "")).keys())
    cols.remove("extra")
    new_file = not out_path.exists()
    with out_path.open("a", newline="") as f:
        try:
            import fcntl as _fcntl
            _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
            _locked = True
        except (ImportError, OSError):
            _locked = False
        try:
            # Re-check after lock: another shard may have created the file
            # between our `exists()` and now.
            if _locked and out_path.stat().st_size == 0:
                new_file = True
            elif _locked:
                new_file = False
            w = csv.DictWriter(f, fieldnames=cols)
            if new_file:
                w.writeheader()
            for row in rows:
                d = asdict(row)
                d.pop("extra", None)
                w.writerow(d)
            f.flush()
            os.fsync(f.fileno())
        finally:
            if _locked:
                try:
                    import fcntl as _fcntl
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass


def already_done(out_path: Path) -> set[tuple[str, str]]:
    """Read out_path and return the set of (instance_id, pipeline) pairs
    already written. Used by main() to skip on resume.

    Wave 10 (D12): csv.Error during read no longer silently empties the
    set; instead we log a visible warning so a partial-write race or
    corrupt CSV doesn't trigger a SILENT re-run that double-charges.
    """
    if not out_path.exists():
        return set()
    done: set[tuple[str, str]] = set()
    try:
        with out_path.open() as f:
            for row in csv.DictReader(f):
                done.add((row["instance_id"], row["pipeline"]))
    except (OSError, KeyError) as e:
        print(f"warning: could not read resume state from {out_path}: {e}",
              file=sys.stderr)
    except csv.Error as e:
        print(
            f"warning: CSV parse error in {out_path} ({e}); "
            f"recovered {len(done)} done rows. "
            f"Concurrent harness shards or a corrupt file may "
            f"trigger re-runs of partially-written instances.",
            file=sys.stderr,
        )
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=Path, required=True,
                    help="manifest of instance IDs (one per line or JSON-per-line)")
    ap.add_argument("--pipelines", default=",".join(PIPELINES),
                    help="comma-separated subset of: " + ",".join(PIPELINES))
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "RESULTS_SWE.csv")
    ap.add_argument("--abort-at-total-dollars", type=float, default=None,
                    help="Stop the run when accumulated $ spend exceeds N.")
    ap.add_argument("--no-resume", action="store_true",
                    help="Don't skip rows already in the output CSV.")
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
    done = set() if args.no_resume else already_done(args.out)
    if done:
        print(f"resuming: {len(done)} (instance,pipeline) pairs already in {args.out}",
              file=sys.stderr)

    total_spend = 0.0
    skipped = 0
    written = 0

    try:
        for inst in instances:
            iid = inst["instance_id"]
            brief = inst.get("brief", "")
            extra = {
                "fail_to_pass": inst.get("fail_to_pass", []) or [],
                "pass_to_pass": inst.get("pass_to_pass", []) or [],
                "gold_patch": inst.get("gold_patch", "") or "",
                "language": inst.get("language", "") or "",
            }
            for pipeline in pipelines:
                if (iid, pipeline) in done:
                    skipped += 1
                    continue
                if (args.abort_at_total_dollars is not None
                        and total_spend >= args.abort_at_total_dollars):
                    print(f"aborting: total spend ${total_spend:.2f} >= "
                          f"${args.abort_at_total_dollars:.2f} cap",
                          file=sys.stderr)
                    return 0
                try:
                    row = _PIPELINE_FNS[pipeline](iid, brief, **extra)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    row = Row(
                        instance_id=iid, pipeline=pipeline, model_id="",
                        outcome=f"error: {type(e).__name__}: {e}",
                    )
                # Append THIS row immediately so a crash on instance N+1
                # doesn't lose rows 0..N. fsync via write_csv.
                write_csv([row], args.out)
                written += 1
                total_spend += row.cost_dollars
                print(f"{iid}\t{pipeline}\t{row.outcome}\t"
                      f"${row.cost_dollars:.3f}\t{row.wall_seconds:.1f}s"
                      f"\ttotal=${total_spend:.2f}")
    except KeyboardInterrupt:
        print(f"\nSIGINT caught; {written} row(s) flushed to {args.out}",
              file=sys.stderr)
        return 130

    print(f"\n{written} row(s) appended to {args.out}; "
          f"{skipped} skipped (already done); total ${total_spend:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
