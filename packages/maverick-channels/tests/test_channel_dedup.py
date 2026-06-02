"""Inbound channels must dedup a retried webhook ATOMICALLY (issue #473).

Twilio resends the same MessageSid within ~15s when a handler is slow. The old
code did is_processed_message() (check) -> handler (slow goal) -> mark (after),
so two retries racing a slow handler both passed the check and ran the goal
twice -- a double-spend (duplicate API cost). The handler now CLAIMS the
MessageSid up front via mark_message_processed()'s atomic return value, so a
racing retry is a no-op.
"""
from __future__ import annotations

import pytest


def _have_twilio() -> bool:
    try:
        import fastapi  # noqa: F401
        import twilio  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_twilio(), reason="fastapi+twilio not installed")
@pytest.mark.parametrize("channel,module,path,frm,sid", [
    ("sms", "maverick_channels.sms", "/webhook/sms",
     "+12025550111", "SMdup"),
    ("whatsapp", "maverick_channels.whatsapp", "/webhook/whatsapp",
     "whatsapp:+12025550111", "WAdup"),
])
def test_webhook_claims_sid_before_running_handler(
    tmp_path, monkeypatch, channel, module, path, frm, sid,
):
    """The fix: the SID is claimed BEFORE the handler runs, so a Twilio retry
    that races a still-running handler is deduped. This discriminates from the
    old check-then-mark, where the SID stayed unmarked until after the handler
    (the double-spend window)."""
    import importlib

    import maverick.world_model as wm_mod
    from fastapi.testclient import TestClient
    monkeypatch.setattr(wm_mod, "DEFAULT_DB", tmp_path / "world.db")

    mod = importlib.import_module(module)
    Channel = mod.SMSChannel if channel == "sms" else mod.WhatsAppChannel

    ran: list[str] = []
    claimed_when_handler_ran: list[bool] = []

    async def _handler(msg):
        # A concurrent Twilio retry arriving *now* must already see the SID as
        # claimed -- i.e. the claim happened before us. (Old code: still False.)
        wm = wm_mod.WorldModel(wm_mod.DEFAULT_DB)
        claimed_when_handler_ran.append(wm.is_processed_message(channel, sid))
        ran.append(msg.text)
        return "ok"

    chan = Channel(
        handler=_handler, account_sid="ACx", auth_token="tok",
        from_number=("whatsapp:+15550000" if channel == "whatsapp" else "+15550000"),
        allowed_user_ids={frm},
    )
    chan._validator.validate = lambda *a, **k: True  # bypass Twilio signature

    async def _send(_uid, _text):
        return None
    chan.send = _send

    client = TestClient(chan._app)

    def _post():
        return client.post(path, data={"From": frm, "Body": "hi", "MessageSid": sid})

    assert _post().status_code == 200
    assert ran == ["hi"]
    # Claimed before the handler ran -> a racing retry would no-op.
    assert claimed_when_handler_ran == [True]

    # An actual Twilio resend of the same SID is now a no-op (no second run).
    assert _post().status_code == 200
    assert ran == ["hi"]
