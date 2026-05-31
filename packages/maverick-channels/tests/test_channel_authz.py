"""Sender-authorization contract for every inbound channel.

Each channel must refuse to run the agent for a sender that isn't on an
explicit allowlist. Before this, slack/signal/matrix/imessage had no
allowlist at all, so any stranger who could reach the bot could drive
the swarm and burn the operator's API budget. These tests pin the
fail-closed behaviour so it can't silently regress.

Channels with optional third-party SDKs (slack_sdk, matrix-nio) can only
be constructed where the SDK is installed, so those cases skip cleanly
on a bare CI runner. The shared gate (``is_allowed`` / ``normalize_allowlist``)
is dependency-free and always exercised.
"""
from __future__ import annotations

import pytest
from maverick_channels.base import is_allowed, normalize_allowlist


async def _noop(_):
    return ""


# --- shared gate -----------------------------------------------------------

def test_is_allowed_denies_unknown_and_anonymous():
    allow = {"alice", "bob"}
    assert is_allowed("alice", allow) is True
    assert is_allowed("carol", allow) is False
    # Missing / sentinel ids never pass, even against a populated allowlist.
    assert is_allowed("", allow) is False
    assert is_allowed(None, allow) is False
    assert is_allowed("anonymous", allow) is False


def test_is_allowed_empty_allowlist_denies_everyone():
    # An empty allowlist is deny-all, never allow-all.
    assert is_allowed("alice", set()) is False


def test_normalize_allowlist_from_arg_and_env(monkeypatch):
    assert normalize_allowlist({"a", " b "}, "X_ALLOWED") == {"a", "b"}
    monkeypatch.setenv("X_ALLOWED", "u1, u2 ,, u3")
    assert normalize_allowlist(None, "X_ALLOWED") == {"u1", "u2", "u3"}
    monkeypatch.delenv("X_ALLOWED", raising=False)
    assert normalize_allowlist(None, "X_ALLOWED") == set()


# --- per-channel: construction is fail-closed ------------------------------

def test_signal_requires_allowlist():
    from maverick_channels.signal import SignalChannel
    with pytest.raises(ValueError, match="SIGNAL_ALLOWED_USER_IDS"):
        SignalChannel(
            handler=_noop, phone_number="+12345550199", allowed_user_ids=set(),
        )


def test_signal_stores_allowlist_and_denies_non_member():
    from maverick_channels.signal import SignalChannel
    # Pass an existing path so construction gets past the signal-cli probe.
    chan = SignalChannel(
        handler=_noop,
        phone_number="+12345550199",
        signal_cli_path="/bin/sh",
        allowed_user_ids={"+12345550100"},
    )
    assert is_allowed("+12345550100", chan.allowed_user_ids) is True
    assert is_allowed("+19998887777", chan.allowed_user_ids) is False


def test_slack_requires_allowlist():
    slack = pytest.importorskip("maverick_channels.slack")
    if not slack._HAVE_SLACK:
        pytest.skip("slack_sdk not installed")
    with pytest.raises(ValueError, match="SLACK_ALLOWED_USER_IDS"):
        slack.SlackChannel(
            handler=_noop, app_token="xapp-x", bot_token="xoxb-x",
            allowed_user_ids=set(),
        )


def test_matrix_requires_allowlist():
    matrix = pytest.importorskip("maverick_channels.matrix")
    if not matrix._HAVE_MATRIX:
        pytest.skip("matrix-nio not installed")
    with pytest.raises(ValueError, match="MATRIX_ALLOWED_USER_IDS"):
        matrix.MatrixChannel(
            handler=_noop, homeserver="https://matrix.org",
            user_id="@me:matrix.org", access_token="tok",
            allowed_user_ids=set(),
        )


# --- sms / whatsapp: per-sender allowlist (Twilio) -------------------------
#
# A valid X-Twilio-Signature only proves Twilio relayed the POST, not that
# the *sender* is authorized -- and a Twilio number is reachable by anyone on
# the PSTN. These channels were the two missed by the first allowlist pass;
# pin the fail-closed behaviour at both construction and the webhook path.

def _have_twilio() -> bool:
    try:
        import fastapi  # noqa: F401
        import twilio  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_twilio(), reason="fastapi+twilio not installed")
def test_sms_requires_allowlist():
    from maverick_channels.sms import SMSChannel
    with pytest.raises(ValueError, match="SMS_ALLOWED_USER_IDS"):
        SMSChannel(
            handler=_noop, account_sid="ACx", auth_token="tok",
            from_number="+15550000", allowed_user_ids=set(),
        )


@pytest.mark.skipif(not _have_twilio(), reason="fastapi+twilio not installed")
def test_whatsapp_requires_allowlist():
    from maverick_channels.whatsapp import WhatsAppChannel
    with pytest.raises(ValueError, match="WHATSAPP_ALLOWED_USER_IDS"):
        WhatsAppChannel(
            handler=_noop, account_sid="ACx", auth_token="tok",
            from_number="whatsapp:+15550000", allowed_user_ids=set(),
        )


@pytest.mark.skipif(not _have_twilio(), reason="fastapi+twilio not installed")
def test_sms_webhook_rejects_unauthorized_sender():
    """End-to-end: a signature-valid POST from a non-allowlisted number is
    refused (403) and never reaches the handler; an allowlisted number runs."""
    from fastapi.testclient import TestClient
    from maverick_channels.sms import SMSChannel

    seen = []

    async def _handler(msg):
        seen.append(msg.user_id)
        return "ran"

    chan = SMSChannel(
        handler=_handler, account_sid="ACx", auth_token="tok",
        from_number="+15550000", allowed_user_ids={"+12025550111"},
    )
    # Isolate the sender-allowlist gate from Twilio signature checking.
    chan._validator.validate = lambda *a, **k: True

    async def _send(_uid, _text):
        return None

    chan.send = _send
    client = TestClient(chan._app)

    def _post(frm):
        return client.post(
            "/webhook/sms",
            data={"From": frm, "Body": "hi", "MessageSid": ""},
        )

    resp = _post("+19998887777")  # stranger
    assert resp.status_code == 403
    assert seen == []

    resp = _post("+12025550111")  # allowlisted owner
    assert resp.status_code == 200
    assert seen == ["+12025550111"]


@pytest.mark.skipif(not _have_twilio(), reason="fastapi+twilio not installed")
def test_whatsapp_webhook_rejects_unauthorized_sender():
    from fastapi.testclient import TestClient
    from maverick_channels.whatsapp import WhatsAppChannel

    seen = []

    async def _handler(msg):
        seen.append(msg.user_id)
        return "ran"

    chan = WhatsAppChannel(
        handler=_handler, account_sid="ACx", auth_token="tok",
        from_number="whatsapp:+15550000",
        allowed_user_ids={"whatsapp:+12025550111"},
    )
    chan._validator.validate = lambda *a, **k: True

    async def _send(_uid, _text):
        return None

    chan.send = _send
    client = TestClient(chan._app)

    def _post(frm):
        return client.post(
            "/webhook/whatsapp",
            data={"From": frm, "Body": "hi", "MessageSid": ""},
        )

    resp = _post("whatsapp:+19998887777")
    assert resp.status_code == 403
    assert seen == []

    resp = _post("whatsapp:+12025550111")
    assert resp.status_code == 200
    assert seen == ["whatsapp:+12025550111"]


# --- voice: per-caller allowlist (launch-hardening) ------------------------

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
