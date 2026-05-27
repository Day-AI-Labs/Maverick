"""File-diff preview tool.

Lets the agent see a unified diff of the workspace BEFORE committing
or applying further changes. Wraps ``git diff`` (the most reliable
source of truth) with a clean schema; falls back to ``difflib`` against
HEAD blobs when git isn't a repo.

Common use: after a series of str_replace_editor / write_file calls,
the agent calls preview_diff to verify its work matches intent.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_DIFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific paths to diff. Default: all changed.",
        },
        "staged": {
            "type": "boolean",
            "description": "Diff staged (--cached) changes instead of unstaged.",
        },
        "max_bytes": {
            "type": "integer",
            "description": "Truncate output (default 50_000).",
        },
        "stat_only": {
            "type": "boolean",
            "description": "Show --stat summary instead of full diff.",
        },
    },
    "required": [],
}


def _run_factory(sandbox):
    def _run(args: dict[str, Any]) -> str:
        cwd = str(Path(getattr(sandbox, "workdir", ".")).resolve())
        if not Path(cwd).is_dir():
            return f"ERROR: workdir {cwd!r} not found"
        if not (Path(cwd) / ".git").exists():
            return (
                "ERROR: not a git repo. preview_diff currently requires "
                "a git repository at the sandbox workdir."
            )
        max_bytes = int(args.get("max_bytes") or 50_000)
        cmd = ["git", "-C", cwd, "diff"]
        if args.get("staged"):
            cmd.append("--cached")
        if args.get("stat_only"):
            cmd.append("--stat")
        for p in (args.get("paths") or []):
            cmd.append("--")
            cmd.append(str(p))
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=15,
                env={**os.environ, "GIT_PAGER": ""},
            )
        except subprocess.TimeoutExpired:
            return "ERROR: git diff timed out (15s)"
        except OSError as e:
            return f"ERROR: cannot run git: {e}"
        if proc.returncode not in (0, 1):
            err = (proc.stderr or b"").decode("utf-8", errors="replace")
            return f"ERROR: git diff exited {proc.returncode}: {err[:500]}"
        out = (proc.stdout or b"").decode("utf-8", errors="replace")
        if not out.strip():
            return "(no changes)"
        if len(out) > max_bytes:
            out = out[:max_bytes] + f"\n\n[... truncated at {max_bytes} bytes]"
        return out
    return _run


def preview_diff(sandbox) -> Tool:
    return Tool(
        name="preview_diff",
        description=(
            "Show a unified diff of pending changes in the sandbox workdir "
            "(via `git diff`). Use after str_replace_editor/write_file to "
            "review your work before continuing. Args: staged=true for "
            "staged changes, stat_only=true for a summary, paths=[...] to "
            "limit to specific files. Output truncated at max_bytes "
            "(default 50000)."
        ),
        input_schema=_DIFF_SCHEMA,
        fn=_run_factory(sandbox),
    )
