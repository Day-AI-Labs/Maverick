"""Voice channel (Vapi / Retell / Bland).

Tenth channel adapter. A voice provider exposes a REST + webhook surface
that matches Maverick's existing IncomingMessage / handler contract —
when the user speaks, the provider transcribes (Deepgram / Whisper /
ElevenLabs) and POSTs the transcript to our webhook; we run the swarm;
the reply goes back via the provider's TTS.

Config in ~/.maverick/config.toml::

    [channels.voice]
    enabled       = true
    provider      = "vapi"            # vapi | retell | bland
    api_key       = "${VAPI_API_KEY}" # RETELL_API_KEY / BLAND_API_KEY for those
    phone_number  = "+14155551234"
    port          = 8770
    assistant_id  = "<provider assistant/agent id>"

The TTS / STT happens on the provider's side; Maverick is just the
"reasoning brain" the provider calls when the user pauses. This keeps
the adapter thin.

Provider support:
  - Inbound webhook parsing is Vapi-shaped today (the swarm-facing
    transcript handler). Retell/Bland inbound is not yet wired.
  - Outbound ``send()`` (proactive calls) is provider-dispatched and
    supports vapi, retell, and bland. The Vapi contract is live-tested;
    the Retell and Bland contracts are wired from each vendor's public
    API docs and should be smoke-tested with real credentials before
    you depend on them.

Requires::

    pip install 'maverick-channels[voice]'
"""
from __future__ import annotations

import hmac
import logging
import os

from .base import (
    Channel,
    IncomingMessage,
    add_webhook_body_limit,
    is_allowed,
    normalize_allowlist,
)

log = logging.getLogger(__name__)

# Which env var holds the API key for each provider. Used both to resolve
# the key at construction and by the installer wizard to prompt for the
# right secret.
PROVIDER_KEY_ENV = {
    "vapi": "VAPI_API_KEY",
    "retell": "RETELL_API_KEY",
    "bland": "BLAND_API_KEY",
}


