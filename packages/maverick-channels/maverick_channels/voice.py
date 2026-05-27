"""Voice channel via Vapi (2026 leader: 62M calls/mo).

Tenth channel adapter. Vapi exposes a REST + webhook surface that
matches Maverick's existing IncomingMessage / handler contract — when
the user speaks, Vapi transcribes via Deepgram / Whisper / ElevenLabs
and POSTs the transcript to our webhook; we run the swarm; the reply
goes back via Vapi's TTS.

Config in ~/.maverick/config.toml::

    [channels.voice]
    enabled       = true
    provider      = "vapi"
    api_key       = "${VAPI_API_KEY}"
    phone_number  = "+14155551234"
    port          = 8770
    assistant_id  = "<your-vapi-assistant-id>"

The actual TTS / STT happens on Vapi's side; Maverick is just the
"reasoning brain" that Vapi calls when the user pauses. This keeps
the channel adapter thin and provider-swappable (Retell, Bland AI,
ElevenLabs Conversational AI all expose similar webhook contracts).

Requires::

    pip install 'maverick-channels[voice]'
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)


try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response
    import httpx
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = Header = HTTPException = Request = Response = httpx = None  # type: ignore


class VoiceChannel(Channel):
    """Vapi-backed voice channel.

    Lifecycle:
      - start(): bring up a FastAPI server on `port` exposing
        `/webhook/voice` for Vapi's events.
      - on each `function-call` / `transcript` event, dispatch to
        Maverick's handler and return a `result` Vapi will TTS.
      - send(): for proactive notifications (e.g., goal completed
        while user was on another call) we POST to Vapi's outbound
        call endpoint with the assistant_id.
    """

    name = "voice"

    def __init__(
        self,
        handler,
        api_key: Optional[str] = None,
        phone_number: Optional[str] = None,
        port: int = 8770,
        assistant_id: Optional[str] = None,
        provider: str = "vapi",
        webhook_token: Optional[str] = None,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi/httpx not installed. Run: "
                "pip install 'maverick-channels[voice]'"
            )
        self.api_key = api_key or os.environ.get("VAPI_API_KEY")
        if not self.api_key:
            raise ValueError("voice channel: VAPI_API_KEY not set")
        self.phone_number = phone_number
        self.port = port
        self.assistant_id = assistant_id
        self.provider = provider
        self.webhook_token = webhook_token or os.environ.get("VAPI_WEBHOOK_TOKEN")

        self._app = FastAPI()
        self._app.post("/webhook/voice")(self._handle_webhook)
        self._uvicorn_server = None

    def _check_webhook_auth(self, authorization: Optional[str]) -> bool:
        """Require bearer auth for inbound webhook events."""
        expected = self.webhook_token
        if not expected:
            return False
        if not authorization or not authorization.startswith("Bearer "):
            return False
        given = authorization[len("Bearer "):].strip()
        return hmac.compare_digest(expected, given)

    async def _handle_webhook(
        self,
        request: "Request",
        authorization: Optional[str] = Header(None),
    ):
        if not self._check_webhook_auth(authorization):
            raise HTTPException(status_code=401, detail="invalid webhook bearer")

        # Vapi sends webhook events with a `type` field: "function-call",
        # "end-of-call-report", "transcript", "speech-update", etc.
        # We only care about transcripts that resolve into agent turns.
        payload = await request.json()
        ev_type = payload.get("message", {}).get("type", "")

        if ev_type == "transcript":
            msg_data = payload.get("message", {})
            transcript = msg_data.get("transcript", "")
            role = msg_data.get("role", "user")
            if role != "user" or not transcript:
                return Response(content="{}", media_type="application/json")
            call = payload.get("call", {}) or {}
            user_id = (
                call.get("customer", {}).get("number")
                or call.get("id")
                or "voice-unknown"
            )
            msg = IncomingMessage(
                user_id=str(user_id),
                text=transcript,
                channel="voice",
                raw=payload,
            )
            try:
                reply = await self.handler(msg)
            except Exception as e:  # pragma: no cover
                log.exception("voice handler error")
                reply = f"Sorry, I ran into an error: {e}"
            return {"response": reply}

        # Other events (end-of-call, status updates) are informational.
        # Acknowledge with empty body so Vapi doesn't retry.
        return Response(content="{}", media_type="application/json")

    async def start(self) -> None:
        import uvicorn
        log.info("Voice channel listening on :%d (provider=%s)",
                 self.port, self.provider)
        config = uvicorn.Config(
            self._app, host="127.0.0.1", port=self.port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def send(self, user_id: str, text: str) -> None:
        """Outbound: place a Vapi call to `user_id` (a phone number)
        and have the assistant deliver `text`."""
        if not self.assistant_id:
            log.warning("voice send: no assistant_id configured; skipping outbound")
            return
        if self.provider != "vapi":
            log.warning("voice send: provider %r not yet implemented", self.provider)
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.vapi.ai/call",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "assistantId": self.assistant_id,
                    "customer": {"number": user_id},
                    "phoneNumber": {"number": self.phone_number},
                    "assistantOverrides": {
                        "firstMessage": text,
                    },
                },
            )
            if r.status_code >= 300:
                log.warning("voice outbound call failed: %s %s",
                            r.status_code, r.text[:200])

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
