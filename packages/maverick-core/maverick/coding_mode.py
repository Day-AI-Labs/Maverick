"""Coding-mode prompts + patch validation for benchmark-grade output.

SWE-bench Pro (and the upstream evaluator) expects ONE unified diff,
not prose. Our default WORKER_SYSTEM_TEMPLATE produces prose-with-
diff which scores zero. This module ships:

  - CODER_CODING_MODE_TEMPLATE: replacement system prompt that
    enforces diff-only FINAL.
  - validate_patch(patch, workdir): runs `git apply --check` so the
    agent learns from a bad patch BEFORE submitting it.
  - extract_unified_diff(text): pulls the first valid diff out of an
    LLM reply (handles markdown fences + leading prose).
  - run_failing_tests(workdir, fail_to_pass, pass_to_pass, sandbox):
    test-driven verifier replacement for SWE-bench-style briefs.
    Returns a structured result the orchestrator uses instead of /
    alongside the LLM verifier.

The `--coding-mode` CLI flag (or [coding] mode=true config) wires
these in; default OFF so the consumer-facing kernel stays focused on
prose tasks.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CODER_CODING_MODE_TEMPLATE = """You are a coding agent solving a software engineering task.

Your role: {role}
Your depth: {depth} (root = 0, max = {max_depth})

OUTPUT FORMAT (STRICT):
When you have a fix ready, respond with EXACTLY this format:

