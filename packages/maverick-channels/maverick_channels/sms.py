"""SMS channel via Twilio.

Same transport pattern as WhatsApp: Twilio webhook -> FastAPI receiver.
Difference is the message format (no `whatsapp:` prefix on numbers).

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
    from fastapi import FastAPI, Form, Response
    from twilio.rest import Client as TwilioClient
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = Form = Response = TwilioClient = None  # type: ignore


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
        self._app = FastAPI()
        self._app.post("/webhook/sms")(self._handle_webhook)

    async def _handle_webhook(self, From: str = Form(...), Body: str = Form(...)):  # noqa: N803
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
        server = uvicorn.Server(config)
        await server.serve()

    async def send(self, user_id: str, text: str) -> None:
        import asyncio
        await asyncio.to_thread(
            self._twilio.messages.create,
            body=text,
            from_=self.from_number,
            to=user_id,
        )

    async def stop(self) -> None:
        pass
