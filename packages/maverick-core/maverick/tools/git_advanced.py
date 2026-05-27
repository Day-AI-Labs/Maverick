"""Git advanced ops tool.

Surfaces high-leverage git verbs the agent commonly fumbles when
using the raw shell tool: bisect, rebase --onto, cherry-pick,
worktree. Structured args + sandbox-mediated execution.

Each op is a typed verb. The tool returns a short result summary
plus the relevant output; on failure, the full stderr is included.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_GIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": [
                "bisect_start", "bisect_good", "bisect_bad",
                "bisect_skip", "bisect_reset",
                "rebase_onto",
                "cherry_pick",
                "worktree_add", "worktree_remove", "worktree_list",
                "log_oneline", "blame_line", "show_commit",
            ],
            "description": "git operation.",
        },
        "ref": {"type": "string", "description": "git ref (sha, branch, tag)."},
        "upstream": {"type": "string", "description": "Upstream ref (rebase_onto)."},
        "onto": {"type": "string", "description": "New base (rebase_onto)."},
        "branch": {"type": "string", "description": "Branch name (rebase_onto, worktree_add)."},
        "commit": {"type": "string", "description": "Commit sha (cherry_pick, show_commit, blame_line)."},
        "path": {"type": "string", "description": "Worktree path (worktree_add/remove) or file path (blame_line)."},
        "line": {"type": "integer", "description": "Line number (blame_line)."},
        "limit": {"type": "integer", "description": "Log entry cap (log_oneline)."},
        "since_ref": {"type": "string", "description": "Range start ref (log_oneline)."},
    },
    "required": ["op"],
}


def _run_git(workdir: Path, args: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    cmd = ["git", "-C", str(workdir), *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            env={**os.environ, "GIT_PAGER": ""},
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {shlex.join(cmd)}"
    except OSError as e:
        return 127, "", f"cannot run git: {e}"
    return (
        proc.returncode,
        (proc.stdout or b"").decode("utf-8", errors="replace"),
        (proc.stderr or b"").decode("utf-8", errors="replace"),
    )


def _shape(code: int, out: str, err: str, *, label: str) -> str:
    if code == 0:
        return f"[{label}] OK\n{out}".rstrip() if out else f"[{label}] OK"
    return f"[{label}] FAILED (exit {code})\n{err}".rstrip() if err else f"[{label}] FAILED (exit {code})"


def _make_run(sandbox):
    def _run(args: dict[str, Any]) -> str:
        op = args.get("op")
        if not op:
            return "ERROR: op is required"
        workdir = Path(getattr(sandbox, "workdir", ".")).resolve()
        if not workdir.is_dir():
            return f"ERROR: workdir {workdir} not found"
        if not (workdir / ".git").exists():
            # git worktree etc still works with --git-dir, but bisect /
            # rebase require an actual repo.
            return "ERROR: not a git repo at sandbox workdir"

        if op == "bisect_start":
            return _shape(*_run_git(workdir, ["bisect", "start"]), label="bisect start")
        if op == "bisect_good":
            ref = (args.get("ref") or "HEAD").strip()
            return _shape(*_run_git(workdir, ["bisect", "good", ref]), label=f"bisect good {ref}")
        if op == "bisect_bad":
            ref = (args.get("ref") or "HEAD").strip()
            return _shape(*_run_git(workdir, ["bisect", "bad", ref]), label=f"bisect bad {ref}")
        if op == "bisect_skip":
            ref = (args.get("ref") or "HEAD").strip()
            return _shape(*_run_git(workdir, ["bisect", "skip", ref]), label="bisect skip")
        if op == "bisect_reset":
            return _shape(*_run_git(workdir, ["bisect", "reset"]), label="bisect reset")

        if op == "rebase_onto":
            onto = (args.get("onto") or "").strip()
            upstream = (args.get("upstream") or "").strip()
            branch = (args.get("branch") or "").strip()
            if not onto or not upstream:
                return "ERROR: rebase_onto requires onto and upstream"
            git_args = ["rebase", "--onto", onto, upstream]
            if branch:
                git_args.append(branch)
            return _shape(*_run_git(workdir, git_args), label="rebase --onto")

        if op == "cherry_pick":
            commit = (args.get("commit") or "").strip()
            if not commit:
                return "ERROR: cherry_pick requires commit"
            return _shape(*_run_git(workdir, ["cherry-pick", commit]), label=f"cherry-pick {commit}")

        if op == "worktree_add":
            path = (args.get("path") or "").strip()
            branch = (args.get("branch") or "").strip()
            if not path:
                return "ERROR: worktree_add requires path"
            git_args = ["worktree", "add", path]
            if branch:
                git_args.append(branch)
            return _shape(*_run_git(workdir, git_args), label="worktree add")
        if op == "worktree_remove":
            path = (args.get("path") or "").strip()
            if not path:
                return "ERROR: worktree_remove requires path"
            return _shape(*_run_git(workdir, ["worktree", "remove", path]), label="worktree remove")
        if op == "worktree_list":
            return _shape(*_run_git(workdir, ["worktree", "list"]), label="worktree list")

        if op == "log_oneline":
            limit = max(1, min(int(args.get("limit") or 30), 500))
            since = (args.get("since_ref") or "").strip()
            git_args = ["log", "--oneline", f"-n{limit}"]
            if since:
                git_args.append(f"{since}..HEAD")
            return _shape(*_run_git(workdir, git_args), label="log")
        if op == "show_commit":
            commit = (args.get("commit") or "HEAD").strip()
            return _shape(*_run_git(workdir, ["show", "--stat", commit]), label=f"show {commit}")
        if op == "blame_line":
            path = (args.get("path") or "").strip()
            line = args.get("line")
            if not path or line is None:
                return "ERROR: blame_line requires path and line"
            line = int(line)
            return _shape(
                *_run_git(workdir, ["blame", "-L", f"{line},{line}", path]),
                label=f"blame {path}:{line}",
            )

        return f"ERROR: unknown op {op!r}"

    return _run


def git_advanced(sandbox) -> Tool:
    return Tool(
        name="git_advanced",
        description=(
            "Structured wrappers around git verbs the agent commonly "
            "fumbles in raw shell. ops: bisect_start/good/bad/skip/reset, "
            "rebase_onto, cherry_pick, worktree_add/remove/list, "
            "log_oneline, show_commit, blame_line. Sandbox-mediated."
        ),
        input_schema=_GIT_SCHEMA,
        fn=_make_run(sandbox),
    )
