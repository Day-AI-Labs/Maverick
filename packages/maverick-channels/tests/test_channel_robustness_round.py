"""Audit round 10: channel robustness + outbound info-hygiene.

1. Signal: the outbound reply send sat OUTSIDE the receive loop's try/except, so
   a send failure (signal-cli's stdin breaks when the daemon dies/restarts --
   exactly when sends fail) propagated out of start() and killed the whole
   channel. Now guarded, like email/sms/whatsapp.

2. Error-text leakage: several channels reflected the raw exception text back to
   the remote user (``f"⚠ error: {e}"``), which can carry a credential or
   internal path. The detail is already logged; the user now gets a generic
   message (matching slack/signal). Voice is the representative case here.
"""
from __future__ import annotations

import asyncio
import json

import pytest

# --- fix 1: a Signal send failure must not kill the receive loop -----------

class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class _FakeProc:
    pid = 4242
    returncode = None

    def __init__(self, stdout):
        self.stdout = stdout
        self.stdin = None


def test_signal_send_failure_does_not_kill_loop(monkeypatch):
    from maverick_channels.signal import SignalChannel

    async def _noop(_):
        return "reply"

    chan = SignalChannel(
        handler=_noop,
        phone_number="+12345550199",
        signal_cli_path="/bin/sh",
        allowed_user_ids={"+12345550100"},
    )

    line = json.dumps({
        "method": "receive",
        "params": {"envelope": {
            "source": "+12345550100",
            "dataMessage": {"message": "hello"},
        }},
    }).encode() + b"\n"

    async def _fake_create(*a, **k):
        return _FakeProc(_FakeStdout([line, b""]))  # one message, then EOF

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    sent: list = []

    async def _boom(user_id, text):
        sent.append((user_id, text))
        raise BrokenPipeError("signal-cli stdin closed")

    monkeypatch.setattr(chan, "send", _boom)

    async def _reply(_msg):
        return "the reply"

    monkeypatch.setattr(chan, "dispatch_text", _reply)

    # The send raises, but start() must swallow it, keep looping, hit EOF, and
    # return -- not propagate the BrokenPipeError out of the channel.
    asyncio.run(chan.start())
    assert sent and sent[0][0] == "+12345550100"


# --- fix 2: handler errors are not reflected to the remote user ------------

def test_voice_handler_error_is_generic_not_leaked(monkeypatch):
    from fastapi.testclient import TestClient
    from maverick_channels.voice import VoiceChannel

    secret = "sk-do-not-leak-9876"  # pragma: allowlist secret

    async def _raises(_):
        raise RuntimeError(f"db connect failed token={secret}")

    monkeypatch.setenv("VAPI_WEBHOOK_TOKEN", "voice-secret")  # pragma: allowlist secret
    chan = VoiceChannel(handler=_raises, api_key="vapi-test-key")
    client = TestClient(chan._app)
    resp = client.post(
        "/webhook/voice",
        json={"message": {"type": "transcript", "role": "user", "transcript": "hi"}},
        headers={"Authorization": "Bearer voice-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()["response"]
    assert secret not in body
    assert "error" in body.lower()  # a generic apology, no raw detail


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
