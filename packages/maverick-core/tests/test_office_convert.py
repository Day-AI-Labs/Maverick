"""Tests for the office_convert tool (LibreOffice headless conversion).

Offline: the LibreOffice binary is faked via shutil.which, and the shell is a
recording sandbox so we assert the argv that would run, never executing it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick.tools.office_convert import office_convert


class RecordingSandbox:
    """Routes sandbox_run through .exec and records the shell string."""

    def __init__(self, workdir, *, exit_code=0, stdout="", stderr=""):
        self.workdir = str(workdir)
        self._res = SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)
        self.commands: list[str] = []

    def exec(self, cmd, timeout=None):
        self.commands.append(cmd)
        return self._res


@pytest.fixture
def have_lo(monkeypatch):
    monkeypatch.setattr(
        "maverick.tools.office_convert.shutil.which",
        lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None,
    )


def test_missing_binary(monkeypatch):
    monkeypatch.setattr("maverick.tools.office_convert.shutil.which", lambda name: None)
    t = office_convert()
    out = t.fn({"op": "convert", "input_path": "report.docx", "to": "pdf"})
    assert out.startswith("ERROR") and "libreoffice not on PATH" in out


def test_convert_builds_headless_command(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path, stdout="convert report.docx -> report.pdf")
    t = office_convert(sandbox=sb)
    out = t.fn({"op": "convert", "input_path": "report.docx", "to": "pdf"})
    assert len(sb.commands) == 1
    cmd = sb.commands[0]
    assert "--headless" in cmd
    assert "--convert-to pdf" in cmd
    assert "--outdir" in cmd
    assert out.startswith("wrote ")
    assert out.endswith("report.pdf") or "report.pdf" in out


def test_to_pdf_shortcut(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path)
    t = office_convert(sandbox=sb)
    t.fn({"op": "to_pdf", "input_path": "sheet.xlsx"})
    assert "--convert-to pdf" in sb.commands[0]


def test_to_text_shortcut(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path)
    t = office_convert(sandbox=sb)
    t.fn({"op": "to_text", "input_path": "deck.pptx"})
    assert "--convert-to txt" in sb.commands[0]


def test_outdir_honored(tmp_path, have_lo):
    (tmp_path / "out").mkdir()
    sb = RecordingSandbox(tmp_path)
    t = office_convert(sandbox=sb)
    out = t.fn({"op": "convert", "input_path": "report.docx",
                "to": "pdf", "outdir": "out"})
    assert "/out" in sb.commands[0]
    assert "out/report.pdf" in out.replace("\\", "/")


def test_rejects_bad_format(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path)
    t = office_convert(sandbox=sb)
    out = t.fn({"op": "convert", "input_path": "report.docx", "to": "-flag"})
    assert out.startswith("ERROR") and "invalid target format" in out
    assert sb.commands == []  # never reached the shell


def test_rejects_dash_path_without_sandbox(have_lo):
    t = office_convert()  # sandbox=None
    out = t.fn({"op": "convert", "input_path": "-evil.docx", "to": "pdf"})
    assert out.startswith("ERROR") and "may not begin with '-'" in out


def test_path_escape_blocked(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path)
    t = office_convert(sandbox=sb)
    out = t.fn({"op": "convert", "input_path": "../../etc/passwd", "to": "pdf"})
    assert out.startswith("ERROR") and "escapes the sandbox workdir" in out


def test_requires_input(have_lo):
    t = office_convert()
    out = t.fn({"op": "convert", "to": "pdf"})
    assert out.startswith("ERROR") and "input_path" in out


def test_nonzero_exit_surfaces_stderr(tmp_path, have_lo):
    sb = RecordingSandbox(tmp_path, exit_code=1, stderr="source file could not be loaded")
    t = office_convert(sandbox=sb)
    out = t.fn({"op": "convert", "input_path": "report.docx", "to": "pdf"})
    assert out.startswith("ERROR: libreoffice (1)") and "could not be loaded" in out


def test_formats_lists_common():
    t = office_convert()
    out = t.fn({"op": "formats"})
    assert "pdf" in out and "docx" in out and "input formats" in out


def test_unknown_op():
    t = office_convert()
    assert t.fn({"op": "frobnicate"}).startswith("ERROR: unknown op")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "office_convert" in names