try:
    import httpx
    from fastapi import FastAPI, Header, HTTPException, Request, Response
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
        api_key: str | None = None,
        phone_number: str | None = None,
        port: int = 8770,
        assistant_id: str | None = None,
        provider: str = "vapi",
        webhook_token: str | None = None,
        allowed_callers=None,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi/httpx not installed. Run: "
                "pip install 'maverick-channels[voice]'"
            )
        self.provider = provider
        # Each provider keeps its key in its own env var; fall back to the
        # Vapi var for an unknown provider so the error message is sensible.
        key_env = PROVIDER_KEY_ENV.get(provider, "VAPI_API_KEY")
        self.api_key = api_key or os.environ.get(key_env)
        if not self.api_key:
            raise ValueError(f"voice channel: {key_env} not set")
        self.phone_number = phone_number
        self.port = port
        self.assistant_id = assistant_id
        self.webhook_token = webhook_token or os.environ.get("VAPI_WEBHOOK_TOKEN")
        # Optional per-caller allowlist (by phone number). The webhook bearer
        # + loopback bind are the primary gate; when this is set we also
        # restrict WHICH caller number may drive the agent. Empty = allow any
        # authenticated caller (bearer still required).
        self.allowed_callers = normalize_allowlist(
            allowed_callers, "VOICE_ALLOWED_CALLERS",
        )

        self._app = FastAPI()
        add_webhook_body_limit(self._app)
        self._app.post("/webhook/voice")(self._handle_webhook)
        self._uvicorn_server = None

    def _check_webhook_auth(self, authorization: str | None) -> bool:
        """Require bearer auth for inbound webhook events."""
        expected = self.webhook_token
        if not expected:
            return False
        if not authorization or not authorization.startswith("Bearer "):
            return False
        given = authorization[len("Bearer "):].strip()
        return hmac.compare_digest(expected.encode("utf-8"), given.encode("utf-8"))

    async def _handle_webhook(
        self,
        request: Request,
        authorization: str | None = Header(None),
    ):
        if not self._check_webhook_auth(authorization):
            raise HTTPException(status_code=401, detail="invalid webhook bearer")

        # Vapi sends webhook events with a `type` field: "function-call",
        # "end-of-call-report", "transcript", "speech-update", etc.
        # We only care about transcripts that resolve into agent turns.
        try:
            payload = await request.json()
        except Exception:
            # Malformed / non-JSON body: 400, don't 500 (which Vapi
            # retries, amplifying load).
            raise HTTPException(status_code=400, detail="invalid JSON body") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="expected a JSON object")
        # Coerce nested fields to dicts: a body like {"message": "x"} would make
        # the chained .get() raise AttributeError -> unhandled 500 (and Vapi
        # retries non-2xx, amplifying load).
        msg_data = payload.get("message")
        if not isinstance(msg_data, dict):
            msg_data = {}
        ev_type = msg_data.get("type", "")

        if ev_type == "transcript":
            transcript = msg_data.get("transcript", "")
            role = msg_data.get("role", "user")
            if role != "user" or not transcript:
                return Response(content="{}", media_type="application/json")
            call = payload.get("call")
            call = call if isinstance(call, dict) else {}
            customer = call.get("customer")
            customer = customer if isinstance(customer, dict) else {}
            user_id = (
                customer.get("number")
                or call.get("id")
                or "voice-unknown"
            )
            # Enforce the per-caller allowlist when one is configured.
            if self.allowed_callers and not is_allowed(str(user_id), self.allowed_callers):
                log.warning("unauthorized voice caller: %s", user_id)
                return {"response": "Sorry, this number isn't authorized to use this assistant."}
            msg = IncomingMessage(
                user_id=str(user_id),
                text=transcript,
                channel="voice",
                raw=payload,
            )
            try:
                reply = await self.dispatch_text(msg)
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

    def _outbound_request(self, user_id: str, text: str) -> dict:
        """Build the provider-specific outbound-call HTTP request.

        Returns a dict with ``url`` / ``headers`` / ``json``. Contracts
        come from each vendor's public API docs — Vapi is live-tested;
        Retell and Bland are wired from docs and want a real smoke test
        before you rely on them. Raises ValueError for an unknown
        provider so ``send()`` can fail soft.
        """
        if self.provider == "vapi":
            return {
                "url": "https://api.vapi.ai/call",
                "headers": {"Authorization": f"Bearer {self.api_key}"},
                "json": {
                    "assistantId": self.assistant_id,
                    "customer": {"number": user_id},
                    "phoneNumber": {"number": self.phone_number},
                    "assistantOverrides": {"firstMessage": text},
                },
            }
        if self.provider == "retell":
            # https://docs.retellai.com/api-references/create-phone-call
            return {
                "url": "https://api.retellai.com/v2/create-phone-call",
                "headers": {"Authorization": f"Bearer {self.api_key}"},
                "json": {
                    "from_number": self.phone_number,
                    "to_number": user_id,
                    "override_agent_id": self.assistant_id,
                    "retell_llm_dynamic_variables": {"first_message": text},
                },
            }
        if self.provider == "bland":
            # https://docs.bland.ai/api-v1/post/calls
            return {
                "url": "https://api.bland.ai/v1/calls",
                "headers": {"authorization": self.api_key or ""},
                "json": {
                    "phone_number": user_id,
                    "from": self.phone_number,
                    "task": text,
                    "pathway_id": self.assistant_id,
                },
            }
        raise ValueError(f"unsupported voice provider {self.provider!r}")

    async def send(self, user_id: str, text: str) -> None:
        """Outbound: place a call to `user_id` (a phone number) via the
        configured provider and have the assistant deliver `text`."""
        if not self.assistant_id:
            log.warning("voice send: no assistant_id configured; skipping outbound")
            return
        try:
            req = self._outbound_request(user_id, text)
        except ValueError as e:
            log.warning("voice send: %s", e)
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                req["url"], headers=req["headers"], json=req["json"],
            )
            if r.status_code >= 300:
                log.warning("voice outbound call failed (%s): %s %s",
                            self.provider, r.status_code, r.text[:200])

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
