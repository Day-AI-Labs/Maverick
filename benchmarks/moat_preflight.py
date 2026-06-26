"""Free, no-API pre-flight for the moat run: prove the whole pipeline works
BEFORE spending a cent.

The $3.79 wasted in MOAT_RIGOROUS_RESULTS.md was 100% preventable -- the agent
never had the codebase, and a single free dry-run would have caught it. This
codifies "verify before you pay" as three checks, each fully offline:

  1. **sandbox-can-read** -- provision the codebase into a workspace, build the
     sandbox exactly as a run does, and confirm the agent's shell can actually
     READ a real source file. Catches the empty-``~/maverick-workspace`` bug
     directly (not just "files exist on disk").
  2. **grader-self-test** -- feed the citation grader a known-CORRECT answer
     (cites the real file) and a known-WRONG one; it must score them right, or
     we cannot trust it on paid answers.
  3. **distill-mechanism** -- two synthetic successful trajectories must produce
     a saved skill, so the populate phase will distill IF it gets >=2 successes
     (the single-run populate that silently distilled nothing is why warm often
     had no memory).

Run ``python benchmarks/moat_preflight.py`` and require READY before any paid
run. ``run_live`` also calls ``sandbox_can_read`` as its hard guard.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_CODEBASE = str(Path(__file__).resolve().parents[1]
                       / "packages" / "maverick-core" / "maverick")


def sandbox_can_read(codebase: str | Path) -> tuple[bool, str]:
    """Provision ``codebase`` into a workspace, build the sandbox the way a run
    does, and confirm the agent's shell can READ a real source file. Offline."""
    src = Path(codebase).expanduser()
    if not src.is_dir():
        return False, f"codebase {str(codebase)!r} is not a directory"
    pys = list(src.rglob("*.py"))
    if not pys:
        return False, f"codebase {str(codebase)!r} has no .py sources to mount"
    ws = Path(tempfile.mkdtemp(prefix="moat-preflight-"))
    try:
        import os
        os.environ.setdefault("MAVERICK_SUPPRESS_SANDBOX_WARNING", "1")
        dst = ws / src.name
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        rel = dst.relative_to(ws) / pys[0].relative_to(src)
        from maverick.sandbox import build_sandbox
        sb = build_sandbox(workdir=ws, backend="local")
        res = sb.exec(f"cat {rel}")
        out = str(getattr(res, "stdout", res) or "")
        if not out.strip():
            return False, f"sandbox returned empty content for {rel}"
        return True, f"sandbox read {rel} ({len(out)} bytes) of {len(pys)} sources"
    except Exception as e:  # pragma: no cover -- any failure here = NOT ready
        return False, f"sandbox read failed: {type(e).__name__}: {e}"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def cite_grader(answer: str, repo_files: set[str], topic_kws: list[str],
                *, min_cited: int = 1) -> tuple[bool, int]:
    """Objective correctness signal: the answer cites >= ``min_cited`` REAL repo
    files (not hallucinated) AND is on-topic. Pure/deterministic."""
    a = (answer or "").lower()
    cited = sum(1 for f in repo_files if f.lower() in a)
    topic = any(k in a for k in topic_kws)
    return bool(cited >= min_cited and topic), cited


def grader_self_test() -> tuple[bool, str]:
    """The grader must accept a known-correct answer and reject a known-wrong
    one, or it cannot be trusted on paid answers."""
    repo = {"tool_risk.py", "dreaming.py"}
    kws = ["risk", "ceiling"]
    right = "The per-tool risk ceiling is enforced in tool_risk.py (risk_rank)."
    wrong = "No codebase is available; I could not find any relevant file."
    if not cite_grader(right, repo, kws)[0]:
        return False, "grader REJECTED a known-correct answer"
    if cite_grader(wrong, repo, kws)[0]:
        return False, "grader ACCEPTED a known-wrong answer"
    return True, "grader scores known-correct vs known-wrong correctly"


def distill_mechanism_ok() -> tuple[bool, str]:
    """Two synthetic successful trajectories must produce a saved skill, so the
    populate phase will distill given >=2 successes."""
    from maverick.skill import distillation_v2 as v2
    trajs = [{"goal": "reconcile the general ledger to the bank statement",
              "success": True, "tools": ["read_file"], "t": 2},
             {"goal": "reconcile the quarterly ledger against bank records",
              "success": True, "tools": ["read_file"], "t": 1}]
    store = Path(tempfile.mkdtemp(prefix="moat-distill-"))
    try:
        path, reason = v2.distill_and_save_gated(trajs, store=store, min_examples=2)
        if path is None:
            return False, f"distill produced no skill: {reason}"
        return True, f"distill wrote a skill ({path.name})"
    finally:
        shutil.rmtree(store, ignore_errors=True)


def preflight(codebase: str | Path = DEFAULT_CODEBASE) -> list[tuple[str, bool, str]]:
    """Run all checks; returns ``[(name, ok, detail), ...]``."""
    return [
        ("sandbox-can-read", *sandbox_can_read(codebase)),
        ("grader-self-test", *grader_self_test()),
        ("distill-mechanism", *distill_mechanism_ok()),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Moat run pre-flight (no API, no spend)")
    ap.add_argument("--codebase", default=DEFAULT_CODEBASE)
    args = ap.parse_args(argv)
    print("Moat pre-flight (free / no API):")
    all_ok = True
    for name, ok, detail in preflight(args.codebase):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        all_ok = all_ok and ok
    print("\nREADY -- safe to spend." if all_ok
          else "\nNOT READY -- do NOT spend until every check is green.")
    return 0 if all_ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
