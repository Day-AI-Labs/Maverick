"""iMessage send-safety smoke test.

Critical security property: send() must pass user-controlled text as
argv to AppleScript, never interpolate it into the script body. An LLM
emitting `"; tell application "Finder" to ...` must be inert.

We can only run the macOS-only import path on macOS, but we *can* test
the AppleScript constant + the subprocess.run shape on any platform.
"""
from __future__ import annotations

import platform
from unittest.mock import patch

import pytest


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="iMessage channel imports macOS-only APIs at construction",
)
def test_send_passes_text_via_argv_not_interpolation():
    """The send() path must invoke osascript with text/handle as argv."""
    from maverick_channels.imessage import iMessageChannel

    async def _noop(_):
        return ""

    # Construct without hitting chat.db. We patch the file-existence check.
    with patch("maverick_channels.imessage.CHAT_DB") as fake_db:
        fake_db.exists.return_value = True
        fake_db.__fspath__ = lambda: "/tmp/fake_chat.db"
        chan = iMessageChannel(
            handler=_noop, poll_interval=1, allowed_user_ids={"+1555"},
        )

    import asyncio
    with patch("maverick_channels.imessage.subprocess.run") as run_mock:
        asyncio.run(chan.send(
            "+1555",
            'malicious"; tell app "Finder" to delete every file',
        ))

    assert run_mock.called
    args, kwargs = run_mock.call_args
    # The cmdline must be osascript reading from stdin, with text + handle as argv.
    argv = args[0]
    assert argv[0] == "osascript"
    assert argv[1] == "-"
    assert argv[2] == 'malicious"; tell app "Finder" to delete every file'
    assert argv[3] == "+1555"
    # And the script body comes from stdin, not the cmdline.
    assert "input" in kwargs
    assert "on run argv" in kwargs["input"]


def test_send_script_does_not_interpolate_text():
    """Static check on the script constant itself."""
    from maverick_channels.imessage import _SEND_SCRIPT
    # The script reads argv -- it must not contain `%s` or `{` placeholders
    # that suggest python-side string formatting.
    assert "%s" not in _SEND_SCRIPT
    assert "{" not in _SEND_SCRIPT
    assert "on run argv" in _SEND_SCRIPT
    assert "item 1 of argv" in _SEND_SCRIPT
    assert "item 2 of argv" in _SEND_SCRIPT


def _make_channel():
    """Build an iMessageChannel without hitting the macOS-only __init__ guards."""
    from maverick_channels.imessage import iMessageChannel

    chan = iMessageChannel.__new__(iMessageChannel)
    chan.allowed_user_ids = {"+1555"}
    chan.poll_interval = 0
    chan._last_rowid = 0
    chan._stop = False
    return chan


def test_start_survives_send_failure():
    """A transient send() failure (e.g. osascript TimeoutExpired / OSError)
    must NOT propagate out of start() and kill the poll loop.

    Regression: line 97 `await self.send(...)` was previously unguarded, so a
    subprocess.TimeoutExpired (which check=False does not suppress) terminated
    the whole receive loop permanently.
    """
    import asyncio
    import subprocess

    chan = _make_channel()

    fetched = {"done": False}

    def _fetch_new():
        if fetched["done"]:
            chan._stop = True
            return []
        fetched["done"] = True
        return [("+1555", "hi", 1)]

    sent = {"attempts": 0}

    async def _dispatch(_msg):
        return "reply"

    async def _send(_user, _text):
        sent["attempts"] += 1
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=10)

    chan._fetch_new = _fetch_new
    chan._latest_rowid = lambda: 0
    chan.dispatch_text = _dispatch
    chan.send = _send

    # Without the fix this raises TimeoutExpired out of start(); with the fix
    # the send failure is logged and the loop continues to a clean stop.
    asyncio.run(asyncio.wait_for(chan.start(), timeout=5))

    assert sent["attempts"] == 1  # the send was attempted (and failed) once


def test_start_skips_empty_reply():
    """An empty reply (action-only goal) should not trigger a send call."""
    import asyncio

    chan = _make_channel()

    fetched = {"done": False}

    def _fetch_new():
        if fetched["done"]:
            chan._stop = True
            return []
        fetched["done"] = True
        return [("+1555", "hi", 1)]

    async def _dispatch(_msg):
        return ""

    sent = {"attempts": 0}

    async def _send(_user, _text):
        sent["attempts"] += 1

    chan._fetch_new = _fetch_new
    chan._latest_rowid = lambda: 0
    chan.dispatch_text = _dispatch
    chan.send = _send

    asyncio.run(asyncio.wait_for(chan.start(), timeout=5))

    assert sent["attempts"] == 0
