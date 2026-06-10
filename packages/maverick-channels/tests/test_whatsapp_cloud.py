"""WhatsApp Cloud API adapter: verification handshake, HMAC-signed events,
sender allowlist, dedup claim, and outbound Graph calls."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from maverick_channels.whatsapp_cloud import WhatsAppCloudChannel  # noqa: E402

APP_SECRET = "app-secret"
VERIFY_TOKEN = "verify-me"
SENDER = "15551234567"


def _channel(monkeypatch=None, **overrides):
    kw = dict(
        handler=AsyncMock(return_value="the reply"),
        access_token="EAAG-token",
        phone_number_id="1112223334445",
        verify_token=VERIFY_TOKEN,
        app_secret=APP_SECRET,
        allowed_user_ids=[SENDER],
    )
    kw.update(overrides)
    return WhatsAppCloudChannel(**kw)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _event(sender=SENDER, text="hello agent", msg_id="wamid.X1"):
    return {
        "entry": [{"changes": [{"value": {"messages": [
            {"type": "text", "from": sender, "id": msg_id, "text": {"body": text}},
        ]}}]}],
    }


def test_verification_handshake():
    ch = _channel()
    client = TestClient(ch._app)
    r = client.get("/webhook/whatsapp-cloud", params={
        "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "12345",
    })
    assert r.status_code == 200 and r.text == "12345"
    bad = client.get("/webhook/whatsapp-cloud", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x",
    })
    assert bad.status_code == 403


def test_signed_message_drives_handler_and_replies(monkeypatch):
    ch = _channel()
    ch.send = AsyncMock()
    # No dedup DB in tests: claim path is exercised separately.
    monkeypatch.setattr(
        "maverick.world_model.WorldModel",
        MagicMock(side_effect=RuntimeError("no db")),
    )
    client = TestClient(ch._app)
    body = json.dumps(_event()).encode()
    r = client.post("/webhook/whatsapp-cloud", content=body,
                    headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200
    ch.handler.assert_awaited_once()
    msg = ch.handler.await_args.args[0]
    assert msg.user_id == SENDER and msg.text == "hello agent"
    assert msg.channel == "whatsapp_cloud" and msg.message_id == "wamid.X1"
    ch.send.assert_awaited_once_with(SENDER, "the reply")


def test_bad_signature_403():
    ch = _channel()
    client = TestClient(ch._app)
    body = json.dumps(_event()).encode()
    r = client.post("/webhook/whatsapp-cloud", content=body,
                    headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})
    assert r.status_code == 403
    assert not ch.handler.await_count


def test_unlisted_sender_ignored(monkeypatch):
    ch = _channel()
    ch.send = AsyncMock()
    client = TestClient(ch._app)
    body = json.dumps(_event(sender="19998887777")).encode()
    r = client.post("/webhook/whatsapp-cloud", content=body,
                    headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200          # Meta still gets its 200
    assert not ch.handler.await_count    # but nothing ran
    assert not ch.send.await_count


def test_dedup_claim_skips_redelivery(monkeypatch):
    ch = _channel()
    ch.send = AsyncMock()
    wm = MagicMock()
    wm.mark_message_processed.return_value = False  # already claimed
    monkeypatch.setattr("maverick.world_model.WorldModel", MagicMock(return_value=wm))
    client = TestClient(ch._app)
    body = json.dumps(_event()).encode()
    r = client.post("/webhook/whatsapp-cloud", content=body,
                    headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200
    wm.mark_message_processed.assert_called_once_with("whatsapp_cloud", "wamid.X1")
    assert not ch.handler.await_count


def test_send_posts_to_graph(monkeypatch):
    ch = _channel()
    sent = []

    class _Resp:
        status_code = 200
        text = ""

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append((url, headers, json))
            return _Resp()

    import sys
    import types
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=_Client))
    import asyncio
    asyncio.run(ch.send(SENDER, "pong"))
    url, headers, payload = sent[0]
    assert url.endswith("/1112223334445/messages")
    assert headers["Authorization"] == "Bearer EAAG-token"
    assert payload == {"messaging_product": "whatsapp", "to": SENDER,
                       "type": "text", "text": {"body": "pong"}}


def test_long_replies_chunked(monkeypatch):
    ch = _channel()
    sent = []

    class _Resp:
        status_code = 200
        text = ""

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(json["text"]["body"])
            return _Resp()

    import sys
    import types
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=_Client))
    import asyncio
    asyncio.run(ch.send(SENDER, "x" * 9000))
    assert len(sent) == 3 and sum(len(s) for s in sent) == 9000


def test_missing_credentials_raise():
    with pytest.raises(ValueError, match="credentials missing"):
        _channel(app_secret=None, access_token=None)


def test_missing_allowlist_raises(monkeypatch):
    monkeypatch.delenv("WHATSAPP_CLOUD_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(ValueError, match="ALLOWED_USER_IDS"):
        _channel(allowed_user_ids=None)
