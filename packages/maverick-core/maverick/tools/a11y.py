"""Accessibility (a11y) check tool.

Runs ``pa11y`` (preferred) or ``axe-core`` via local CLI against a
URL or HTML file and returns a deduplicated, ranked list of
violations the agent can use to file issues or fix problems.

Why CLIs and not a Python lib? The maintained a11y rule sets all
live in the JS ecosystem (axe-core, pa11y). Shelling out keeps us
out of the rule-update business.

ops:
  - check(url, runner)             — runner = pa11y | axe (default: pa11y)
  - check_html(path, runner)       — local .html file

Both require the corresponding binary on PATH:
  - pa11y:  ``npm install -g pa11y``
  - axe:    ``npm install -g @axe-core/cli``

Failures are loud (we surface the missing binary + install command).
"""
from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_A11Y_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["check", "check_html"]},
        "url": {"type": "string"},
        "path": {"type": "string"},
        "runner": {"type": "string", "enum": ["pa11y", "axe"]},
        "max_issues": {"type": "integer"},
    },
    "required": ["op"],
}


def _bin(runner: str) -> str:
    return {"pa11y": "pa11y", "axe": "axe"}.get(runner, "pa11y")


def _ensure_runner(runner: str) -> str | None:
    b = _bin(runner)
    if shutil.which(b):
        return None
    install = (
        "npm install -g pa11y" if runner == "pa11y"
        else "npm install -g @axe-core/cli"
    )
    return f"ERROR: {b} not found on PATH. Install with: {install}"


def _confine_path(sandbox, user_path: str) -> str:
    """Confine a check_html file path to the sandbox workspace and block
    option-injection (a leading '-' would be parsed as a runner flag).
    Mirrors the media tools' _safe_path."""
    if user_path.startswith("-"):
        raise ValueError(f"path {user_path!r} may not begin with '-'")
    if sandbox is None:
        return user_path
    from pathlib import Path
    workdir = Path(sandbox.workdir).resolve()
    candidate = (workdir / user_path).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as e:
        raise ValueError(f"path {user_path!r} escapes the workspace") from e
    return str(candidate)


def _run_pa11y(target: str, sandbox) -> tuple[int, str, str]:
    from . import sandbox_run
    # `--` ends option parsing so a target beginning with `-` is treated
    # as a path, not an injected pa11y flag (e.g. --config=/tmp/evil.js).
    code, out, err = sandbox_run(
        sandbox, ["pa11y", "--reporter", "json", "--", target], timeout=120,
    )
    if code == 124:
        return 124, "", "pa11y TIMEOUT"
    return code, out or "", err or ""


def _run_axe(target: str, sandbox) -> tuple[int, str, str]:
    from . import sandbox_run
    # `--` ends option parsing so a target beginning with `-` is treated as a
    # URL/path, not an injected axe flag (parity with the pa11y path). Options
    # precede `--`; the target is the sole positional after it.
    code, out, err = sandbox_run(
        sandbox,
        ["axe", "--no-reporter", "--save", "/dev/stdout", "--", target],
        timeout=120,
    )
    if code == 124:
        return 124, "", "axe TIMEOUT"
    return code, out or "", err or ""


def _format_pa11y(stdout: str, max_issues: int) -> str:
    try:
        items = json.loads(stdout)
    except json.JSONDecodeError:
        return f"ERROR: pa11y returned non-JSON output:\n{stdout[:500]}"
    if not isinstance(items, list):
        return f"ERROR: pa11y returned unexpected shape: {type(items)}"
    if not items:
        return "no a11y issues"
    # Group by code so duplicate violations across many elements collapse.
    by_code: dict[str, list[dict]] = {}
    for it in items:
        by_code.setdefault(it.get("code", "?"), []).append(it)
    lines = [f"{len(items)} a11y issue(s) across {len(by_code)} rule(s):"]
    for code in sorted(by_code, key=lambda c: -len(by_code[c]))[:max_issues]:
        examples = by_code[code]
        first = examples[0]
        lines.append(
            f"  {code}  ×{len(examples)}  [{first.get('type', '?')}]\n"
            f"      {(first.get('message') or '')[:140]}\n"
            f"      selector: {(first.get('selector') or '')[:120]}"
        )
    return "\n".join(lines)


def _format_axe(stdout: str, max_issues: int) -> str:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return f"ERROR: axe returned non-JSON output:\n{stdout[:500]}"
    # axe outputs an array per page tested.
    if isinstance(data, list):
        data = data[0] if data else {}
    violations = (data.get("violations") if isinstance(data, dict) else None) or []
    if not violations:
        return "no a11y issues"
    lines = [f"{len(violations)} a11y violation(s):"]
    for v in violations[:max_issues]:
        nodes = v.get("nodes") or []
        lines.append(
            f"  {v.get('id', '?')}  ×{len(nodes)}  "
            f"[{v.get('impact', '?')}]\n"
            f"      {(v.get('description') or '')[:140]}"
        )
    return "\n".join(lines)


def _op_check(target: str, runner: str, max_issues: int, sandbox) -> str:
    err = _ensure_runner(runner)
    if err:
        return err
    if runner == "axe":
        code, out, err_out = _run_axe(target, sandbox)
        if code != 0 and not out:
            return f"ERROR: axe ({code}): {err_out.strip()[:300]}"
        return _format_axe(out, max_issues)
    code, out, err_out = _run_pa11y(target, sandbox)
    # pa11y returns 2 when issues are found AND has stdout — that's
    # expected, not an error.
    if code not in (0, 2) and not out:
        return f"ERROR: pa11y ({code}): {err_out.strip()[:300]}"
    return _format_pa11y(out, max_issues)


def _run(args: dict[str, Any], sandbox) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    runner = (args.get("runner") or "pa11y").strip().lower()
    if runner not in {"pa11y", "axe"}:
        runner = "pa11y"
    max_issues = max(1, min(int(args.get("max_issues") or 20), 100))
    try:
        if op == "check":
            url = (args.get("url") or "").strip()
            if not url:
                return "ERROR: check requires url"
            return _op_check(url, runner, max_issues, sandbox)
        if op == "check_html":
            path = (args.get("path") or "").strip()
            if not path:
                return "ERROR: check_html requires path"
            path = _confine_path(sandbox, path)
            return _op_check(path, runner, max_issues, sandbox)
    except Exception as e:
        return f"ERROR: a11y failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def a11y(sandbox=None) -> Tool:
    return Tool(
        name="a11y",
        description=(
            "Accessibility checker via pa11y or @axe-core/cli. "
            "ops: check (url), check_html (local file path). runner "
            "= pa11y (default) | axe. Requires the chosen binary on "
            "PATH (install via npm)."
        ),
        input_schema=_A11Y_SCHEMA,
        fn=lambda args: _run(args, sandbox),
    )