FINAL:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -10,3 +10,3 @@
-old line
+new line
```

Rules:
1. ONE unified diff per FINAL. No prose explanation, no preamble,
   no markdown headers, no "I think" / "let me explain".
2. The diff MUST apply cleanly to HEAD via `git apply`. If you're
   unsure, run `read_file` to verify the exact line content before
   composing the diff.
3. Use `shell` to run tests + `git apply --check` before declaring
   FINAL. The orchestrator validates your patch and will reject
   if it doesn't apply.
4. Prefer the SMALLEST diff that makes the failing tests pass.
   Drive-by formatting changes will get the patch rejected.
5. If you need information, use `read_file` / `list_dir` / `shell`
   freely. Tool budget is not the bottleneck; correctness is.
6. The `spawn_subagent` and `spawn_swarm` tools are available for
   sub-tasks (e.g., "research how the test fixture is set up");
   they cannot themselves produce FINAL.

Available tools include file ops, shell (sandboxed), spawn_subagent,
spawn_swarm. End with `FINAL:` followed by the diff block."""


# Anthropic / SWE-bench reference diff regex. Tolerant of indent +
# markdown fences but requires the `--- a/... +++ b/...` header pair.
_DIFF_RE = re.compile(
    r"""
    (?:```(?:diff|patch)?\s*\n)?     # optional fence open
    (
        ---\s+a/.+?\n
        \+\+\+\s+b/.+?\n
        (?:@@.+?\n.*?)
        (?=                            # stop at:
            \n```                       # markdown fence close, OR
            | \Z                        # end of string
            | (?:\n---\s+a/)            # next file in multi-file diff
        )
    )
    """,
    re.DOTALL | re.VERBOSE,
)


def extract_unified_diff(text: str) -> Optional[str]:
    """Extract the first unified diff from an LLM reply.

    Returns the cleaned diff (no fences) or None if nothing
    diff-shaped is present.
    """
    if not text:
        return None
    # Strip the FINAL: prefix the agent uses to mark the boundary.
    work = text
    final_idx = work.find("FINAL:")
    if final_idx >= 0:
        work = work[final_idx + len("FINAL:"):]

    # Multi-file diffs: the regex stops at the next `--- a/`, so we
    # need to concat across hits. Simpler approach: find ALL hits and
    # join.
    hits = []
    pos = 0
    diff_start = re.compile(r"---\s+a/")
    fence_close = re.compile(r"```")
    while True:
        m = diff_start.search(work, pos)
        if m is None:
            break
        start = m.start()
        # Find the end: next fence close OR next "--- a/" OR EOF.
        next_diff = diff_start.search(work, m.end())
        next_fence = fence_close.search(work, m.end())
        end = len(work)
        if next_diff is not None:
            end = min(end, next_diff.start())
        if next_fence is not None:
            end = min(end, next_fence.start())
        hits.append(work[start:end].rstrip())
        pos = end
        if next_diff is None or next_diff.start() >= end:
            if next_fence is not None and next_fence.start() == end:
                break
            if next_diff is None:
                break

    if not hits:
        return None
    return "\n".join(hits).strip()


@dataclass
class PatchValidation:
    valid: bool
    reason: str = ""
    git_apply_stderr: str = ""


def validate_patch(patch: str, workdir: Path) -> PatchValidation:
    """Run `git apply --check` to confirm the patch applies cleanly.

    The agent uses this BEFORE declaring FINAL. A failing check
    triggers a revision pass with the git_apply_stderr fed back as
    the critique.
    """
    if not patch or not patch.strip():
        return PatchValidation(valid=False, reason="empty patch")
    if "--- a/" not in patch or "+++ b/" not in patch:
        return PatchValidation(
            valid=False,
            reason="patch is missing `--- a/...` / `+++ b/...` headers",
        )
    if not (workdir / ".git").exists():
        return PatchValidation(
            valid=False,
            reason="workdir is not a git repository; cannot validate",
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), "apply", "--check", "-"],
            input=patch.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return PatchValidation(
            valid=False,
            reason="git apply --check timed out",
        )
    if proc.returncode == 0:
        return PatchValidation(valid=True)
    return PatchValidation(
        valid=False,
        reason="git apply --check rejected the patch",
        git_apply_stderr=proc.stderr.decode("utf-8", errors="replace")[:2000],
    )


@dataclass
class TestRunResult:
    fail_to_pass_passing: int = 0
    fail_to_pass_total: int = 0
    pass_to_pass_passing: int = 0
    pass_to_pass_total: int = 0
    error: str = ""
    raw_output: str = ""

    @property
    def all_pass(self) -> bool:
        return (
            self.fail_to_pass_passing == self.fail_to_pass_total
            and self.pass_to_pass_passing == self.pass_to_pass_total
            and not self.error
        )

    @property
    def score(self) -> float:
        """Combined score: did we fix the failing tests AND not break passing ones?

        Returns in [0, 1]. 1.0 = perfect resolution.
        """
        if self.error:
            return 0.0
        total = self.fail_to_pass_total + self.pass_to_pass_total
        if total == 0:
            return 0.0
        passing = self.fail_to_pass_passing + self.pass_to_pass_passing
        return passing / total

    def summary(self) -> str:
        if self.error:
            return f"test runner error: {self.error}"
        return (
            f"FAIL_TO_PASS: {self.fail_to_pass_passing}/{self.fail_to_pass_total} pass; "
            f"PASS_TO_PASS: {self.pass_to_pass_passing}/{self.pass_to_pass_total} pass"
        )


def run_failing_tests(
    workdir: Path,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
    sandbox,
    *,
    timeout: float = 600.0,
) -> TestRunResult:
    """Apply the staged patch + run the SWE-bench tests.

    SWE-bench instances ship with two test sets:
      - FAIL_TO_PASS: tests that fail on HEAD; must pass after fix
      - PASS_TO_PASS: tests that pass on HEAD; must still pass

    Both lists are pytest node IDs. We invoke pytest via the sandbox
    so the run is isolated.

    `sandbox` is any object exposing `.exec(cmd) -> ExecResult`
    (LocalBackend / DockerBackend / FirecrackerBackend).
    """
    if not fail_to_pass and not pass_to_pass:
        return TestRunResult(error="no FAIL_TO_PASS or PASS_TO_PASS tests provided")

    result = TestRunResult(
        fail_to_pass_total=len(fail_to_pass),
        pass_to_pass_total=len(pass_to_pass),
    )

    def _run(test_ids: list[str]) -> tuple[int, int, str]:
        if not test_ids:
            return 0, 0, ""
        # Quote test IDs so pytest sees them as a single arg per id.
        cmd = "pytest -x --tb=short " + " ".join(f"'{t}'" for t in test_ids)
        try:
            r = sandbox.exec(cmd)
        except Exception as e:  # pragma: no cover
            return 0, len(test_ids), f"sandbox exec failed: {e}"
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        # Pytest summary line: "1 failed, 3 passed in 0.1s" etc.
        m_pass = re.search(r"(\d+)\s+passed", out)
        m_fail = re.search(r"(\d+)\s+failed", out)
        m_err = re.search(r"(\d+)\s+error", out)
        passed = int(m_pass.group(1)) if m_pass else 0
        failed = int(m_fail.group(1)) if m_fail else 0
        errored = int(m_err.group(1)) if m_err else 0
        # If neither matched, treat as one big failure (the run crashed).
        if not (m_pass or m_fail or m_err):
            return 0, len(test_ids), out[:1000]
        return passed, failed + errored, out[:1000]

    f_pass, f_fail, f_out = _run(fail_to_pass)
    result.fail_to_pass_passing = f_pass
    p_pass, p_fail, p_out = _run(pass_to_pass)
    result.pass_to_pass_passing = p_pass
    result.raw_output = (f_out + "\n" + p_out)[-2000:]
    return result


@dataclass
class CodingModeConfig:
    """Settings for benchmark / coding tasks."""
    enabled: bool = False
    best_of_n: int = 1
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    require_apply_check: bool = True


def from_env() -> CodingModeConfig:
    """Read coding-mode config from env (set by the SWE-bench harness)."""
    import os
    cfg = CodingModeConfig()
    cfg.enabled = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true", "yes")
    try:
        cfg.best_of_n = int(os.environ.get("MAVERICK_BEST_OF_N", "1"))
    except ValueError:
        cfg.best_of_n = 1
    cfg.fail_to_pass = [
        t for t in os.environ.get("MAVERICK_FAIL_TO_PASS", "").split("||") if t
    ]
    cfg.pass_to_pass = [
        t for t in os.environ.get("MAVERICK_PASS_TO_PASS", "").split("||") if t
    ]
    return cfg


@dataclass
class Candidate:
    """One of N candidate patches considered during best-of-N selection."""
    index: int
    patch: str
    score: float
    apply_check_passed: bool
    test_result: Optional["TestRunResult"] = None
    error: str = ""


def select_best_candidate(candidates: list[Candidate]) -> Optional[Candidate]:
    """Pick the candidate with the highest test score; tiebreak on
    apply-check + smaller patch (Occam).

    Used at the end of a best-of-N orchestrator run. Returns None if
    no candidate is usable.
    """
    if not candidates:
        return None
    usable = [c for c in candidates if c.apply_check_passed and not c.error]
    if not usable:
        # Fall back to whatever applies.
        usable = [c for c in candidates if c.apply_check_passed]
    if not usable:
        # Last resort: anything non-empty.
        usable = [c for c in candidates if c.patch.strip()]
    if not usable:
        return None
    # Higher score first; smaller patch wins ties.
    usable.sort(key=lambda c: (-c.score, len(c.patch)))
    return usable[0]


async def evaluate_candidate(
    patch: str,
    workdir: Path,
    cfg: CodingModeConfig,
    sandbox,
    index: int,
) -> Candidate:
    """Validate + score one candidate. Used by best-of-N pickers."""
    cand = Candidate(index=index, patch=patch, score=0.0,
                     apply_check_passed=False)
    if not patch or not patch.strip():
        cand.error = "empty patch"
        return cand

    validation = validate_patch(patch, workdir)
    cand.apply_check_passed = validation.valid
    if not validation.valid:
        cand.error = validation.reason
        return cand

    if cfg.fail_to_pass or cfg.pass_to_pass:
        # Apply patch + run tests. We use a copy of workdir to avoid
        # polluting the original between candidates.
        import subprocess as _subprocess
        try:
            _subprocess.run(
                ["git", "-C", str(workdir), "stash", "--include-untracked"],
                capture_output=True, timeout=20,
            )
            _subprocess.run(
                ["git", "-C", str(workdir), "apply", "-"],
                input=patch.encode("utf-8"),
                capture_output=True, timeout=30,
            )
            test_result = run_failing_tests(
                workdir, cfg.fail_to_pass, cfg.pass_to_pass, sandbox,
            )
            cand.test_result = test_result
            cand.score = test_result.score
        finally:
            _subprocess.run(
                ["git", "-C", str(workdir), "reset", "--hard", "HEAD"],
                capture_output=True, timeout=20,
            )
            _subprocess.run(
                ["git", "-C", str(workdir), "stash", "pop"],
                capture_output=True, timeout=20,
            )
    else:
        # No ground-truth tests; score by apply-check + patch size as
        # a proxy (smaller diffs preferred when tests can't decide).
        cand.score = 0.5
    return cand
