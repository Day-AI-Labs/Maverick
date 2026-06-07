"""Diagramming tool (ROADMAP 2027 H2)."""
from __future__ import annotations

import shlex
from pathlib import Path

from maverick.tools.diagram_tool import _argv, diagram_tool


class _FakeSandbox:
    """Creates the renderer's -o output target on success."""

    def __init__(self, succeed=True):
        self.succeed = succeed

    def exec(self, cmd, timeout=None):
        if self.succeed:
            toks = shlex.split(cmd)
            if "-o" in toks:
                Path(toks[toks.index("-o") + 1]).write_text("<svg/>", encoding="utf-8")

        class R:
            pass
        r = R()
        r.exit_code = 0 if self.succeed else 127
        r.stdout, r.stderr = "", "" if self.succeed else "not found"
        return r


def test_argv_dot():
    assert _argv("dot", "in.dot", "out.svg", "svg") == [
        "dot", "-Tsvg", "in.dot", "-o", "out.svg"]


def test_argv_mermaid():
    assert _argv("mermaid", "in.mmd", "out.png", "png") == [
        "mmdc", "-i", "in.mmd", "-o", "out.png"]


def test_render_dot_success(tmp_path):
    out = tmp_path / "g.svg"
    res = diagram_tool(_FakeSandbox()).fn(
        {"engine": "dot", "source": "digraph{a->b}", "out": str(out)})
    assert "rendered dot diagram" in res
    assert out.exists()


def test_render_invalid_engine():
    res = diagram_tool(_FakeSandbox()).fn({"engine": "bogus", "source": "x"})
    assert res.startswith("ERROR") and "engine" in res


def test_render_invalid_format(tmp_path):
    res = diagram_tool(_FakeSandbox()).fn(
        {"engine": "dot", "source": "digraph{}", "format": "gif"})
    assert res.startswith("ERROR") and "format" in res


def test_render_binary_missing(tmp_path):
    res = diagram_tool(_FakeSandbox(succeed=False)).fn(
        {"engine": "mermaid", "source": "graph TD; A-->B", "out": str(tmp_path / "d.svg")})
    assert res.startswith("ERROR") and "installed" in res


def test_empty_source():
    assert diagram_tool(_FakeSandbox()).fn(
        {"engine": "dot", "source": "  "}).startswith("ERROR")
