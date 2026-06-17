"""Reproducible benchmark harness v2 (ROADMAP 2027 H1 Distribution).

The repo-root ``benchmarks/`` harnesses answer "how well did we score?".
This answers a different question that matters for a *published* number:
**can a third party re-run it and get the same thing?** A claimed score is
only credible if the conditions are pinned and the run is byte-reproducible.

So this harness runs a benchmark suite under explicitly pinned conditions
(seed, model id, prompt-template hash, tool-set hash) and emits a signed
manifest -- ``{suite, seed, env_fingerprint, per-task results, aggregate}``
-- that a third party stores, re-runs, and diffs against their own manifest.
Any divergence (a task that scored differently, an env that drifted) is
surfaced by ``verify_manifests`` / ``--verify``, naming the task that broke.

Two seams keep it deterministic and offline, mirroring ``benchmarks/evals.py``:

  * A **suite** is just a list of ``Task`` (id, prompt, answer). A tiny
    built-in suite ships so the harness self-tests without any dataset.
  * A **solver** ``Callable[[Task], str]`` turns one task into an answer. It
    is injected, so tests pass a deterministic scripted fixture and the whole
    harness runs end-to-end with no LLM and no network. ``RunConditions.seed``
    is threaded to the solver so a stochastic real solver can pin its RNG.

The manifest is signed with HMAC-SHA256 over its canonical JSON (the same
construction ``maverick.webhooks`` uses), so tampering or accidental drift in
a stored manifest is detectable. Signing is optional: with no key the manifest
carries ``signature: null`` and ``verify_manifests`` still diffs the content.

CLI::

    # run the built-in suite with a scripted oracle and write a manifest
    python -m maverick.benchmarks.reproducible_v2 run --out baseline.json

    # re-run later, then diff two manifests for non-determinism
    python -m maverick.benchmarks.reproducible_v2 run --out current.json
    python -m maverick.benchmarks.reproducible_v2 --verify baseline.json current.json
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Manifest format version. Bump on a breaking change to the manifest shape so
# a verifier can refuse to diff manifests it can't interpret.
MANIFEST_VERSION = 2


@dataclass(frozen=True)
class Task:
    """One reproducibility task: a prompt plus its ground-truth answer."""

    task_id: str
    prompt: str
    answer: str


# A solver turns one task into an answer string. ``seed`` is threaded so a
# stochastic real solver can pin its RNG; the offline fixtures ignore it.
Solver = Callable[..., str]


@dataclass(frozen=True)
class RunConditions:
    """The pinned conditions a run is reproducible *under*.

    These are the inputs a third party must match to reproduce a number.
    ``prompt_template`` / ``tool_set`` are hashed (not stored verbatim) so the
    manifest commits to them without bloating -- a differing template or tool
    set changes the fingerprint and the verifier flags it.
    """

    seed: int = 0
    model_id: str = "fixture/offline"
    prompt_template: str = ""
    tool_set: tuple[str, ...] = ()

    def prompt_hash(self) -> str:
        return _sha256_hex(self.prompt_template.encode("utf-8"))

    def tool_set_hash(self) -> str:
        # Order-independent: the *set* of tools is what matters, not the order
        # they happened to be registered in.
        joined = "\n".join(sorted(self.tool_set)).encode("utf-8")
        return _sha256_hex(joined)


@dataclass
class TaskResult:
    """The graded outcome of one task under the pinned conditions."""

    task_id: str
    score: float
    passed: bool
    expected: str
    got: str


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no incidental whitespace.

    The signature and any content diff are taken over exactly these bytes, so
    two runs that are semantically identical hash identically regardless of
    dict insertion order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def env_fingerprint(conditions: RunConditions) -> dict[str, Any]:
    """Capture the pinned conditions + the interpreter env as a flat dict.

    Python version + implementation are recorded because a benchmark can be
    bit-sensitive to them; the verifier reports an env drift as a warning (it
    does not, by itself, fail the diff -- a score divergence does).
    """
    return {
        "seed": conditions.seed,
        "model_id": conditions.model_id,
        "prompt_hash": conditions.prompt_hash(),
        "tool_set_hash": conditions.tool_set_hash(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }


def _score_exact(task: Task, output: str) -> float:
    """Normalized exact match. 1.0 iff the answer matches case/space-folded.

    A deliberately simple, deterministic scorer -- the harness's job is
    reproducibility, not GAIA-grade grading (``benchmarks/eval_gaia.py`` owns
    that). A real suite can pass its own scorer via ``run_suite(scorer=...)``.
    """
    return 1.0 if output.strip().lower() == task.answer.strip().lower() else 0.0


# A scorer grades one task's output in [0.0, 1.0]. Injected; defaults to exact.
Scorer = Callable[[Task, str], float]


def builtin_suite() -> list[Task]:
    """A tiny deterministic suite so the harness self-tests with no dataset."""
    return [
        Task("arith-1", "2 + 2 = ?", "4"),
        Task("capital-1", "Capital of France?", "Paris"),
        Task("bool-1", "Is 7 prime? yes/no", "yes"),
    ]


def run_suite(
    suite: list[Task],
    solver: Solver,
    conditions: RunConditions,
    *,
    scorer: Scorer = _score_exact,
) -> dict[str, Any]:
    """Run every task through ``solver`` under ``conditions``, score, aggregate.

    A solver that raises is recorded as a 0-score result (its exception text
    becomes ``got``) rather than aborting the run -- one flaky task must not
    sink the suite (mirrors ``benchmarks/evals.run_benchmark``). Results are
    sorted by ``task_id`` so the manifest is order-stable across runs.

    Returns a manifest *body* (no signature yet); ``build_manifest`` signs it.
    """
    results: list[TaskResult] = []
    for task in suite:
        try:
            out = solver(task, seed=conditions.seed)
        except TypeError:
            # Tolerate a solver that doesn't accept a seed kwarg.
            out = solver(task)
        except Exception as e:  # one bad task != a dead suite
            out = f"ERROR: {type(e).__name__}: {e}"
        sc = max(0.0, min(1.0, float(scorer(task, out))))
        results.append(
            TaskResult(
                task_id=task.task_id,
                score=sc,
                passed=sc >= 1.0,
                expected=task.answer,
                got=out,
            )
        )
    results.sort(key=lambda r: r.task_id)
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    aggregate = {
        "n": n,
        "passed": passed,
        "pass_at_1": round(passed / n, 6) if n else 0.0,
        "mean_score": round(sum(r.score for r in results) / n, 6) if n else 0.0,
    }
    return {
        "version": MANIFEST_VERSION,
        "suite": _suite_id(suite),
        "seed": conditions.seed,
        "env_fingerprint": env_fingerprint(conditions),
        "results": [
            {
                "task_id": r.task_id,
                "score": r.score,
                "passed": r.passed,
                "expected": r.expected,
                "got": r.got,
            }
            for r in results
        ],
        "aggregate": aggregate,
    }


def _suite_id(suite: list[Task]) -> str:
    """A stable id for a suite: a hash over its task ids + answers.

    Two manifests can only be meaningfully diffed if they ran the *same* suite;
    this id lets the verifier reject a mismatched pair instead of reporting
    every task as "diverged".
    """
    material = "\n".join(f"{t.task_id}={t.answer}" for t in sorted(suite, key=lambda t: t.task_id))
    return _sha256_hex(material.encode("utf-8"))[:16]


def sign_manifest(body: dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 over the canonical JSON of the manifest body.

    Same construction as ``maverick.webhooks._sign`` so the project has one
    signing idiom. Returns a ``sha256=<hex>`` string.
    """
    mac = hmac.new(secret.encode("utf-8"), _canonical_json(body), hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def build_manifest(
    suite: list[Task],
    solver: Solver,
    conditions: RunConditions,
    *,
    scorer: Scorer = _score_exact,
    secret: str | None = None,
) -> dict[str, Any]:
    """Run the suite and return a (optionally signed) manifest.

    The signature covers the body only; the ``signature`` field is added after
    signing so it never signs itself. With no ``secret`` the field is ``None``
    and the manifest is still fully diffable -- signing is integrity, not a
    prerequisite for reproducibility checks.
    """
    body = run_suite(suite, solver, conditions, scorer=scorer)
    signature = sign_manifest(body, secret) if secret else None
    return {**body, "signature": signature}


def verify_signature(manifest: dict[str, Any], secret: str) -> bool:
    """True iff ``manifest``'s signature matches a re-sign of its body."""
    sig = manifest.get("signature")
    if not isinstance(sig, str) or not sig.startswith("sha256="):
        return False
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return hmac.compare_digest(sig.encode(), sign_manifest(body, secret).encode())


@dataclass
class DiffReport:
    """The outcome of diffing two manifests for reproducibility."""

    reproducible: bool
    suite_match: bool
    env_drift: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    diverged_tasks: list[dict[str, Any]] = field(default_factory=list)
    only_in_baseline: list[str] = field(default_factory=list)
    only_in_current: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reproducible": self.reproducible,
            "suite_match": self.suite_match,
            "env_drift": {k: list(v) for k, v in self.env_drift.items()},
            "diverged_tasks": self.diverged_tasks,
            "only_in_baseline": self.only_in_baseline,
            "only_in_current": self.only_in_current,
            "reasons": self.reasons,
        }


