"""The clipboard tool gates read AND write through the consent path (#476).

The clipboard holds passwords / 2FA codes / tokens, and it's host-bound so it
can't be sandbox-mediated. Both read and write therefore route through
require_consent. The default mode is 'auto-approve', so this is a no-op out of
the box; an operator who sets MAVERICK_CONSENT_MODE=auto-deny gets every
clipboard access blocked with a clear error (not a crash).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.tools.clipboard import clipboard


@pytest.fixture
def _fake_backends(monkeypatch):
    """Stub the actual clipboard backends so the test never touches a real
    desktop clipboard; we only care about the consent gate around them."""
    monkeypatch.setattr("maverick.tools.clipboard._read_clipboard", lambda: "SECRET")
    monkeypatch.setattr("maverick.tools.clipboard._write_clipboard", lambda text: True)


def test_clipboard_read_blocked_under_auto_deny(tmp_path: Path, monkeypatch, _fake_backends):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    out = clipboard().fn({"op": "read"})
    assert out == "ERROR: clipboard access denied (consent)"
    # The secret must NOT have been returned.
    assert "SECRET" not in out


def test_clipboard_write_blocked_under_auto_deny(tmp_path: Path, monkeypatch, _fake_backends):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    out = clipboard().fn({"op": "write", "text": "planted"})
    assert out == "ERROR: clipboard access denied (consent)"


def test_clipboard_read_allowed_under_auto_approve(tmp_path: Path, monkeypatch, _fake_backends):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)  # default = auto-approve
    out = clipboard().fn({"op": "read"})
    assert out == "SECRET"


def test_clipboard_write_allowed_under_auto_approve(tmp_path: Path, monkeypatch, _fake_backends):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    out = clipboard().fn({"op": "write", "text": "hello"})
    assert "wrote 5 chars" in out


def test_clipboard_env_disable_still_wins(tmp_path: Path, monkeypatch, _fake_backends):
    """The pre-existing global env disable is preserved and short-circuits
    before the consent gate."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_CLIPBOARD_DISABLE", "1")
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    out = clipboard().fn({"op": "read"})
    assert "disabled by MAVERICK_CLIPBOARD_DISABLE" in out
