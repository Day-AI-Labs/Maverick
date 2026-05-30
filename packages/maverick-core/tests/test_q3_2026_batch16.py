"""Q3 2026 batch 16.

  - Browser session persistence: cookies + localStorage saved to disk
    via storage_state and restored on the next context, surviving
    restarts/crashes. Tested with mocked sessions (no real chromium).
"""
from __future__ import annotations

import maverick.tools.browser as browser_mod
from maverick.tools.browser import (
    _BrowserSession,
    _persist_enabled,
    _restore_state_arg,
    _state_path,
    browser,
)


# ---------- path / toggle helpers (pure) ----------

def test_state_path_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_BROWSER_STATE", raising=False)
    p = _state_path()
    assert p.name == "state.json"
    assert p.parent.name == "browser"


def test_state_path_override(monkeypatch, tmp_path):
    target = tmp_path / "profileA.json"
    monkeypatch.setenv("MAVERICK_BROWSER_STATE", str(target))
    assert _state_path() == target


def test_persist_enabled_toggle(monkeypatch):
    monkeypatch.delenv("MAVERICK_BROWSER_NO_PERSIST", raising=False)
    assert _persist_enabled() is True
    monkeypatch.setenv("MAVERICK_BROWSER_NO_PERSIST", "1")
    assert _persist_enabled() is False


def test_restore_arg_none_when_missing(monkeypatch, tmp_path):
    target = tmp_path / "nope.json"
    monkeypatch.setenv("MAVERICK_BROWSER_STATE", str(target))
    monkeypatch.delenv("MAVERICK_BROWSER_NO_PERSIST", raising=False)
    assert _restore_state_arg() is None  # file does not exist yet
    target.write_text("{}")
    assert _restore_state_arg() == str(target)
    monkeypatch.setenv("MAVERICK_BROWSER_NO_PERSIST", "1")
    assert _restore_state_arg() is None  # disabled wins even when file exists


# ---------- save_state on the session ----------

class _FakeContext:
    def __init__(self):
        self.saved_to = None

    def storage_state(self, path):
        self.saved_to = path
        # Mimic playwright: write a valid state file.
        from pathlib import Path
        Path(path).write_text('{"cookies": [], "origins": []}')


def test_save_state_writes_file_with_secure_perms(monkeypatch, tmp_path):
    import stat
    target = tmp_path / "sub" / "state.json"
    monkeypatch.setenv("MAVERICK_BROWSER_STATE", str(target))
    monkeypatch.delenv("MAVERICK_BROWSER_NO_PERSIST", raising=False)

    sess = _BrowserSession()
    sess._context = _FakeContext()
    assert sess.save_state() is True
    assert target.exists()
    import os
    if os.name != "nt":  # NTFS reports 0o666 regardless of chmod
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_save_state_noop_without_context(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_BROWSER_STATE", str(tmp_path / "s.json"))
    sess = _BrowserSession()
    assert sess.save_state() is False  # no context started


def test_save_state_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_BROWSER_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("MAVERICK_BROWSER_NO_PERSIST", "1")
    sess = _BrowserSession()
    sess._context = _FakeContext()
    assert sess.save_state() is False


# ---------- action wiring (mocked session, no playwright) ----------

class _FakePage:
    url = "about:blank"

    def goto(self, url, timeout, wait_until):
        self.url = url


class _FakeSession:
    def __init__(self):
        self._page = _FakePage()
        self.save_calls = 0

    @property
    def page(self):
        return self._page

    def save_state(self):
        self.save_calls += 1
        return True


def test_navigate_checkpoints_session(monkeypatch):
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "0")
    fake = _FakeSession()
    monkeypatch.setattr(browser_mod, "_get_session", lambda: fake)
    out = browser_mod._run_browser_action({"action": "navigate", "url": "https://example.com"})
    assert out.startswith("navigated to https://example.com")
    assert fake.save_calls == 1


def test_save_session_action(monkeypatch):
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "0")
    fake = _FakeSession()
    monkeypatch.setattr(browser_mod, "_get_session", lambda: fake)
    out = browser_mod._run_browser_action({"action": "save_session"})
    assert out == "session saved"
    assert fake.save_calls == 1


def test_save_session_reports_when_not_saved(monkeypatch):
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "0")

    class _NoSaveSession(_FakeSession):
        def save_state(self):
            return False

    monkeypatch.setattr(browser_mod, "_get_session", lambda: _NoSaveSession())
    out = browser_mod._run_browser_action({"action": "save_session"})
    assert "not saved" in out.lower()


def test_schema_includes_save_session():
    actions = browser().input_schema["properties"]["action"]["enum"]
    assert "save_session" in actions