def _results_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["task_id"]: r for r in manifest.get("results", [])}


def verify_manifests(baseline: dict[str, Any], current: dict[str, Any]) -> DiffReport:
    """Diff two manifests and flag non-determinism, naming what diverged.

    Reproducible == same suite, no task scored/answered differently, and no
    task added or dropped. Env drift (e.g. a different Python version) is
    reported but does NOT by itself fail reproducibility -- only a behavioural
    divergence does, because that is the thing a third party actually cares
    about. The report lists every diverging task with both ``got`` values so a
    human can see exactly where the runs parted ways.
    """
    report = DiffReport(reproducible=True, suite_match=True)

    if baseline.get("suite") != current.get("suite"):
        report.suite_match = False
        report.reproducible = False
        report.reasons.append(
            f"suite mismatch: baseline {baseline.get('suite')!r} != "
            f"current {current.get('suite')!r} (different tasks; not comparable)"
        )

    base_env = baseline.get("env_fingerprint", {})
    cur_env = current.get("env_fingerprint", {})
    for key in sorted(set(base_env) | set(cur_env)):
        if base_env.get(key) != cur_env.get(key):
            report.env_drift[key] = (base_env.get(key), cur_env.get(key))
    if report.env_drift:
        report.reasons.append(
            "env drift (advisory): " + ", ".join(sorted(report.env_drift))
        )

    base_r = _results_by_id(baseline)
    cur_r = _results_by_id(current)
    report.only_in_baseline = sorted(set(base_r) - set(cur_r))
    report.only_in_current = sorted(set(cur_r) - set(base_r))
    if report.only_in_baseline or report.only_in_current:
        report.reproducible = False
        report.reasons.append(
            "task set changed: "
            f"{len(report.only_in_baseline)} dropped, "
            f"{len(report.only_in_current)} added"
        )

    for task_id in sorted(set(base_r) & set(cur_r)):
        b, c = base_r[task_id], cur_r[task_id]
        if b.get("score") != c.get("score") or b.get("got") != c.get("got"):
            report.diverged_tasks.append(
                {
                    "task_id": task_id,
                    "baseline_score": b.get("score"),
                    "current_score": c.get("score"),
                    "baseline_got": b.get("got"),
                    "current_got": c.get("got"),
                }
            )
    if report.diverged_tasks:
        report.reproducible = False
        names = ", ".join(t["task_id"] for t in report.diverged_tasks)
        report.reasons.append(f"non-determinism: {len(report.diverged_tasks)} task(s) diverged: {names}")

    if report.reproducible and not report.reasons:
        report.reasons.append("reproducible: every task matched the baseline")
    return report


