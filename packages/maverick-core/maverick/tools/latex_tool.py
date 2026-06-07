"""LaTeX tool: render math to MathML and full documents to PDF.

Two ops:
  - ``mathml``: convert a LaTeX math expression to MathML via the pure-Python
    ``latex2mathml`` package (optional dep) — no TeX install needed.
  - ``render``: compile a full LaTeX document to PDF by shelling a TeX engine
    (``tectonic`` or ``pdflatex``) through the sandbox chokepoint.

Both degrade with an actionable error when their dependency is missing, per the
optional-dependency knob exemption. ``mathml`` needs ``pip install
maverick-agent[latex]``; ``render`` needs a TeX engine on PATH in the sandbox.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import Tool, sandbox_run
from .ffmpeg_tool import _safe_path

_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["mathml", "render"], "default": "mathml"},
        "latex": {"type": "string", "description": "LaTeX source (math for mathml, full doc for render)"},
        "engine": {"type": "string", "enum": ["tectonic", "pdflatex"],
                   "description": "TeX engine for render (default tectonic)"},
        "out": {"type": "string", "description": "output PDF path (render op)"},
    },
    "required": ["latex"],
}


def to_mathml(latex: str) -> str:
    """Convert a LaTeX math expression to a MathML string."""
    try:
        from latex2mathml import converter
    except ImportError as e:
        raise RuntimeError(
            "mathml needs the 'latex2mathml' package. Install it with: "
            "pip install 'maverick-agent[latex]'") from e
    return converter.convert(latex)


def _render_pdf(latex: str, sandbox, engine: str, out: str) -> str:
    eng = engine if engine in ("tectonic", "pdflatex") else "tectonic"
    workdir = Path(tempfile.mkdtemp(prefix="mvk-latex-"))
    tex = workdir / "doc.tex"
    tex.write_text(latex, encoding="utf-8")
    if eng == "tectonic":
        argv = ["tectonic", "--outdir", str(workdir), str(tex)]
    else:
        argv = ["pdflatex", "-interaction=nonstopmode",
                "-output-directory", str(workdir), str(tex)]
    code, stdout, stderr = sandbox_run(sandbox, argv, timeout=120.0)
    pdf = workdir / "doc.pdf"
    if code != 0 or not pdf.exists():
        tail = (stderr or stdout or "").strip()[-500:]
        return (f"ERROR: {eng} failed (exit {code}); is it installed in the "
                f"sandbox? {tail}")
    # Confine the model-supplied destination to the sandbox workspace; an
    # unconfined `out` would let the tool overwrite arbitrary host files.
    try:
        dest = Path(_safe_path(sandbox, out or "doc.pdf"))
    except ValueError as e:
        return f"ERROR: {e}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, dest)
    return f"rendered PDF -> {dest}"


def _run(args: dict[str, Any], sandbox) -> str:
    op = args.get("op") or "mathml"
    latex = args.get("latex") or ""
    if not latex.strip():
        return "ERROR: latex source is required"
    try:
        if op == "mathml":
            return to_mathml(latex)
        if op == "render":
            return _render_pdf(latex, sandbox, args.get("engine") or "tectonic",
                               args.get("out") or "")
    except RuntimeError as e:
        return f"ERROR: {e}"
    return f"ERROR: unknown op {op!r}"


def latex_tool(sandbox) -> Tool:
    return Tool(
        name="latex",
        description=(
            "Render LaTeX. ops: mathml (math expr -> MathML, pure-Python, needs "
            "maverick-agent[latex]); render (full document -> PDF via tectonic/"
            "pdflatex in the sandbox). Input: latex, op, engine, out."
        ),
        input_schema=_SCHEMA,
        fn=lambda args: _run(args, sandbox),
    )


__all__ = ["latex_tool", "to_mathml"]
