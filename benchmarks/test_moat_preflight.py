"""Offline tests for the moat pre-flight -- all no-API, CI-safe. These guard the
checks that make a paid run safe to start."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moat_preflight as MP  # noqa: E402


def test_cite_grader_accepts_real_citation_rejects_vague():
    repo = {"tool_risk.py", "dreaming.py"}
    kws = ["risk", "ceiling"]
    ok, cited = MP.cite_grader("see tool_risk.py for the risk ceiling", repo, kws)
    assert ok and cited == 1
    bad, _ = MP.cite_grader("no codebase available", repo, kws)
    assert not bad


def test_grader_self_test_passes():
    ok, detail = MP.grader_self_test()
    assert ok, detail


def test_distill_mechanism_ok():
    ok, detail = MP.distill_mechanism_ok()
    assert ok, detail


def test_sandbox_can_read_real_codebase(tmp_path):
    # A tiny provisioned codebase: the sandbox must be able to read its source.
    cb = tmp_path / "cb" / "pkg"
    cb.mkdir(parents=True)
    (cb / "mod.py").write_text("MARKER = 42\n")
    ok, detail = MP.sandbox_can_read(tmp_path / "cb")
    assert ok, detail


def test_sandbox_can_read_rejects_empty_codebase(tmp_path):
    ok, detail = MP.sandbox_can_read(tmp_path / "empty")  # missing dir
    assert not ok
    (tmp_path / "empty").mkdir()
    ok2, detail2 = MP.sandbox_can_read(tmp_path / "empty")  # exists but no .py
    assert not ok2 and "no .py sources" in detail2


def test_preflight_runs_all_three_checks(tmp_path):
    cb = tmp_path / "cb"
    cb.mkdir()
    (cb / "x.py").write_text("z = 1\n")
    checks = MP.preflight(cb)
    names = {name for name, _, _ in checks}
    assert names == {"sandbox-can-read", "grader-self-test", "distill-mechanism"}
    assert all(ok for _, ok, _ in checks)  # tiny codebase -> all green
