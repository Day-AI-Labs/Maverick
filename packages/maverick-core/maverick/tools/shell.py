"""Shell tool. Sandbox-mediated."""
from __future__ import annotations

import os
import re

from . import Tool


# Wave 10 (S2): in benchmark opaque mode, refuse git subcommands that
# can leak the gold patch (the SWE-bench evaluator pre-applies the
# bug commit to HEAD; the fix is reachable via `git log -p`, `git
# show <commit>`, `git diff HEAD..main`, etc.). The list is the
# minimum-surprise blocklist — generic `git` (status, diff, apply,
# add, commit, reset) stays available so the agent can still work.
_GIT_GOLD_LEAK_PATTERNS = [
    re.compile(r"\bgit\s+log\b.*?(?:-p|--patch|--all|--reflog)\b"),
    re.compile(r"\bgit\s+show\b"),
    re.compile(r"\bgit\s+blame\b"),
    # `git diff` is fine for HEAD-vs-worktree (the normal case);
    # block only when it's pointed at another ref.
    re.compile(r"\bgit\s+diff\s+\S+\.\."),
    # `git stash list` / `git stash show` could surface a leftover
    # gold stash from the harness setup.
    re.compile(r"\bgit\s+stash\s+(?:list|show)\b"),
    # Reflog can also reveal pre-bug state.
    re.compile(r"\bgit\s+reflog\b"),
    # Wave 12 (council F9d): direct object/ref enumeration. The
    # harness's setup leaves the gold reachable via these plumbing
    # commands even when porcelain (log/show/diff) is blocked.
    re.compile(r"\bgit\s+cat-file\b"),
    re.compile(r"\bgit\s+for-each-ref\b"),
    re.compile(r"\bgit\s+rev-parse\b.*\b(?:HEAD\^|HEAD~|main|master|origin)"),
    re.compile(r"\bgit\s+ls-tree\b"),
    # `cat .git/refs/...` / `head .git/HEAD` / `find .git` — raw
    # filesystem access to git internals. The fs.py read_file
    # blocks .git/ via the tool, but shell.cat is a separate channel.
    re.compile(r"\b(?:cat|head|tail|less|more|strings|hexdump|od)\b[^|;&]*?\.git/"),
    re.compile(r"\bfind\s+\.git\b"),
    re.compile(r"\bls\s+[^|;&]*?\.git/(?:refs|objects|packed-refs|HEAD)\b"),
]


# Wave 11: block external network egress in opaque benchmark mode.
# The agent can `curl` / `wget` the upstream fix PR off github.com,
# read it, then transcribe — fully bypassing our shell-level git
# blocks. This is the most common cheating vector documented in the
# SWE-bench-Pro post-mortems (Princeton issue #465, Scale's cheating
# detection blog 2025-11-19). LocalBackend has no `--network=none`
# equivalent so we have to gate it here at the tool layer.
_NETWORK_LEAK_PATTERNS = [
    re.compile(
        r"\b(?:curl|wget|http(?:ie)?|aria2c|fetch)\b.*?"
        r"\b(?:github\.com|githubusercontent\.com|gist\.github\.com|"
        r"raw\.githubusercontent|api\.github\.com|patch-diff)\b",
        re.IGNORECASE,
    ),
    # `pip install <pkg>@git+...` and `git clone https://github.com/...`
    # would also fetch upstream — block them too in opaque mode.
    re.compile(r"\bgit\s+clone\s+\S*github\.com\S*", re.IGNORECASE),
    re.compile(r"\bpip\s+install\s+\S*git\+\S*github\S*", re.IGNORECASE),
    # Python one-liner fetch
    re.compile(
        r"\b(?:python|python3)\s+-c\s+[\"'].*?(?:urllib|requests|httpx).*?"
        r"github\.com",
        re.IGNORECASE | re.DOTALL,
    ),
]


# Wave 11: block `pip install -e .` in opaque mode when running inside
# a worktree (the Karpathy bet). Editable installs from inside a
# git-worktree create .pth/.egg-link entries that may point at the
# ORIGINAL tree or fail to point anywhere useful; tests then import
# unpatched code from the original. We surface the right pattern
# instead of letting the agent burn cycles on a silent failure.
_EDITABLE_INSTALL_PATTERN = re.compile(
    r"\bpip\s+install\s+(?:[^|;&]*\s+)?-e\b",
    re.IGNORECASE,
)