# ---- CLI --------------------------------------------------------------------

def _oracle_solver(task: Task, *, seed: int = 0) -> str:  # noqa: ARG001 - seed unused offline
    """Answer every task with its ground truth -> a perfect, stable run."""
    return task.answer


def _resolve_secret(arg_secret: str | None) -> str | None:
    """Signing key from --secret or ``MAVERICK_BENCH_SECRET`` (env wins if set)."""
    return os.environ.get("MAVERICK_BENCH_SECRET") or arg_secret


def _cmd_run(args: argparse.Namespace) -> int:
    conditions = RunConditions(
        seed=args.seed,
        model_id=args.model_id,
        prompt_template=args.prompt_template,
        tool_set=tuple(args.tool or ()),
    )
    manifest = build_manifest(
        builtin_suite(), _oracle_solver, conditions, secret=_resolve_secret(args.secret)
    )
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote manifest: {args.out} (suite={manifest['suite']}, "
              f"pass@1={manifest['aggregate']['pass_at_1']})")
    else:
        print(text)
    return 0


def _cmd_verify(baseline_path: str, current_path: str, secret: str | None) -> int:
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))

    if secret:
        for label, m in (("baseline", baseline), ("current", current)):
            if m.get("signature") is not None and not verify_signature(m, secret):
                print(f"SIGNATURE INVALID: {label} manifest failed HMAC verification",
                      file=sys.stderr)
                return 3

    report = verify_manifests(baseline, current)
    print(json.dumps(report.to_dict(), indent=2))
    if report.reproducible:
        print("REPRODUCIBLE: runs match", file=sys.stderr)
        return 0
    print("NON-REPRODUCIBLE: " + "; ".join(report.reasons), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m maverick.benchmarks.reproducible_v2",
        description="Deterministic reproducibility harness: pinned conditions + signed manifest.",
    )
    # --verify is a top-level mode so the documented `--verify a.json b.json`
    # invocation works without a subcommand.
    ap.add_argument(
        "--verify", nargs=2, metavar=("BASELINE", "CURRENT"),
        help="diff two manifests for non-determinism and exit non-zero if they diverge",
    )
    ap.add_argument("--secret", default=None, help="HMAC signing/verification key")
    sub = ap.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="run the built-in suite and emit a signed manifest")
    run_p.add_argument("--out", default=None, help="write the manifest JSON here (else stdout)")
    run_p.add_argument("--seed", type=int, default=0)
    run_p.add_argument("--model-id", default="fixture/offline")
    run_p.add_argument("--prompt-template", default="", help="prompt template text (hashed into the fingerprint)")
    run_p.add_argument("--tool", action="append", default=[], help="declare a tool in the pinned tool set (repeatable)")
    run_p.add_argument("--secret", default=None, help="HMAC signing key")
    run_p.set_defaults(func=_cmd_run)

    args = ap.parse_args(argv)

    if args.verify:
        return _cmd_verify(args.verify[0], args.verify[1], _resolve_secret(args.secret))
    if getattr(args, "func", None):
        return args.func(args)
    ap.print_help()
    return 2


__all__ = [
    "Task",
    "Solver",
    "Scorer",
    "RunConditions",
    "TaskResult",
    "DiffReport",
    "MANIFEST_VERSION",
    "builtin_suite",
    "env_fingerprint",
    "run_suite",
    "build_manifest",
    "sign_manifest",
    "verify_signature",
    "verify_manifests",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
