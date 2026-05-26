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
import threading
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


# Wave 12: sanitize patches before they reach the CSV. Three failures
# in one place: (a) NUL bytes break csv.DictReader on resume → silent
# re-runs that double-charge; (b) Excel auto-executes cells starting
# with `=+-@\t\r` and patch lines literally start with `+`/`-` → CSV
# formula injection when anyone opens RESULTS_SWE.csv in Excel for
# analysis; (c) other C0 control characters can confuse downstream
# tooling. Truncation is REMOVED — SWE-bench Pro has no patch-size cap
# and the prior 50_000-byte slice cut mid-hunk on multi-file refactors.
def _sanitize_patch_for_csv(diff: str) -> str:
    if not diff:
        return ""
    # Wave 12 hardening: normalize CRLF to LF before C0 strip so Windows-
    # origin patches don't leave bare \r that csv.DictReader misinterprets
    # as embedded newlines. Also strip BOM (U+FEFF) and C1 controls
    # (U+0080-U+009F + zero-width / bidi U+200B-U+200F, U+202A-U+202E),
    # all of which break various downstream parsers (Excel, pandas
    # strict-encoding, SWE-bench grader).
    diff = diff.replace("\r\n", "\n").replace("\r", "")
    cleaned_chars = []
    for c in diff:
        cp = ord(c)
        if c in "\t\n":
            cleaned_chars.append(c)
            continue
        if cp < 0x20:               # C0 controls (excluding \t\n above)
            continue
        if 0x7F <= cp <= 0x9F:      # DEL + C1 controls
            continue
        if cp == 0xFEFF:            # BOM
            continue
        if 0x200B <= cp <= 0x200F:  # zero-width / RTL marks
            continue
        if 0x202A <= cp <= 0x202E:  # bidi override
            continue
        cleaned_chars.append(c)
    cleaned = "".join(cleaned_chars)
    if not cleaned:
        return ""
    # Excel formula-injection: if the first non-whitespace char is one
    # of the dangerous prefixes, prepend a leading apostrophe. `\t` and
    # `\r` no longer appear after the strip above; keep `=+-@` only.
    leader = cleaned.lstrip()[:1]
    if leader in ("=", "+", "-", "@"):
        cleaned = "'" + cleaned
    return cleaned


# Wave 11: hoist LLM() across instances. anthropic.Client holds an
# httpx connection pool; constructing a fresh LLM per instance leaked
# ~5-10 MB of RSS per instance and OOM-killed the run around #800-1200
# on a 1865-instance Pro sweep. One LLM per process, threadsafe per
# the Anthropic SDK's documented invariants.
_SHARED_LLM = None
# Wave 12 (council F12a): lock around lazy init so two pipeline calls
# starting near-simultaneously don't double-construct the LLM (which
# would leak a second httpx pool and stomp on the first's connections).
_SHARED_LLM_LOCK = threading.Lock()


def _get_shared_llm():
    global _SHARED_LLM
    if _SHARED_LLM is not None:
        return _SHARED_LLM
    with _SHARED_LLM_LOCK:
        if _SHARED_LLM is None:
            from maverick.llm import LLM
            _SHARED_LLM = LLM()
        return _SHARED_LLM


