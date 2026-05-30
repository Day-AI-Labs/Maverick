"""Per-sender authorization gates for inbound channel adapters.

Regression for the launch-audit HIGH: slack/signal/matrix dispatched every
inbound message to the swarm with NO identity gate (any reachable user could
drive the agent + burn the operator's budget); voice only had a single shared
bearer. These pin the default-deny allowlist behaviour.
"""
from __future__ import annotations

import pytest

from maverick_channels.base import is_allowed, normalize_allowlist


def test_is_allowed_default_deny():
    """Unknown / missing / 'anonymous' senders never pass; only explicit
    allowlist members do."""
    allow = normalize_allowlist(["u1", "u2"], "UNUSED_ENV")
    assert is_allowed("u1", allow) is True
    assert is_allowed("u2", allow) is True
    assert is_allowed("intruder", allow) is False
    assert is_allowed("", allow) is False
    assert is_allowed("anonymous", allow) is False
    assert is_allowed(None, allow) is False
    # An empty allowlist denies everyone (fail-closed).
    assert is_allowed("u1", set()) is False


def test_signal_requires_allowlist(monkeypatch):
    """SignalChannel must refuse to start without an allowlist (default-deny),
    matching discord/telegram."""
    from maverick_channels.signal import SignalChannel

    async def _noop(_):
        return "ok"

    monkeypatch.delenv("SIGNAL_ALLOWED_USER_IDS", raising=False)
    # Pass a fake cli path so the shutil.which() check passes and we reach
    # the allowlist guard.
    with pytest.raises(ValueError, match="SIGNAL_ALLOWED_USER_IDS"):
        SignalChannel(_noop, phone_number="+12025550100",
                      signal_cli_path="/usr/bin/false")

    # With an allowlist it constructs and stores the normalized set.
    chan = SignalChannel(_noop, phone_number="+12025550100",
                         signal_cli_path="/usr/bin/false",
                         allowed_user_ids=["+12025550111"])
    assert chan.allowed_user_ids == {"+12025550111"}
    # The same gate the receive loop uses:
    assert is_allowed("+12025550111", chan.allowed_user_ids) is True
    assert is_allowed("+19998887777", chan.allowed_user_ids) is False


def _have_voice_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_voice_deps(), reason="fastapi+httpx not installed")
def test_voice_allowlist_blocks_unauthorized_caller(monkeypatch):
    from fastapi.testclient import TestClient

    from maverick_channels.voice import VoiceChannel

    seen = []

    async def _handler(msg):
        seen.append(msg.user_id)
        return "ran"

    monkeypatch.setenv("VAPI_WEBHOOK_TOKEN", "voice-secret")
    chan = VoiceChannel(_handler, api_key="vapi-test-key",
                        allowed_callers=["+12025550111"])
    client = TestClient(chan._app)
    hdr = {"Authorization": "Bearer voice-secret"}

    def _post(number):
        return client.post("/webhook/voice", headers=hdr, json={
            "message": {"type": "transcript", "role": "user", "transcript": "hi"},
            "call": {"customer": {"number": number}},
        })

    # Unauthorized caller: rejected, handler never runs.
    resp = _post("+19998887777")
    assert resp.status_code == 200
    assert "authorized" in resp.json()["response"].lower()
    assert seen == []

    # Authorized caller: handler runs.
    resp = _post("+12025550111")
    assert resp.status_code == 200
    assert resp.json() == {"response": "ran"}
    assert seen == ["+12025550111"]


@pytest.mark.skipif(not _have_voice_deps(), reason="fastapi+httpx not installed")
def test_voice_without_allowlist_allows_any_authenticated_caller(monkeypatch):
    """Back-compat: with no allowlist, the bearer is the gate (any caller)."""
    from fastapi.testclient import TestClient

    from maverick_channels.voice import VoiceChannel

    async def _handler(_):
        return "ran"

    monkeypatch.setenv("VAPI_WEBHOOK_TOKEN", "voice-secret")
    monkeypatch.delenv("VOICE_ALLOWED_CALLERS", raising=False)
    chan = VoiceChannel(_handler, api_key="vapi-test-key")
    client = TestClient(chan._app)
    resp = client.post("/webhook/voice", headers={"Authorization": "Bearer voice-secret"}, json={
        "message": {"type": "transcript", "role": "user", "transcript": "hi"},
        "call": {"customer": {"number": "+19998887777"}},
    })
    assert resp.status_code == 200
    assert resp.json() == {"response": "ran"}


def _have_slack() -> bool:
    try:
        import slack_sdk  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_slack(), reason="slack_sdk not installed")
def test_slack_requires_allowlist(monkeypatch):
    from maverick_channels.slack import SlackChannel
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-1")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    monkeypatch.delenv("SLACK_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(ValueError, match="SLACK_ALLOWED_USER_IDS"):
        SlackChannel(lambda m: None)


def _have_matrix() -> bool:
    try:
        import nio  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_matrix(), reason="matrix-nio not installed")
def test_matrix_requires_allowlist(monkeypatch):
    from maverick_channels.matrix import MatrixChannel
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "tok")
    monkeypatch.delenv("MATRIX_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(ValueError, match="MATRIX_ALLOWED_USER_IDS"):
        MatrixChannel(lambda m: None, homeserver="https://h", user_id="@a:h")
