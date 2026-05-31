"""Stage SWE-bench Verified for a Maverick harness run.

Pulls `princeton-nlp/SWE-bench_Verified` from HuggingFace, converts each
instance to Maverick's manifest line format (JSONL), and (optionally)
shallow-clones each instance's repo at its `base_commit` into a workdir
tree the harness can run against.

Outputs:
  - manifest.jsonl: one line per instance, fields the harness consumes
  - repos/<instance_id>/: cloned + base-commit-checked-out trees (when
    --stage is passed). One workdir per instance; the harness must run
    instance-by-instance, swapping `MAVERICK_SANDBOX_WORKDIR` per row.

The schema was verified against the HF dataset card May 2026:
  - instance_id, repo, base_commit, patch, test_patch
  - problem_statement, hints_text, version
  - FAIL_TO_PASS, PASS_TO_PASS (JSON-encoded strings — we json.loads them)
  - environment_setup_commit, difficulty, created_at

Wave 12 hotfix companion: this is the script the runbook references for
the "stage Verified" step that the harness itself does NOT perform.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# SWE-bench instance ids look like `<org>__<repo>-<number>`, e.g.
# `django__django-12345`. Restrict to alphanumerics, `_`, `-`, and `.`
# so a malicious dataset row can't smuggle path traversal (`..`,
# absolute path, embedded slash) into the staging target.
_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def _validate_instance_id(iid: str) -> bool:
    """True iff `iid` is safe to join with the staging directory."""
    if not isinstance(iid, str) or not iid:
        return False
    if iid in (".", ".."):
        return False
    if not _INSTANCE_ID_RE.match(iid):
        return False
    return True


def _load_dataset(split: str = "test"):
    """Lazy import so the script doesn't require `datasets` for --help."""
    try:
        from datasets import load_dataset
    except ImportError:
        sys.stderr.write(
            "ERROR: `datasets` package not installed. Install with:\n"
            "    pip install datasets\n"
        )
        sys.exit(2)
    return load_dataset("princeton-nlp/SWE-bench_Verified", split=split)


def _row_to_manifest(row: dict) -> dict:
    """Convert one HF row to a Maverick manifest line.

    The harness's load_instances expects native types for fail_to_pass /
    pass_to_pass (lists, not JSON strings). It also reads `brief` as the
    plain-text problem statement and `gold_patch` for the cheating
    detector to compare against.
    """
    def _parse_test_list(value) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    return {
        "instance_id": row["instance_id"],
        "brief": row.get("problem_statement", ""),
        "repo": row.get("repo", ""),
        "base_commit": row.get("base_commit", ""),
        "environment_setup_commit": row.get("environment_setup_commit", ""),
        "fail_to_pass": _parse_test_list(row.get("FAIL_TO_PASS")),
        "pass_to_pass": _parse_test_list(row.get("PASS_TO_PASS")),
        "gold_patch": row.get("patch", ""),
        # test_patch is NOT included — that's the grader's test fixture,
        # not for the agent. Surfaced separately in run_meta if needed.
        "version": row.get("version", ""),
        "difficulty": row.get("difficulty", ""),
        "language": "python",  # SWE-bench Verified is Python-only
        "hints_text": row.get("hints_text", ""),
    }


def _write_manifest(rows: Iterable[dict], out_path: Path) -> int:
    n = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_row_to_manifest(row)) + "\n")
            n += 1
    return n


def _clone_instance(row: dict, repos_dir: Path, depth: int = 1) -> tuple[bool, str]:
    """Shallow-clone one instance's repo at base_commit."""
    iid = row["instance_id"]
    repo = row.get("repo", "")
    base_commit = row.get("base_commit", "")
    if not repo or not base_commit:
        return False, f"{iid}: missing repo or base_commit"
    if not _validate_instance_id(iid):
        return False, f"{iid!r}: unsafe instance_id (must match [A-Za-z0-9._-]+)"
    # Resolve and confirm containment so a future change can't regress.
    repos_root = repos_dir.resolve()
    target = (repos_dir / iid).resolve()
    try:
        target.relative_to(repos_root)
    except ValueError:
        return False, f"{iid!r}: resolves outside repos_dir {repos_root}"
    if target.exists():
        return True, f"{iid}: already staged"
    url = f"https://github.com/{repo}.git"
    target.mkdir(parents=True, exist_ok=True)
    try:
        # Full clone is needed to checkout a specific historical commit
        # that may predate `--depth=1`. Use --filter=blob:none for speed.
        proc = subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(target)],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            return False, f"{iid}: clone failed: {proc.stderr.decode('utf-8', 'replace')[:200]}"
        proc = subprocess.run(
            ["git", "-C", str(target), "checkout", "--detach", base_commit],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            return False, f"{iid}: checkout {base_commit[:8]} failed"
        return True, f"{iid}: cloned + at {base_commit[:8]}"
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"{iid}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-manifest", type=Path,
                    default=Path("benchmarks/swe_bench_verified.jsonl"),
                    help="Output JSONL manifest path.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Take only the first N instances (smoke). 0 = all.")
    ap.add_argument("--difficulty", type=str, default="",
                    help='Filter by difficulty: "<15 min", "15 min - 1 hour", etc.')
    ap.add_argument("--repos", type=str, default="",
                    help="Comma-separated repo allowlist (e.g. django/django).")
    ap.add_argument("--stage", action="store_true",
                    help="Also clone + checkout each instance's repo. Slow + needs disk.")
    ap.add_argument("--repos-dir", type=Path, default=Path("./repos"),
                    help="Where to put cloned instance trees (with --stage).")
    args = ap.parse_args()

    ds = _load_dataset()
    print(f"loaded {len(ds)} instances from princeton-nlp/SWE-bench_Verified",
          file=sys.stderr)

    rows = list(ds)
    if args.repos:
        wanted = {r.strip() for r in args.repos.split(",") if r.strip()}
        rows = [r for r in rows if r.get("repo") in wanted]
        print(f"after --repos filter: {len(rows)}", file=sys.stderr)
    if args.difficulty:
        rows = [r for r in rows if r.get("difficulty") == args.difficulty]
        print(f"after --difficulty filter: {len(rows)}", file=sys.stderr)
    if args.limit > 0:
        rows = rows[: args.limit]
        print(f"after --limit: {len(rows)}", file=sys.stderr)

    n = _write_manifest(rows, args.out_manifest)
    print(f"wrote {n} instances → {args.out_manifest}", file=sys.stderr)

    if args.stage:
        args.repos_dir.mkdir(parents=True, exist_ok=True)
        ok = 0
        fail = 0
        for row in rows:
            success, msg = _clone_instance(row, args.repos_dir)
            print(msg, file=sys.stderr)
            ok += 1 if success else 0
            fail += 0 if success else 1
        print(f"staged {ok} ok, {fail} failed → {args.repos_dir}",
              file=sys.stderr)
        if fail:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