def _reset_workdir(workdir, base_commit: str = "") -> None:
    """Wave 11: reset workdir to a known clean state between instances.

    The harness's sandbox workdir is shared across instances when using
    LocalBackend (or a mounted volume on Docker). Without this reset,
    git state from instance N pollutes instance N+1's run — pre-applied
    edits, untracked files, branch tip drift. Documented as +10-25pp
    silent score leak in operational-failure research.

    Best-effort: failures are logged but not raised so a missing-git
    workdir (e.g., synthetic dry-run paths) doesn't abort the run.
    """
    import subprocess
    from pathlib import Path
    workdir_path = Path(workdir)
    if not workdir_path.exists() or not (workdir_path / ".git").exists():
        return
    try:
        if base_commit:
            subprocess.run(
                ["git", "-C", str(workdir_path), "reset", "--hard", base_commit],
                capture_output=True, timeout=30,
            )
        else:
            subprocess.run(
                ["git", "-C", str(workdir_path), "reset", "--hard", "HEAD"],
                capture_output=True, timeout=30,
            )
        subprocess.run(
            ["git", "-C", str(workdir_path), "clean", "-fdx"],
            capture_output=True, timeout=30,
        )
        # Strip reflog/branches/tags that could leak the gold patch
        # (Princeton issue #465). Best-effort; failures don't block.
        if os.environ.get("MAVERICK_BENCHMARK_OPAQUE", "1") != "0":
            subprocess.run(
                ["git", "-C", str(workdir_path), "reflog", "expire",
                 "--expire=all", "--all"],
                capture_output=True, timeout=15,
            )
            subprocess.run(
                ["git", "-C", str(workdir_path), "gc", "--prune=now", "--quiet"],
                capture_output=True, timeout=30,
            )
    except (subprocess.SubprocessError, OSError):
        pass


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

    Wave 11: LLM is hoisted to a process-wide singleton (no RSS leak),
    workdir is reset before the run (no state bleed), per-instance
    cost is hard-capped, Pro `requirements`/`interface` fields are
    surfaced into the brief, and the 30-turn productivity ceiling is
    honored (most successful Pro solutions resolve in ~25 turns per
    Scale Labs' empirical study).
    """
    if os.environ.get("MAVERICK_BENCH_DRY_RUN") == "1":
        return _dry_run_row(instance_id, "maverick")

    import asyncio
    from maverick.budget import Budget
    from maverick.coding_mode import extract_unified_diff
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
        "MAVERICK_BASE_COMMIT", "MAVERICK_GOLD_PATCH",
    )
    _prior_env = {k: os.environ.get(k) for k in _env_keys}
    os.environ["MAVERICK_FAIL_TO_PASS"] = "||".join(kwargs.get("fail_to_pass") or [])
    os.environ["MAVERICK_PASS_TO_PASS"] = "||".join(kwargs.get("pass_to_pass") or [])
    os.environ["MAVERICK_LANGUAGE"] = str(kwargs.get("language") or "")
    base_commit = str(kwargs.get("base_commit") or "")
    if base_commit:
        os.environ["MAVERICK_BASE_COMMIT"] = base_commit
    # Wave 12 hotfix: complete the gold-patch plumbing. The agent's
    # defensive_validate reads via coding_mode.get_gold_patch() which
    # pops MAVERICK_GOLD_PATCH from env on first call (security). Before
    # this fix the harness never SET the env var, so the cheating
    # detector silently never fired. We set it from the manifest's
    # `gold_patch` field; coding_mode.reset_gold_patch_cache() is
    # called below so per-instance values don't bleed across instances.
    gold_patch = str(kwargs.get("gold_patch") or "")
    if gold_patch:
        os.environ["MAVERICK_GOLD_PATCH"] = gold_patch
    try:
        from maverick.coding_mode import reset_gold_patch_cache
        reset_gold_patch_cache()
    except Exception:
        pass

    # Wave 11 (D8): reset workdir to a clean state before the run so
    # state from instance N-1 doesn't pollute. Also strips reflog/tags
    # that could leak gold (Princeton issue #465).
    try:
        sandbox_pre = build_sandbox()
        _reset_workdir(sandbox_pre.workdir, base_commit=base_commit)
    except Exception:
        pass

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

    # Wave 11: surface Pro `requirements` + `interface` fields. SWE-bench
    # Pro adds these as part of issue augmentation; harnesses that drop
    # them lose easy points because the agent has to infer the spec.
    pro_block = ""
    requirements = (kwargs.get("requirements") or "").strip()
    interface = (kwargs.get("interface") or "").strip()
    if requirements or interface:
        parts = []
        if requirements:
            parts.append(f"REQUIREMENTS (from Pro spec):\n{requirements}")
        if interface:
            parts.append(f"INTERFACE (expected class/function signatures):\n{interface}")
        pro_block = "\n\n" + "\n\n".join(parts)

    enriched_brief = brief + pro_block + failing_test_context

    start = time.monotonic()
    world = WorldModel()
    llm = _get_shared_llm()
    gid = world.create_goal(f"swe-bench:{instance_id}", enriched_brief)
    # Wave 11: per-instance hard cost cap honors operator's
    # --instance-hard-cap; defaults to $3 to align with Scale's published
    # Pro budget. Wall is capped at 25 turns x 60s = 25 min effective.
    instance_cap = float(os.environ.get("MAVERICK_INSTANCE_HARD_CAP", "3.0"))
    instance_wall = float(os.environ.get("MAVERICK_INSTANCE_WALL_SEC", "1500"))
    budget = Budget(max_dollars=instance_cap, max_wall_seconds=instance_wall)
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
        # Wave 11 (D18): release the per-instance WorldModel SQLite
        # connection. Without this, 1865 instances leak 1865 open file
        # descriptors and SQLite WAL handles.
        try:
            world.close()
        except Exception:
            pass

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

    # Wave 11: surface tool-use signals + verifier confidence + trace
    # data for adoption tripwire + forensics. The agent posts these
    # to the blackboard which mirrors into goal_events.
    try:
        events = world.goal_events(gid, limit=2000)
    except Exception:
        events = []
    str_replace_used = any(
        "search_replace_used=1" in (e.content or "")
        for e in events
    )
    verifier_events = [
        e.content for e in events
        if e.kind == "verify"
    ]
    tool_invocations = [
        e.content for e in events
        if e.kind == "observation" and (e.content or "").startswith("tool=")
    ]
    tool_names = set()
    for tinv in tool_invocations:
        if tinv.startswith("tool="):
            name = tinv.split("=", 1)[1].split(" ", 1)[0].rstrip(",")
            tool_names.add(name)

    extra_payload: dict = {
        "goal_id": gid,
        "run_text": (result or "")[:500],
        "str_replace_editor_used": bool(str_replace_used),
        "tool_names": sorted(tool_names),
        "verify_event_count": len(verifier_events),
        "num_turns": len(tool_invocations),
    }
    # Optional per-instance JSON sidecar for forensics.
    trace_dir = os.environ.get("MAVERICK_TRACE_DIR")
    if trace_dir:
        try:
            from pathlib import Path as _Path
            from dataclasses import asdict as _asdict
            tp = _Path(trace_dir)
            tp.mkdir(parents=True, exist_ok=True)
            safe_id = instance_id.replace("/", "_")
            sidecar = tp / f"{safe_id}.jsonl"
            with sidecar.open("w", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(_asdict(e), default=str) + "\n")
        except Exception as e:
            print(f"warning: trace write failed for {instance_id}: {e}",
                  file=sys.stderr)

    return Row(
        instance_id=instance_id,
        pipeline="maverick",
        model_id=getattr(llm, "model", ""),
        wall_seconds=time.monotonic() - start,
        cost_dollars=total_cost,
        tokens_in=total_in,
        tokens_out=total_out,
        # Wave 12 fix: SWE-bench Pro grader has no patch-size cap; the
        # previous [:50_000] silently truncated mid-hunk on multi-file
        # refactors (Django/pandas instances ~60-100KB). Sanitize NUL
        # bytes (csv.DictReader fails on them, breaking resume) and
        # neutralize CSV-formula-injection prefixes (Excel auto-executes
        # cells starting with =+-@\t\r — patch lines naturally start
        # with `+`/`-`).
        predicted_patch=_sanitize_patch_for_csv(diff),
        outcome=last_outcome or ("success" if diff else "no-diff"),
        extra=extra_payload,
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
    for lineno, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
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
            brief = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
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
    with out_path.open("a", newline="", encoding="utf-8") as f:
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


def _write_run_meta(out_dir: Path, args, manifest_path: Path) -> Path:
    """Wave 12 (council F16): emit run_meta.json next to the results CSV.

    Captures everything needed to reproduce or audit a run:
      - Maverick git rev (HEAD sha)
      - manifest SHA-256
      - pip freeze
      - Anthropic API client version
      - relevant env vars (MAVERICK_*, ANTHROPIC_*)
      - CLI args
      - host info (python version, platform)
    """
    import hashlib
    import platform
    import subprocess as _sp
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "run_meta.json"

    # Maverick git rev — best-effort.
    try:
        rev = _sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5,
        )
        git_sha = rev.stdout.strip() if rev.returncode == 0 else "unknown"
    except (OSError, _sp.SubprocessError):
        git_sha = "unknown"

    # Manifest SHA — pins the exact instance set evaluated.
    manifest_sha = "unknown"
    try:
        if manifest_path.exists():
            h = hashlib.sha256()
            h.update(manifest_path.read_bytes())
            manifest_sha = h.hexdigest()
    except OSError:
        pass

    # pip freeze — pinned dep snapshot.
    # Wave 12 hardening: 120s timeout (was 30s) because pip freeze on a
    # fresh venv with many packages on a slow CI worker can take 60+s.
    # 30s silently returned empty pip_freeze, defeating the audit purpose.
    try:
        freeze = _sp.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, timeout=120,
        )
        pip_freeze = freeze.stdout if freeze.returncode == 0 else ""
        if not pip_freeze:
            print(
                "warning: pip freeze returned empty output for run_meta.json",
                file=sys.stderr,
            )
    except (OSError, _sp.SubprocessError) as e:
        pip_freeze = ""
        print(f"warning: pip freeze failed for run_meta.json: {e}",
              file=sys.stderr)

    # Anthropic SDK version.
    try:
        import anthropic as _a
        anthropic_version = getattr(_a, "__version__", "unknown")
    except Exception:
        anthropic_version = "not-installed"

    # Env vars that affect behavior — capture but redact API keys.
    env_snapshot = {}
    for k, v in os.environ.items():
        if not (k.startswith("MAVERICK_") or k.startswith("ANTHROPIC_")
                or k in ("OPENAI_API_KEY",)):
            continue
        if "KEY" in k or "TOKEN" in k or "SECRET" in k:
            env_snapshot[k] = "REDACTED" if v else ""
        else:
            env_snapshot[k] = v

    meta = {
        "started_at": time.time(),
        "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "maverick_git_sha": git_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "pip_freeze": pip_freeze,
        "anthropic_sdk_version": anthropic_version,
        "anthropic_version_header": "2023-06-01",
        "env_snapshot": env_snapshot,
        "cli_args": {
            k: (str(v) if isinstance(v, Path) else v)
            for k, v in vars(args).items()
        },
        "host": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8",
    )
    return meta_path


def already_done(out_path: Path) -> set[tuple[str, str]]:
    """Read out_path and return the set of (instance_id, pipeline) pairs
    already written AND that succeeded. Used by main() to skip on resume.

    Wave 10 (D12): csv.Error during read no longer silently empties the
    set; instead we log a visible warning so a partial-write race or
    corrupt CSV doesn't trigger a SILENT re-run that double-charges.

    Wave 12 (council F11b): rows whose `outcome` starts with "error:"
    are NOT marked done. The agent errored (sandbox crash, API
    outage, etc) without producing a real patch — resuming should
    retry these, not skip them.
    """
    if not out_path.exists():
        return set()
    done: set[tuple[str, str]] = set()
    error_rows = 0
    try:
        with out_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                outcome = (row.get("outcome") or "").strip()
                if outcome.startswith("error:"):
                    error_rows += 1
                    continue
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
    if error_rows:
        print(
            f"info: {error_rows} error row(s) found in {out_path} — "
            "they will be retried (Wave 12: errors no longer mark a "
            "row as done)",
            file=sys.stderr,
        )
    return done


# Wave 12 (council F11a): clean-exit flag shared with signal handler.
# Set on SIGTERM; the main loop checks it after each row write and
# exits gracefully (last row flushed, partial accounting reported).
_TERMINATE_REQUESTED: bool = False


def _on_sigterm(signum, frame) -> None:  # pragma: no cover (signal)
    global _TERMINATE_REQUESTED
    _TERMINATE_REQUESTED = True
    # Single line, no stdlib calls beyond stdio — signal handlers are
    # async-signal-safe restricted.
    try:
        sys.stderr.write(
            "\nSIGTERM received; finishing current row + exiting...\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def main() -> int:
    # Wave 12 (F11a): install SIGTERM handler so cloud schedulers
    # (kubelet, systemd, AWS Batch) get a clean shutdown instead of
    # an unflushed CSV. SIGINT (Ctrl-C) is already caught by the
    # KeyboardInterrupt block.
    # Wave 12 hardening: reset the global flag so reentry (tests calling
    # main() twice in one process, harness wrappers, etc.) doesn't
    # immediately short-circuit because a prior call set the flag.
    global _TERMINATE_REQUESTED
    _TERMINATE_REQUESTED = False
    import signal as _signal
    try:
        _signal.signal(_signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError, AttributeError):
        # Some environments (Windows w/o SIGTERM symbol, embedded threads)
        # reject signal registration; harness still works, just less
        # graceful on TERM.
        pass

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
    ap.add_argument("--instance-hard-cap", type=float, default=None,
                    help="Hard per-instance $ cap (sets MAVERICK_INSTANCE_HARD_CAP).")
    ap.add_argument("--worker-index", type=int, default=0,
                    help="Shard index (0..num-workers-1). Wave 11 (D8 shard).")
    ap.add_argument("--num-workers", type=int, default=1,
                    help="Total number of parallel shards.")
    ap.add_argument("--adoption-tripwire", type=float, default=None,
                    help="Abort if SEARCH/REPLACE adoption rate < N (0.0-1.0) "
                    "after the first 25 instances. Sentinel for prompt drift.")
    ap.add_argument("--max-consecutive-failures", type=int, default=10,
                    help="Wave 12 (F11e): abort if N consecutive instances "
                    "error out (likely API outage / quota exhaustion / "
                    "sandbox crash). 0 to disable.")
    args = ap.parse_args()

    if not args.instances.exists():
        print(f"manifest not found: {args.instances}", file=sys.stderr)
        return 2

    if args.instance_hard_cap is not None:
        os.environ["MAVERICK_INSTANCE_HARD_CAP"] = str(args.instance_hard_cap)

    # Wave 12 (F16): write run_meta.json before the first instance so a
    # crash mid-run still leaves provenance for replay/audit. Sibling to
    # the results CSV.
    try:
        meta_path = _write_run_meta(args.out.parent, args, args.instances)
        print(f"run_meta: {meta_path}", file=sys.stderr)
    except Exception as e:
        print(f"warning: run_meta.json write failed: {e}", file=sys.stderr)

    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    for p in pipelines:
        if p not in _PIPELINE_FNS:
            print(f"unknown pipeline: {p}", file=sys.stderr)
            return 2

    instances = load_instances(args.instances)
    # Wave 11 (D8): shard by hash(instance_id) % num_workers so two
    # parallel harness processes don't redo each other's work even
    # though both started with the same manifest.
    if args.num_workers > 1:
        import hashlib
        instances = [
            inst for inst in instances
            if (int(hashlib.sha256(inst["instance_id"].encode()).hexdigest(), 16)
                % args.num_workers) == args.worker_index
        ]
        print(f"shard {args.worker_index}/{args.num_workers}: "
              f"{len(instances)} instances assigned", file=sys.stderr)

    done = set() if args.no_resume else already_done(args.out)
    if done:
        print(f"resuming: {len(done)} (instance,pipeline) pairs already in {args.out}",
              file=sys.stderr)

    total_spend = 0.0
    skipped = 0
    written = 0
    # Wave 11: adoption tripwire counters.
    str_replace_uses = 0
    instances_with_str_replace_signal = 0
    # Wave 12 (F11e): consecutive-failure counter for circuit breaker.
    consecutive_failures = 0

    try:
        for inst in instances:
            if _TERMINATE_REQUESTED:
                print("SIGTERM exit: stopping instance iteration",
                      file=sys.stderr)
                break
            iid = inst["instance_id"]
            brief = inst.get("brief", "")
            extra = {
                "fail_to_pass": inst.get("fail_to_pass", []) or [],
                "pass_to_pass": inst.get("pass_to_pass", []) or [],
                "gold_patch": inst.get("gold_patch", "") or "",
                "language": inst.get("language", "") or "",
                # Wave 11: Pro-specific manifest fields.
                "base_commit": inst.get("base_commit", "") or "",
                "requirements": inst.get("requirements", "") or "",
                "interface": inst.get("interface", "") or "",
            }
            for pipeline in pipelines:
                if _TERMINATE_REQUESTED:
                    break
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
                # Wave 12 (F11e) + hardening: consecutive-failure
                # circuit breaker. A "failure" outcome (pipeline caught
                # an API error and downgraded to failure) should ALSO
                # count toward the breaker — only explicitly successful
                # outcomes reset the counter. Otherwise a pipeline that
                # swallows errors internally defeats the safety net.
                outcome_clean = row.outcome.strip().lower()
                is_failure_class = (
                    outcome_clean.startswith("error")
                    or outcome_clean.startswith("failure")
                    or outcome_clean.startswith("budget")
                )
                if is_failure_class:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                if (args.max_consecutive_failures > 0
                        and consecutive_failures >= args.max_consecutive_failures):
                    print(
                        f"ABORT: {consecutive_failures} consecutive errors "
                        f"(>={args.max_consecutive_failures}). Likely API "
                        "outage / quota / sandbox issue — bail before "
                        "burning through the manifest. Last error: "
                        f"{row.outcome}",
                        file=sys.stderr,
                    )
                    return 5
                # Wave 11: track SEARCH/REPLACE adoption via extra signal.
                if pipeline == "maverick":
                    if row.extra.get("str_replace_editor_used"):
                        str_replace_uses += 1
                    if "str_replace_editor_used" in row.extra:
                        instances_with_str_replace_signal += 1
                print(f"{iid}\t{pipeline}\t{row.outcome}\t"
                      f"${row.cost_dollars:.3f}\t{row.wall_seconds:.1f}s"
                      f"\ttotal=${total_spend:.2f}")
                # Wave 11: adoption tripwire. After 25 instances, if
                # SEARCH/REPLACE adoption is below the threshold, abort
                # so we don't burn $4k on a degenerate run.
                if (args.adoption_tripwire is not None
                        and instances_with_str_replace_signal >= 25):
                    rate = str_replace_uses / instances_with_str_replace_signal
                    if rate < args.adoption_tripwire:
                        print(
                            f"ABORT: SEARCH/REPLACE adoption {rate:.1%} < "
                            f"{args.adoption_tripwire:.1%} after "
                            f"{instances_with_str_replace_signal} instances. "
                            f"Spent: ${total_spend:.2f}. Prompt likely "
                            "regressed; check tool-use template before "
                            "scaling up.", file=sys.stderr,
                        )
                        return 4
    except KeyboardInterrupt:
        print(f"\nSIGINT caught; {written} row(s) flushed to {args.out}",
              file=sys.stderr)
        return 130

    if _TERMINATE_REQUESTED:
        print(f"\nSIGTERM exit: {written} row(s) flushed to {args.out}; "
              f"total ${total_spend:.2f}", file=sys.stderr)
        return 143  # 128 + SIGTERM(15)

    print(f"\n{written} row(s) appended to {args.out}; "
          f"{skipped} skipped (already done); total ${total_spend:.2f}")
    if instances_with_str_replace_signal > 0:
        rate = str_replace_uses / instances_with_str_replace_signal
        print(f"SEARCH/REPLACE adoption: {rate:.1%} "
              f"({str_replace_uses}/{instances_with_str_replace_signal})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
