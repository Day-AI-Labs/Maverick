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
    # Porcelain commands — most leak vectors. We accept that any of
    # these tokens after `git` (possibly with global flags like -P,
    # -C dir, --git-dir=path, -c k=v) defeats the simple `\bgit\s+log\b`
    # anchor, so we accept ANY non-newline char between `git` and the
    # subcommand. The `git\b` start anchor still rules out `gitlab` etc.
    re.compile(r"\bgit\s[^\n;&|]*?\blog\b.*?(?:-p|--patch|--all|--reflog)\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bshow\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bblame\b"),
    # `git diff` HEAD-vs-worktree is fine; block ref-vs-ref diffs.
    re.compile(r"\bgit\s[^\n;&|]*?\bdiff\s+\S+\.\."),
    re.compile(r"\bgit\s[^\n;&|]*?\bstash\s+(?:list|show)\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\breflog\b"),
    # Plumbing — Wave 12 hardening: full coverage including subcommands
    # that the original list missed (rev-list, show-ref, ls-files,
    # fsck, update-ref, symbolic-ref).
    re.compile(r"\bgit\s[^\n;&|]*?\bcat-file\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bfor-each-ref\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\brev-list\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bshow-ref\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bsymbolic-ref\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bls-tree\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bls-files\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bfsck\b"),
    re.compile(r"\bgit\s[^\n;&|]*?\bupdate-ref\b"),
    re.compile(
        r"\bgit\s[^\n;&|]*?\brev-parse\b.*\b"
        r"(?:HEAD\^|HEAD~|main|master|origin)"
    ),
    # `git --git-dir=PATH` redirects to a foreign .git — block any
    # use that names a path (Wave 12 hardening from agent 2's #3).
    re.compile(r"\bgit\s+--git-dir[=\s]+\S+"),
    # Any *consuming utility* against `.git/<sensitive>` paths.
    # Wave 12 hardening (agent 2's #2): the prior allowlist (cat/
    # head/tail/less/more/strings/hexdump/od) missed python/awk/xxd/
    # grep/sed/cp/mv/tar/rsync. Anchor on the .git/<file> token so
    # the rule fires regardless of who reads it.
    re.compile(
        r"\.git/(?:HEAD|ORIG_HEAD|FETCH_HEAD|MERGE_HEAD|packed-refs"
        r"|refs(?:/|\b)|objects(?:/|\b)|index\b)",
    ),
    re.compile(r"\bfind\s+\.git\b"),
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


# May 26 council fix (Princeton-perspective audit #1, smoke-batch
# pylint pip-rabbit-hole): the prompt's Rule 11 ("never run pip
# install") is aspirational. Enforce here. The grader uses a pristine
# Docker image with deps pre-installed; any `pip install` from the
# agent's shell pollutes the LOCAL sandbox (changing test outcomes
# for subsequent instances when the workdir is shared) but is a
# no-op for the grader. Block in opaque mode.
_PACKAGE_INSTALL_PATTERN = re.compile(
    r"\b(?:"
    r"pip\s+install"
    r"|pip3\s+install"
    r"|python\s+-m\s+pip\s+install"
    r"|python3\s+-m\s+pip\s+install"
    r"|conda\s+install"
    r"|npm\s+(?:install|i|ci|add)"
    r"|yarn\s+(?:add|install)"
    r"|apt(?:-get)?\s+install"
    r"|apk\s+add"
    r"|brew\s+install"
    r")\b",
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
            # May 26 council fix: block ALL package-install commands
            # in opaque mode. The grader's container has deps already;
            # any install here just pollutes the local sandbox for
            # downstream instances. Surface the right framing so the
            # agent treats ImportError as a code bug, not env issue.
            if _PACKAGE_INSTALL_PATTERN.search(cmd):
                return (
                    "ERROR: package install commands are blocked in "
                    "benchmark opaque mode. The grader's test container "
                    "has dependencies pre-installed at the pinned "
                    "versions for this instance. If you see ImportError "
                    "or ModuleNotFoundError, treat it as a CODE bug "
                    "(missing import in production code, wrong module "
                    "path) — not an environment problem. Do NOT try "
                    "`pip install` / `npm install` / `apt install`; "
                    "fix the code instead. "
                    "(Override: MAVERICK_BENCHMARK_OPAQUE=0.)"
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
        description=(
            "Run a shell command in the sandbox. Use for running "
            "tests, builds, greps, finding files, inspecting "
            "environment, running reproduction scripts.\n\n"
            "Each invocation starts a fresh shell — there's no "
            "persistent cwd, env, or shell variables between calls. "
            "Use absolute or workspace-relative paths; do NOT `cd` "
            "then expect the next call to be in that directory.\n\n"
            "Always pass non-interactive flags: `-y` / `-f` for "
            "package managers, `-q` to silence prompts. Interactive "
            "commands (vi, nano, less, more, `git rebase -i`) hang "
            "the sandbox. Use `cat`, `head -N`, `tail -N` for reading.\n\n"
            "Common patterns:\n"
            "  • `python -m pytest path::test -xvs` — single test, "
            "verbose, exit-on-fail, no capture\n"
            "  • `grep -rn 'pattern' src/` — recursive search, line "
            "numbers, file paths\n"
            "  • `git diff` — see what you're about to submit\n"
            "  • `python -c 'import pkg; print(pkg.__file__)'` — "
            "check which install Python loads\n\n"
            "In benchmark opaque mode, git-internals access is "
            "blocked: no `git log -p`, `git show <ref>`, `git cat-file`, "
            "`git for-each-ref`, `git rev-list`, or `cat .git/*`. The "
            "gold answer is reachable via those; we block them. Use "
            "`git diff` (working tree vs HEAD) and `git status` "
            "freely — those are safe."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": (
                        "Shell command to execute in the sandbox. "
                        "Single line preferred; chain with `&&` or "
                        "`;` for sequences."
                    ),
                },
            },
            "required": ["cmd"],
        },
        fn=fn,
    )
