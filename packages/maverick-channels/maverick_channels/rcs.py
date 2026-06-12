"""RCS channel via Google's RCS Business Messaging (RBM) API.

Honesty first: RBM is not self-serve. Sending RCS as a business requires a
**Google-approved RCS agent** (per-region carrier/Google launch approval)
and a GCP **service account** with the RBM API enabled. This adapter speaks
the RBM REST surface (rcsbusinessmessaging.googleapis.com) for deployments
that already have one; it cannot conjure an agent for you.

Inbound contract (RBM webhook):
  - Google POSTs message events to the configured webhook URL. Events
    arrive either as a Pub/Sub-style push envelope ``{"message": {"data":
    "<base64 JSON>"}}`` or as the direct user-event JSON; both are
    accepted. The decoded user event carries ``senderPhoneNumber``,
    ``messageId``, and one payload field (``text``, ``suggestionResponse``,
    ``userFile``, ...). Only plain ``text`` events are dispatched; status
    receipts and rich-card responses are acked and dropped.
  - Authenticity: requests must present the agent's **client token** (the
    value Google echoes back from webhook setup) in a ``clientToken`` query
    param or header — compared constant-time, fail-closed (403). Assumption,
    documented: RBM does not sign deliveries the way Meta does, so register
    the webhook URL with ``?clientToken=...`` appended.
  - Webhook **validation handshake**: at registration Google POSTs
    ``{"clientToken": ..., "secret": ...}`` and expects ``{"secret":
    <same>}`` echoed back iff the token is ours. A GET mirror of the echo
    exists for manual smoke checks.

Security model mirrors whatsapp_cloud: the token only proves the caller
knows the webhook secret; the *sender* (E.164 MSISDN, with leading ``+``)
must be on the allowlist (default-deny), and ``messageId`` is claimed
atomically before processing so Google's redeliveries can't double-run a
goal.

Outbound: ``POST /v1/phones/{msisdn}/agentMessages`` with the agent id and
a client-generated ``messageId``, authorized by an OAuth2 Bearer token
minted from the service account (rcsbusinessmessaging scope) via
google-auth. Credentials are cached and refreshed only when expired.

Config::

    [channels.rcs]
    enabled = true
    agent_id = "my_rbm_agent"
    service_account_json = "/etc/maverick/rbm-sa.json"
    webhook_token = "${RCS_WEBHOOK_TOKEN}"
    allowed_user_ids = ["+14155551234"]   # E.164 MSISDNs
    port = 8768

Requires::

    pip install 'maverick-channels[rcs]'   # fastapi + httpx + google-auth
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import uuid

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, Request
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = HTTPException = Request = None  # type: ignore

RBM_BASE = "https://rcsbusinessmessaging.googleapis.com"
RBM_SCOPE = "https://www.googleapis.com/auth/rcsbusinessmessaging"
TEXT_LIMIT = 2000  # RBM text content cap
HANDSHAKE_BODY_LIMIT = 4096  # body-token registration payload cap


class RcsChannel(Channel):
    name = "rcs"

    def __init__(
        self,
        handler,
        agent_id: str | None = None,
        service_account_json: str | None = None,
        webhook_token: str | None = None,
        allowed_user_ids=None,
        port: int = 8768,
        bind_host: str | None = None,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi not installed. Run: pip install 'maverick-channels[rcs]'"
            )
        self.agent_id = agent_id or os.environ.get("RCS_AGENT_ID")
        self.service_account_json = (
            service_account_json or os.environ.get("RCS_SERVICE_ACCOUNT_JSON")
        )
        self.webhook_token = webhook_token or os.environ.get("RCS_WEBHOOK_TOKEN")
        if not all([self.agent_id, self.service_account_json, self.webhook_token]):
            raise ValueError(
                "RCS credentials missing. Set agent_id, service_account_json, "
                "and webhook_token ([channels.rcs] or RCS_* env)."
            )
        # The client token only proves the caller knows the webhook secret;
        # gate on the SENDER (E.164 MSISDN, leading '+').
        self.allowed_user_ids = normalize_allowlist(allowed_user_ids, "RCS_ALLOWED_USER_IDS")
        if not self.allowed_user_ids:
            raise ValueError(
                "Set RCS_ALLOWED_USER_IDS to restrict who can drive the agent"
            )
        self.port = port
        self.bind_host = bind_host or os.environ.get("RCS_BIND_HOST", "127.0.0.1")
        self._credentials = None  # cached google-auth credentials (lazy)
        self._app = FastAPI()
        self._app.get("/webhook/rcs")(self._handle_verify)
        self._app.post("/webhook/rcs")(self._handle_webhook)
        self._uvicorn_server = None

    # -- client-token verification ---------------------------------------------

    @staticmethod
    def _request_token(request: Request) -> str:
        return (
            request.query_params.get("clientToken")
            or request.headers.get("clientToken")
            or ""
        )

    def _token_ok(self, request: Request) -> bool:
        """Constant-time check of the client token Google echoes back.
        Accepted from the ``clientToken`` query param or header (RBM does not
        document a delivery-time signature, so deployments register the
        webhook URL with ``?clientToken=...`` appended). Fail-closed."""
        return hmac.compare_digest(self._request_token(request), self.webhook_token or "")

    async def _handle_verify(self, request: Request):
        """Webhook URL verification (GET).

        RBM's documented validation is the POST ``{clientToken, secret}``
        handshake (handled in ``_handle_webhook``); this GET mirrors the
        echo for integrations and manual smoke checks that probe the URL
        with ``?clientToken=...&secret=...``."""
        if not self._token_ok(request):
            raise HTTPException(status_code=403, detail="client token invalid")
        return {"secret": request.query_params.get("secret", "")}

    # -- inbound event delivery (POST) -------------------------------------------

    @staticmethod
    def _decode_event(payload: dict) -> dict:
        """Unwrap the Pub/Sub-style push envelope (``{"message": {"data":
        base64(JSON)}}``) RBM webhooks deliver; direct user-event JSON
        passes through unchanged."""
        msg = payload.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("data"), str):
            try:
                event = json.loads(base64.b64decode(msg["data"]))
            except (ValueError, TypeError):
                return {}
            return event if isinstance(event, dict) else {}
        return payload

    @staticmethod
    def _json_object(raw: bytes) -> dict:
        try:
            payload = json.loads(raw)
        except (RecursionError, ValueError) as e:
            raise HTTPException(status_code=400, detail="bad JSON") from e
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="bad JSON")
        return payload

    async def _small_handshake_payload(self, request: Request) -> dict:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > HANDSHAKE_BODY_LIMIT:
                    raise HTTPException(status_code=413, detail="body too large")
            except ValueError as e:
                raise HTTPException(status_code=400, detail="bad Content-Length") from e

        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > HANDSHAKE_BODY_LIMIT:
                raise HTTPException(status_code=413, detail="body too large")
        return self._json_object(bytes(body))

    async def _handle_webhook(self, request: Request):
        # Normal event delivery must authenticate from request metadata before
        # reading the body, so unauthenticated callers cannot force large JSON
        # buffering/parsing. The only body-token exception is RBM's registration
        # handshake, which is read through a small capped path below.
        if not self._token_ok(request):
            if self._request_token(request):
                log.warning("RCS webhook client token invalid; ignoring")
                raise HTTPException(status_code=403, detail="client token invalid")

            payload = await self._small_handshake_payload(request)
            if "secret" in payload and "clientToken" in payload:
                if not hmac.compare_digest(
                    str(payload.get("clientToken") or ""), self.webhook_token or "",
                ):
                    raise HTTPException(status_code=403, detail="client token invalid")
                return {"secret": payload["secret"]}

            log.warning("RCS webhook client token invalid; ignoring")
            raise HTTPException(status_code=403, detail="client token invalid")

        try:
            payload = await request.json()
        except (RecursionError, ValueError) as e:
            raise HTTPException(status_code=400, detail="bad JSON") from e
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="bad JSON")

        event = self._decode_event(payload)
        sender = str(event.get("senderPhoneNumber") or "")
        text = event.get("text")
        msg_id = str(event.get("messageId") or "")
        if not sender or not isinstance(text, str) or not text:
            # Not an inbound text (delivery/read receipt, suggestionResponse,
            # file, ...): ack so Google stops retrying, act on nothing.
            return {"status": "ignored"}
        if not is_allowed(sender, self.allowed_user_ids):
            log.warning("unauthorized rcs access: from=%s", sender)
            return {"status": "ok"}

        # Claim the messageId atomically BEFORE processing so Google's
        # redelivery can't double-run a goal (same pattern as whatsapp_cloud).
        wm = None
        if msg_id:
            try:
                from maverick.world_model import DEFAULT_DB, WorldModel
                wm = WorldModel(DEFAULT_DB)
                if not wm.mark_message_processed("rcs", msg_id):
                    log.info("rcs message %s already claimed; skipping", msg_id)
                    return {"status": "ok"}
            except Exception:  # pragma: no cover
                log.warning("rcs dedup claim failed; processing anyway")
                wm = None

        incoming = IncomingMessage(
            user_id=sender, text=text, channel="rcs", message_id=msg_id or None,
        )
        try:
            reply = await self.handler(incoming)
        except Exception as e:
            log.exception("handler error")
            if wm is not None and msg_id:
                try:
                    wm.release_processed_message("rcs", msg_id)
                except Exception:  # pragma: no cover
                    log.warning("rcs dedup release failed")
            reply = f"⚠ error: {e}"
        if reply:
            await self.send(sender, reply)
        return {"status": "ok"}

    # -- outbound ------------------------------------------------------------

    def _bearer_token(self) -> str:
        """OAuth2 token for the RBM scope, minted from the service account.

        google-auth is lazy-imported so the webhook surface (and tests) work
        without it. Credentials are cached on the instance; ``refresh`` (a
        blocking HTTP call, ~once an hour) runs only when ``valid`` is
        False."""
        try:
            import google.auth
            import google.auth.transport.requests
        except ImportError as e:
            raise ImportError(
                "google-auth not installed. Run: pip install 'maverick-channels[rcs]'"
            ) from e
        if self._credentials is None:
            self._credentials, _ = google.auth.load_credentials_from_file(
                self.service_account_json, scopes=[RBM_SCOPE],
            )
        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())
        return self._credentials.token

    async def send(self, user_id: str, text: str) -> None:
        import httpx
        token = self._bearer_token()
        url = f"{RBM_BASE}/v1/phones/{user_id}/agentMessages"
        for chunk in [text[i:i + TEXT_LIMIT] for i in range(0, max(len(text), 1), TEXT_LIMIT)]:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    url,
                    # messageId is the agent-generated dedup id RBM requires
                    # on every create call.
                    params={"agentId": self.agent_id, "messageId": str(uuid.uuid4())},
                    headers={"Authorization": f"Bearer {token}"},
                    json={"contentMessage": {"text": chunk}},
                )
                if r.status_code >= 400:
                    log.warning("rcs send failed (%s): %s", r.status_code, r.text[:200])

    async def start(self) -> None:
        import uvicorn
        config = uvicorn.Config(
            self._app, host=self.bind_host, port=self.port, log_level="warning",
        )
        self._uvicorn_server = uvicorn.Server(config)
        log.info("RCS webhook on %s:%d", self.bind_host, self.port)
        await self._uvicorn_server.serve()

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
