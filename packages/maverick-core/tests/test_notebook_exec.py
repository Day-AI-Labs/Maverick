"""Notebook execution tool (ROADMAP 2027 H2)."""
from __future__ import annotations

import json

from maverick.tools.notebook_exec import _extract_code, notebook_exec


class _FakeSandbox:
    def __init__(self, stdout="hello\n", code=0, stderr="", workdir="."):
        self.stdout, self.code, self.stderr = stdout, code, stderr
        self.workdir = workdir
        self.last_cmd = None

    def exec(self, cmd, timeout=None):
        self.last_cmd = cmd

        class R:
            pass
        r = R()
        r.exit_code, r.stdout, r.stderr = self.code, self.stdout, self.stderr
        return r


def _nb(*sources, markdown=True):
    cells = []
    if markdown:
        cells.append({"cell_type": "markdown", "source": ["# title\n"]})
    for s in sources:
        cells.append({"cell_type": "code", "source": s})
    return {"cells": cells, "nbformat": 4}


def test_extract_skips_markdown_and_magics():
    nb = _nb(["%matplotlib inline\n", "print('a')\n"], ["!pip install x\n", "print('b')\n"])
    code = _extract_code(nb)
    assert "print('a')" in code and "print('b')" in code
    assert "%matplotlib" not in code and "!pip" not in code
    assert "# title" not in code


def test_extract_empty_when_no_code():
    assert _extract_code({"cells": [{"cell_type": "markdown", "source": ["x"]}]}) == ""


def test_run_executes_via_sandbox(tmp_path):
    nb_path = tmp_path / "nb.ipynb"
    nb_path.write_text(json.dumps(_nb(["print('hi')\n"])), encoding="utf-8")
    sb = _FakeSandbox(stdout="hi\n", code=0, workdir=str(tmp_path))
    tool = notebook_exec(sb)
    out = tool.fn({"path": str(nb_path)})
    assert "exit_code: 0" in out
    assert "hi" in out
    assert "python" in sb.last_cmd  # ran through the sandbox


def test_run_missing_file(tmp_path):
    out = notebook_exec(_FakeSandbox(workdir=str(tmp_path))).fn(
        {"path": str(tmp_path / "no_such.ipynb")})
    assert out.startswith("ERROR")


def test_run_no_code_cells(tmp_path):
    nb_path = tmp_path / "nb.ipynb"
    nb_path.write_text(json.dumps({"cells": []}), encoding="utf-8")
    out = notebook_exec(_FakeSandbox(workdir=str(tmp_path))).fn({"path": str(nb_path)})
    assert "no executable code" in out


def test_run_confines_path_to_sandbox_workspace(tmp_path):
    """A notebook path outside the sandbox workdir is refused before any
    cell executes -- a model-supplied ~/anything.ipynb must not run."""
    workdir = tmp_path / "ws"
    workdir.mkdir()
    outside = tmp_path / "secret.ipynb"
    outside.write_text(json.dumps(_nb(["print('hi')\n"])), encoding="utf-8")
    sb = _FakeSandbox(workdir=str(workdir))
    out = notebook_exec(sb).fn({"path": str(outside)})
    assert out.startswith("ERROR: path escapes the workspace")
    assert sb.last_cmd is None  # never executed