# Wave 11: detect pytest / npm test / go test / cargo test invocations
# so we can raise the per-call timeout from the LocalBackend default
# of 60 s (way too short for real SWE-bench test suites — Django can
# take 5-10 min).
_LONG_RUN_TEST_PATTERNS = [
    re.compile(r"\b(?:python\s+-m\s+)?pytest\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:test|run\s+test)\b", re.IGNORECASE),
    re.compile(r"\bnpx\s+(?:jest|vitest|mocha)\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(?:test|jest|vitest)\b", re.IGNORECASE),
    re.compile(r"\bgo\s+test\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+test\b", re.IGNORECASE),
    re.compile(r"\bbundle\s+exec\s+rspec\b", re.IGNORECASE),
    re.compile(r"\bmvn\s+(?:test|verify)\b", re.IGNORECASE),
    re.compile(r"\b\./gradlew\s+test\b", re.IGNORECASE),
    re.compile(r"\btox\b", re.IGNORECASE),
    # Heavy build/install commands also need longer timeouts.
    re.compile(r"\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:i|install|ci)\b", re.IGNORECASE),
]


def _is_blocked_in_opaque(cmd: str) -> tuple[bool, str]:
    for pat in _GIT_GOLD_LEAK_PATTERNS:
        m = pat.search(cmd)
        if m:
            return True, m.group(0)
    for pat in _NETWORK_LEAK_PATTERNS:
        m = pat.search(cmd)
        if m:
            return True, m.group(0)
    return False, ""


def _is_long_running(cmd: str) -> bool:
    return any(p.search(cmd) for p in _LONG_RUN_TEST_PATTERNS)


def shell(sandbox) -> Tool:
    def fn(args: dict) -> str:
        cmd = args["cmd"]
        opaque = os.environ.get("MAVERICK_BENCHMARK_OPAQUE", "1") != "0"
        coding = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true", "yes")
        # Wave 12 (council F9c): defensively pop MAVERICK_GOLD_PATCH
        # (and cache) before ANY subprocess inherits the env. This
        # guards the window between agent.run() start and the first
        # defensive_validate() call. Idempotent: a no-op once popped.
        if opaque:
            try:
                from ..coding_mode import get_gold_patch as _gp
                _gp()
            except Exception:
                pass
        if opaque and coding:
            blocked, fragment = _is_blocked_in_opaque(cmd)
            if blocked:
                return (
                    f"ERROR: shell command blocked in benchmark opaque "
                    f"mode (matched {fragment!r}). "
                    "git log -p / git show / git blame / git diff with refs / "
                    "git reflog / git stash list / curl|wget to github.com "
                    "can leak the gold patch; derive your fix from the bug "
                    "description and the code, not from inspecting the answer "
                    "in git history or fetching the upstream PR. "
                    "(Override by setting MAVERICK_BENCHMARK_OPAQUE=0.)"
                )
            if _EDITABLE_INSTALL_PATTERN.search(cmd):
                # Don't outright refuse -- the agent may legitimately need
                # an editable install -- but flag the worktree gotcha so
                # the model is told to install against the correct path.
                return (
                    "ERROR: `pip install -e` is blocked in benchmark opaque "
                    "mode. Editable installs from inside a git worktree "
                    "create .pth/.egg-link entries that may import unpatched "
                    "code from the original tree, silently failing tests "
                    "even when your patch is correct. If you need to install "
                    "the package, use `pip install .` (non-editable) or set "
                    "PYTHONPATH to include the worktree explicitly. "
                    "(Override by setting MAVERICK_BENCHMARK_OPAQUE=0.)"
                )
        # Wave 11 (D5 follow-up): the shell tool used to always fall back to
        # `sandbox.timeout` (60 s on LocalBackend) which kills pytest runs
        # on real SWE-bench repos. Detect long-running commands and pass
        # a higher per-call timeout. Falls back gracefully when sandbox
        # backends don't accept the kwarg.
        timeout_override = None
        if _is_long_running(cmd):
            try:
                timeout_override = float(
                    os.environ.get("MAVERICK_LONG_CMD_TIMEOUT", "600")
                )
            except ValueError:
                timeout_override = 600.0
        try:
            if timeout_override is not None:
                result = sandbox.exec(cmd, timeout=timeout_override)
            else:
                result = sandbox.exec(cmd)
        except TypeError:
            # Sandbox backend doesn't support per-call timeout kwarg yet.
            result = sandbox.exec(cmd)
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        out += f"\n[exit {result.exit_code}]"
        return out

    return Tool(
        name="shell",
        description="Run a shell command in the sandbox. Use for builds, tests, scripts, etc.",
        input_schema={
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
        fn=fn,
    )
