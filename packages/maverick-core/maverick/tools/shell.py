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
]


def _is_blocked_in_opaque(cmd: str) -> tuple[bool, str]:
    for pat in _GIT_GOLD_LEAK_PATTERNS:
        m = pat.search(cmd)
        if m:
            return True, m.group(0)
    return False, ""


def shell(sandbox) -> Tool:
    def fn(args: dict) -> str:
        cmd = args["cmd"]
        # Wave 10 (S2): opaque-mode gold-leak guard.
        opaque = os.environ.get("MAVERICK_BENCHMARK_OPAQUE", "1") != "0"
        coding = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true", "yes")
        if opaque and coding:
            blocked, fragment = _is_blocked_in_opaque(cmd)
            if blocked:
                return (
                    f"ERROR: shell command blocked in benchmark opaque "
                    f"mode (matched {fragment!r}). "
                    "git log -p / git show / git blame / git diff with refs / "
                    "git reflog / git stash list can leak the gold patch; "
                    "derive your fix from the bug description and the code, "
                    "not from inspecting the answer in git history. "
                    "(Override by setting MAVERICK_BENCHMARK_OPAQUE=0.)"
                )
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
