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
    from . import safe_media_args, sandbox_run
    cmd.extend(safe_media_args(args.get("args")))
    code, _out, stderr = sandbox_run(sandbox, cmd, timeout=120)
    if code != 0:
        return f"ERROR: pandoc ({code}): {stderr.strip()[-300:]}"
    return f"wrote {dst}"


def _op_formats(_args: dict, sandbox) -> str:
    err = _need_pandoc()
    if err:
        return err
    from . import sandbox_run
    _ci, in_out, _ie = sandbox_run(sandbox, ["pandoc", "--list-input-formats"], timeout=30)
    _co, out_out, _oe = sandbox_run(sandbox, ["pandoc", "--list-output-formats"], timeout=30)
    return (
        f"input formats:\n{in_out.strip()}\n\n"
        f"output formats:\n{out_out.strip()}"
    )


def _string_convert(text: str, from_: str, to: str, sandbox) -> str:
    err = _need_pandoc()
    if err:
        return err
    if not text.strip():
        return "ERROR: text is required"
    from . import sandbox_run
    code, out, stderr = sandbox_run(
        sandbox, ["pandoc", "-f", from_, "-t", to], timeout=60, stdin=text,
    )
    if code != 0:
        return f"ERROR: pandoc ({code}): {stderr.strip()[-300:]}"
    return out


def _run(args: dict[str, Any], sandbox) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        if op == "convert":
            return _op_convert(args, sandbox)
        if op == "formats":
            return _op_formats(args, sandbox)
        if op == "markdown_to_html":
            return _string_convert(args.get("text") or "", "markdown", "html", sandbox)
        if op == "html_to_markdown":
            return _string_convert(args.get("text") or "", "html", "markdown", sandbox)
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
