"""Office-document converter (roadmap: 2028 H1 capabilities).

LibreOffice headless conversion for the *binary* office formats pandoc can't
take — Word/Excel/PowerPoint/OpenDocument — into PDF / text / HTML / CSV.
``pandoc`` (the sibling tool) handles markup formats; this fills the
docx/xlsx/pptx → pdf gap that a business workflow actually hits.

Auth: none. Requires the ``libreoffice`` (or ``soffice``) binary on PATH.

ops:
  - convert(input_path, to, outdir?)  — convert to any LibreOffice target
  - to_pdf(input_path, outdir?)       — shortcut: --convert-to pdf
  - to_text(input_path, outdir?)      — shortcut: --convert-to txt
  - formats()                         — the common input/output formats

All shell goes through the sandbox chokepoint (CLAUDE.md #4); paths are
confined to the sandbox workdir and may not begin with '-' (option injection).
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)

_OFFICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["convert", "to_pdf", "to_text", "formats"],
        },
        "input_path": {"type": "string"},
        "to": {"type": "string",
               "description": "LibreOffice target, e.g. pdf, txt, html, csv, docx"},
        "outdir": {"type": "string",
                   "description": "output directory (defaults to the input's dir)"},
    },
    "required": ["op"],
}

# A LibreOffice convert-to token: a format ('pdf') optionally with an explicit
# filter ('txt:Text'). Must start alnum so it can never be read as a flag.
_TO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 :._-]*$")

_COMMON_INPUTS = ("doc", "docx", "odt", "rtf", "xls", "xlsx", "ods",
                  "ppt", "pptx", "odp", "csv", "html")
_COMMON_OUTPUTS = ("pdf", "txt", "html", "csv", "docx", "odt", "xlsx", "png")


def _need_libreoffice() -> tuple[str | None, str | None]:
    """Return (binary, None) or (None, error). Prefers ``libreoffice``."""
    for name in ("libreoffice", "soffice"):
        if shutil.which(name):
            return name, None
    return None, "ERROR: libreoffice not on PATH. Install LibreOffice."


def _safe_path(sandbox, user_path: str) -> str:
    if sandbox is None:
        if user_path.startswith("-"):
            raise ValueError(f"path {user_path!r} may not begin with '-'")
        return user_path
    workdir = Path(sandbox.workdir).resolve()
    candidate = (workdir / user_path).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as e:
        raise ValueError(f"path {user_path!r} escapes the sandbox workdir") from e
    return str(candidate)


def _op_convert(args: dict, sandbox, to_override: str | None = None) -> str:
    binary, err = _need_libreoffice()
    if err:
        return err
    src = (args.get("input_path") or "").strip()
    to = (to_override or args.get("to") or "").strip()
    if not src:
        return "ERROR: convert requires input_path"
    if not to:
        return "ERROR: convert requires a target format (to)"
    if not _TO_RE.match(to):
        return f"ERROR: invalid target format {to!r}"
    try:
        src = _safe_path(sandbox, src)
        outdir = (args.get("outdir") or "").strip()
        outdir = _safe_path(sandbox, outdir) if outdir else str(Path(src).parent)
    except ValueError as e:
        return f"ERROR: {e}"
    cmd = [binary, "--headless", "--convert-to", to, "--outdir", outdir, src]
    from . import sandbox_run
    code, out, stderr = sandbox_run(sandbox, cmd, timeout=180)
    if code != 0:
        return f"ERROR: libreoffice ({code}): {stderr.strip()[-300:]}"
    ext = to.split(":")[0].strip()
    dst = Path(outdir) / f"{Path(src).stem}.{ext}"
    # LibreOffice prints "convert ... -> /path output_FILTER"; surface its line
    # too, but the derived dst is the predictable answer.
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    suffix = f"\n{tail}" if tail else ""
    # Verify the output exists -- but only when the sandbox filesystem is
    # visible to this process. Under a container/remote backend the host can't
    # stat the path, so a naive exists() check would mis-report every success
    # as "missing"; there we report the path without claiming to have confirmed.
    from ..sandbox import fs_is_host_visible
    if not fs_is_host_visible(sandbox):
        return f"wrote {dst} (in sandbox; not host-visible to verify here){suffix}"
    try:
        if dst.exists():
            return f"wrote {dst} ({dst.stat().st_size} bytes){suffix}"
    except OSError:
        return f"wrote {dst}{suffix}"
    return (f"WARNING: libreoffice exited 0 but {dst} is not present -- it may "
            f"have written a different filename; check the output directory.{suffix}")


def _op_formats(_args: dict, _sandbox) -> str:
    return ("common input formats:\n  " + ", ".join(_COMMON_INPUTS) +
            "\n\ncommon output formats:\n  " + ", ".join(_COMMON_OUTPUTS) +
            "\n\n(any LibreOffice filter token works as `to`, e.g. 'txt:Text')")


def _run(args: dict[str, Any], sandbox) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        if op == "convert":
            return _op_convert(args, sandbox)
        if op == "to_pdf":
            return _op_convert(args, sandbox, to_override="pdf")
        if op == "to_text":
            return _op_convert(args, sandbox, to_override="txt")
        if op == "formats":
            return _op_formats(args, sandbox)
    except Exception as e:
        return f"ERROR: libreoffice failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def office_convert(sandbox=None) -> Tool:
    return Tool(
        name="office_convert",
        description=(
            "Convert binary office documents (Word/Excel/PowerPoint/"
            "OpenDocument) via LibreOffice headless. ops: convert "
            "(input_path + to format + optional outdir), to_pdf, to_text, "
            "formats. Requires libreoffice/soffice on PATH. Use pandoc for "
            "markup formats (md/html/rst)."
        ),
        input_schema=_OFFICE_SCHEMA,
        fn=lambda args: _run(args, sandbox),
    )
