"""SMS channel via Twilio.

Same transport pattern as WhatsApp: Twilio webhook -> FastAPI receiver.
Difference is the message format (no `whatsapp:` prefix on numbers).

v0.1.1 fix: now validates X-Twilio-Signature on incoming webhooks.

Config::

    [channels.sms]
    enabled = true
    account_sid = "${TWILIO_ACCOUNT_SID}"
    auth_token  = "${TWILIO_AUTH_TOKEN}"
    from_number = "+14155551234"
    port = 8766

Requires::

    pip install 'maverick-channels[sms]'
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import Channel, IncomingMessage

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


class SMSChannel(Channel):
    name = "sms"

    def __init__(
        self,
        handler,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        port: int = 8766,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi/twilio not installed. Run: pip install 'maverick-channels[sms]'"
            )
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = from_number
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError("Twilio credentials missing for SMS")
        self.port = port
        self._twilio = TwilioClient(self.account_sid, self.auth_token)
        self._validator = RequestValidator(self.auth_token)
        self._app = FastAPI()
        self._app.post("/webhook/sms")(self._handle_webhook)
        self._uvicorn_server = None

    async def _handle_webhook(
        self,
        request: "Request",
        From: str = Form(...),  # noqa: N803
        Body: str = Form(...),  # noqa: N803
        MessageSid: str = Form(""),  # noqa: N803 -- Twilio dedup key
    ):
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        form = await request.form()
        form_dict = {k: str(v) for k, v in form.items()}
        if not self._validator.validate(url, form_dict, signature):
            log.warning("SMS webhook signature invalid; ignoring")
            raise HTTPException(status_code=403, detail="signature invalid")

        # Council finding (Tier 0): Twilio retries non-2xx and slow
        # handlers; without MessageSid dedup the same inbound SMS spawns
        # N goals and burns N API spends. Best-effort dedup -- if the
        # world model isn't reachable here we fall through to processing.
        if MessageSid:
            try:
                from maverick.world_model import DEFAULT_DB, WorldModel
                wm = WorldModel(DEFAULT_DB)
                if not wm.mark_message_processed("sms", MessageSid):
                    log.info("SMS MessageSid %s already processed; skipping", MessageSid)
                    return Response(content="", media_type="text/xml")
            except Exception:  # pragma: no cover
                log.warning("SMS dedup check failed; processing anyway")

        msg = IncomingMessage(user_id=From, text=Body, channel="sms")
        try:
            reply = await self.handler(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            reply = f"⚠ error: {e}"
        await self.send(From, reply)
        return Response(content="", media_type="text/xml")

    async def start(self) -> None:
        import uvicorn
        log.info("SMS channel listening on :%d", self.port)
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
