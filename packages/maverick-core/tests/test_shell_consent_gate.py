"""The shell tool routes through the consent gate (opt-in).

The consent/approval system existed but was wired to nothing, so no
destructive action was ever gated. shell() now calls require_consent. The
default mode is 'auto-approve', so this is a no-op out of the box; an operator
who sets MAVERICK_CONSENT_MODE gets real gating.
"""
from __future__ import annotations

from pathlib import Path

from maverick.sandbox import LocalBackend
from maverick.tools.shell import shell


def test_shell_runs_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)  # default = auto-approve
    out = shell(LocalBackend(workdir=tmp_path)).fn({"cmd": "echo hello-shell"})
    assert "hello-shell" in out
    assert "denied by consent policy" not in out


def test_shell_gated_when_consent_denies(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    out = shell(LocalBackend(workdir=tmp_path)).fn({"cmd": "echo should-not-run"})
    assert "denied by consent policy" in out
    # The command must NOT have executed.
    assert "should-not-run" not in out
