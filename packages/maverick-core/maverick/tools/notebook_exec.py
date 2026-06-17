"""Jupyter notebook execution tool: run a .ipynb's code cells, capture output.

Extracts the code cells from a notebook (stdlib ``json``), concatenates them into
one script, and runs it through the sandbox chokepoint (``sandbox_run`` →
``python -``) so execution is confined and the backend is swappable in tests.
No Jupyter kernel required — this runs the notebook's *code* the way the agent
runs any other script. Cell magics (``%``/``!`` lines) are stripped since they're
kernel-only. ``_extract_code`` is the pure, unit-tested core.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import Tool, sandbox_run


def _safe_path(sandbox, user_path: str) -> Path:
    """Resolve ``user_path`` confined to the sandbox workspace.

    Without a sandbox there's no workspace to confine to, so fall back to
    ``expanduser`` (matches pandas_query). With a sandbox wired in, resolve
    under ``sandbox.workdir`` and refuse anything that escapes it -- a
    model-supplied ``~/secret.ipynb`` must not execute outside the workspace.
    """
    if sandbox is None:
        return Path(os.path.expanduser(user_path))
    workdir = Path(sandbox.workdir).resolve()
    candidate = Path(user_path)
    candidate = (workdir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    candidate.relative_to(workdir)  # raises ValueError if it escapes
    return candidate

_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "path to a .ipynb notebook"},
        "timeout": {"type": "integer", "description": "seconds (default 120)"},
    },
    "required": ["path"],
}


def _extract_code(nb: dict) -> str:
    """Concatenate code-cell source from a parsed notebook, dropping magics."""
    cells = nb.get("cells") or []
    chunks: list[str] = []
    for i, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source") or []
        if isinstance(src, list):
            src = "".join(src)
        lines = [ln for ln in str(src).splitlines()
                 if not ln.lstrip().startswith(("%", "!"))]
        body = "\n".join(lines).strip()
        if body:
            chunks.append(f"# --- cell {i} ---\n{body}")
    return "\n\n".join(chunks)


def _run(args: dict[str, Any], sandbox) -> str:
    path = str(args.get("path") or "").strip()
    if not path:
        return "ERROR: path is required"
    try:
        p = _safe_path(sandbox, path)
    except ValueError:
        return f"ERROR: path escapes the workspace: {path!r}"
    try:
        if not p.exists():
            return f"ERROR: no such notebook {path!r}"
        nb = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return f"ERROR: cannot read notebook: {e}"
    code = _extract_code(nb)
    if not code:
        return "(notebook has no executable code cells)"
    try:
        timeout = float(args.get("timeout") or 120)
    except (TypeError, ValueError):
        timeout = 120.0
    code, stdout, stderr = sandbox_run(
        sandbox, ["python", "-"], stdin=code, timeout=timeout)
    parts = [f"exit_code: {code}"]
    if stdout.strip():
        parts.append("stdout:\n" + stdout.rstrip())
    if stderr.strip():
        parts.append("stderr:\n" + stderr.rstrip())
    return "\n".join(parts)


def notebook_exec(sandbox) -> Tool:
    return Tool(
        name="notebook_exec",
        description=(
            "Execute a Jupyter notebook's code cells and capture stdout/stderr. "
            "Concatenates code cells (drops %/! magics) and runs them through the "
            "sandbox — no kernel needed. Input: path to a .ipynb."
        ),
        input_schema=_SCHEMA,
        fn=lambda args: _run(args, sandbox),
    )


__all__ = ["notebook_exec", "_extract_code"]
