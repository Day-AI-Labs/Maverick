"""WhatsApp channel via Twilio Business API.

Scaffold. WhatsApp requires:
  - A public HTTPS endpoint (Twilio sends webhooks to your URL)
  - A Twilio account with WhatsApp Sandbox or approved sender
  - DNS / TLS termination (Caddy or similar)

This class provides the runtime; you must expose the FastAPI app at a
public URL and configure it in Twilio. For VPS deployments, the
included Caddyfile already proxies localhost:8765.

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


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(
        self,
        handler,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        port: int = 8765,
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
        self.port = port
        self._twilio = TwilioClient(self.account_sid, self.auth_token)
        self._app = FastAPI()
        self._app.post("/webhook/whatsapp")(self._handle_webhook)

    async def _handle_webhook(self, From: str = Form(...), Body: str = Form(...)):  # noqa: N803
        msg = IncomingMessage(user_id=From, text=Body, channel="whatsapp")
        try:
            reply = await self.handler(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            reply = f"⚠ error: {e}"
        await self.send(From, reply)
        return Response(content="", media_type="text/xml")

    async def start(self) -> None:
        import uvicorn
        log.info("WhatsApp channel listening on :%d", self.port)
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
