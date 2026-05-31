"""WhatsApp channel via Twilio Business API.

Requires:
  - Public HTTPS endpoint (Twilio sends webhooks to your URL)
  - Twilio account with WhatsApp Sandbox or approved sender
  - DNS / TLS termination (Caddy or similar)

This class provides the runtime; you must expose the FastAPI app at a
public URL and configure it in Twilio. The included Caddyfile in
deploy/vps/ shows the reverse-proxy pattern.

v0.1.1 fix: webhook now validates Twilio's X-Twilio-Signature so
random internet POSTs can't trigger agent runs (which would cost the
user real money for outbound Twilio replies).

Config::

    [channels.whatsapp]
    enabled = true
    account_sid = "${TWILIO_ACCOUNT_SID}"
    auth_token  = "${TWILIO_AUTH_TOKEN}"
    from_number = "whatsapp:+14155238886"
    port = 8765

Requires::

    pip install 'maverick-channels[whatsapp]'
"""
from __future__ import annotations

import logging
import os

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, Form, HTTPException, Request, Response
    from twilio.request_validator import RequestValidator
    from twilio.rest import Client as TwilioClient
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = Form = HTTPException = Request = Response = None  # type: ignore
    RequestValidator = TwilioClient = None  # type: ignore


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(
        self,
        handler,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        port: int = 8765,
        allowed_user_ids=None,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi/twilio not installed. "
                "Run: pip install 'maverick-channels[whatsapp]'"
            )
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = from_number
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError(
                "Twilio credentials missing. Set TWILIO_ACCOUNT_SID, "
                "TWILIO_AUTH_TOKEN, and from_number in config."
            )
        # The Twilio signature only proves Twilio relayed the message, not
        # that the *sender* is authorized. Require a per-sender allowlist
        # (default-deny via base.is_allowed). Twilio delivers WhatsApp
        # senders with the "whatsapp:" prefix, so list them as e.g.
        # "whatsapp:+14155551234".
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "WHATSAPP_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError(
                "Set WHATSAPP_ALLOWED_USER_IDS to restrict who can drive the agent"
            )
        self.port = port
        self._twilio = TwilioClient(self.account_sid, self.auth_token)
        self._validator = RequestValidator(self.auth_token)
        self._app = FastAPI()
        self._app.post("/webhook/whatsapp")(self._handle_webhook)
        self._uvicorn_server = None

    async def _handle_webhook(
        self,
        request: Request,
        From: str = Form(...),  # noqa: N803
        Body: str = Form(...),  # noqa: N803
        MessageSid: str = Form(""),  # noqa: N803 -- Twilio dedup key
    ):
        # Validate Twilio signature so random POSTs can't spoof inbound.
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        form = await request.form()
        form_dict = {k: str(v) for k, v in form.items()}
        if not self._validator.validate(url, form_dict, signature):
            log.warning("WhatsApp webhook signature invalid; ignoring")
            raise HTTPException(status_code=403, detail="signature invalid")

        # A valid signature only proves Twilio relayed this; gate on the
        # actual sender before spending any budget (default-deny).
        if not is_allowed(From, self.allowed_user_ids):
            log.warning("unauthorized whatsapp access: from=%s", From)
            raise HTTPException(status_code=403, detail="sender not allowed")

        # Twilio retries; lookup-then-mark so a handler crash doesn't
        # permanently lose the message (Twilio retry re-processes it).
        wm = None
        if MessageSid:
            try:
                from maverick.world_model import DEFAULT_DB, WorldModel
                wm = WorldModel(DEFAULT_DB)
                if wm.is_processed_message("whatsapp", MessageSid):
                    log.info("WhatsApp MessageSid %s already processed; skipping", MessageSid)
                    return Response(content="", media_type="text/xml")
            except Exception:  # pragma: no cover
                log.warning("WhatsApp dedup check failed; processing anyway")
                wm = None

        msg = IncomingMessage(user_id=From, text=Body, channel="whatsapp")
        try:
            reply = await self.handler(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            reply = f"⚠ error: {e}"
            await self.send(From, reply)
            return Response(content="", media_type="text/xml")
        await self.send(From, reply)
        if wm is not None and MessageSid:
            try:
                wm.mark_message_processed("whatsapp", MessageSid)
            except Exception:  # pragma: no cover
                log.warning("WhatsApp dedup mark failed (message processed OK)")
        return Response(content="", media_type="text/xml")

    async def start(self) -> None:
        import uvicorn
        log.info("WhatsApp channel listening on :%d", self.port)
        config = uvicorn.Config(
            self._app, host="0.0.0.0", port=self.port, log_level="info"  # noqa: S104
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def send(self, user_id: str, text: str) -> None:
        import asyncio
        await asyncio.to_thread(
            self._twilio.messages.create,
            body=text,
            from_=self.from_number,
            to=user_id,
        )

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
