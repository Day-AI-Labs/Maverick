"""Pandoc tool — document format conversion.

Auth: none. Requires the ``pandoc`` binary on PATH.

ops:
  - convert(input_path, output_path, from_, to, args)
  - formats()                                    — input/output formats list
  - markdown_to_html(text)                       — string in/out
  - html_to_markdown(text)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_PANDOC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["convert", "formats", "markdown_to_html",
                     "html_to_markdown"],
        },
        "input_path": {"type": "string"},
        "output_path": {"type": "string"},
        "from_": {"type": "string"},
        "to": {"type": "string"},
        "text": {"type": "string"},
        "args": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["op"],
}


def _need_pandoc() -> str | None:
    if shutil.which("pandoc"):
        return None
    return "ERROR: pandoc not on PATH. Install pandoc."


def _safe_path(sandbox, user_path: str) -> str:
    if sandbox is None:
        return user_path
    workdir = Path(sandbox.workdir).resolve()
    candidate = (workdir / user_path).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as e:
        raise ValueError(f"path {user_path!r} escapes the workspace") from e
    return str(candidate)


def _op_convert(args: dict, sandbox) -> str:
    err = _need_pandoc()
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    dst = (args.get("output_path") or "").strip()
    if not src or not dst:
        return "ERROR: convert requires input_path and output_path"
    try:
        src = _safe_path(sandbox, src)
        dst = _safe_path(sandbox, dst)
    except ValueError as e:
        return f"ERROR: {e}"
    cmd = ["pandoc", src, "-o", dst]
    if args.get("from_"):
        cmd.extend(["-f", str(args["from_"])])
    if args.get("to"):
        cmd.extend(["-t", str(args["to"])])
    cmd.extend(str(a) for a in (args.get("args") or []))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return f"ERROR: pandoc ({r.returncode}): {r.stderr.strip()[-300:]}"
    return f"wrote {dst}"


def _op_formats(_args: dict) -> str:
    err = _need_pandoc()
    if err:
        return err
    in_ = subprocess.run(
        ["pandoc", "--list-input-formats"], capture_output=True, text=True,
    )
    out = subprocess.run(
        ["pandoc", "--list-output-formats"], capture_output=True, text=True,
    )
    return (
        f"input formats:\n{in_.stdout.strip()}\n\n"
        f"output formats:\n{out.stdout.strip()}"
    )


def _string_convert(text: str, from_: str, to: str) -> str:
    err = _need_pandoc()
    if err:
        return err
    if not text.strip():
        return "ERROR: text is required"
    r = subprocess.run(
        ["pandoc", "-f", from_, "-t", to],
        input=text, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return f"ERROR: pandoc ({r.returncode}): {r.stderr.strip()[-300:]}"
    return r.stdout


def _run(args: dict[str, Any], sandbox) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        if op == "convert":
            return _op_convert(args, sandbox)
        if op == "formats":
            return _op_formats(args)
        if op == "markdown_to_html":
            return _string_convert(args.get("text") or "", "markdown", "html")
        if op == "html_to_markdown":
            return _string_convert(args.get("text") or "", "html", "markdown")
    except Exception as e:
        return f"ERROR: pandoc failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def pandoc_tool(sandbox=None) -> Tool:
    return Tool(
        name="pandoc",
        description=(
            "Pandoc document conversion. ops: convert (file in/out + "
            "optional from/to/args), formats (list), markdown_to_html "
            "(string), html_to_markdown (string). Requires pandoc on "
            "PATH."
        ),
        input_schema=_PANDOC_SCHEMA,
        fn=lambda args: _run(args, sandbox),
    )
