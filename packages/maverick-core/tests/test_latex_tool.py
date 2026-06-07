"""LaTeX tool (ROADMAP 2027 H2)."""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from maverick.tools.latex_tool import latex_tool, to_mathml


class _FakeSandbox:
    """Sandbox whose exec creates the TeX engine's output PDF, then succeeds."""

    def __init__(self, succeed=True):
        self.succeed = succeed

    def exec(self, cmd, timeout=None):
        if self.succeed:
            # tectonic --outdir <dir> <tex>  /  pdflatex -output-directory <dir>
            parts = shlex.split(cmd)
            outdir = None
            for flag in ("--outdir", "-output-directory"):
                if flag in parts:
                    outdir = parts[parts.index(flag) + 1]
            if outdir:
                Path(outdir).mkdir(parents=True, exist_ok=True)
                (Path(outdir) / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

        class R:
            pass
        r = R()
        r.exit_code = 0 if self.succeed else 127
        r.stdout, r.stderr = "", "" if self.succeed else "command not found"
        return r


def test_mathml_conversion():
    pytest.importorskip("latex2mathml")
    out = to_mathml(r"x^2 + 1")
    assert "<math" in out and "</math>" in out


def test_mathml_op_via_tool():
    pytest.importorskip("latex2mathml")
    out = latex_tool(_FakeSandbox()).fn({"op": "mathml", "latex": r"\frac{a}{b}"})
    assert "<math" in out


def test_render_success(tmp_path):
    out_pdf = tmp_path / "out" / "paper.pdf"
    tool = latex_tool(_FakeSandbox(succeed=True))
    out = tool.fn({"op": "render", "latex": r"\documentclass{article}\begin{document}hi\end{document}",
                   "out": str(out_pdf)})
    assert "rendered PDF" in out
    assert out_pdf.exists()


def test_render_engine_missing(tmp_path):
    tool = latex_tool(_FakeSandbox(succeed=False))
    out = tool.fn({"op": "render", "latex": r"\documentclass{article}\begin{document}x\end{document}",
                   "out": str(tmp_path / "x.pdf")})
    assert out.startswith("ERROR") and "installed" in out


def test_empty_latex():
    assert latex_tool(_FakeSandbox()).fn({"op": "mathml", "latex": "  "}).startswith("ERROR")
