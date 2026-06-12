"""WhatsApp channel via Meta's Cloud API (roadmap: "WhatsApp Cloud API rewrite").

The original adapter (``whatsapp.py``) rides Twilio's Business API — an extra
vendor, extra cost-per-message, and Twilio-shaped webhooks. This adapter
speaks **Meta's WhatsApp Cloud API directly** (graph.facebook.com): free
service tier, first-party webhooks, no middleman. The Twilio adapter stays
for deployments already on it; new deployments should start here.

Webhook contract (Meta):
  - **GET** verification handshake: ``hub.mode=subscribe`` +
    ``hub.verify_token`` must equal the configured token → echo
    ``hub.challenge`` as plain text.
  - **POST** events signed with ``X-Hub-Signature-256`` =
    ``sha256=`` + HMAC-SHA256(app_secret, raw body) — verified
    constant-time, fail-closed.

Security model mirrors the Twilio adapter: the signature only proves Meta
relayed the event; the *sender* (wa_id) must be on the allowlist
(default-deny), and message ids are claimed atomically before processing so
Meta's redeliveries can't double-run (and double-bill) a goal.

Config::

    [channels.whatsapp_cloud]
    enabled = true
    access_token    = "${WHATSAPP_CLOUD_ACCESS_TOKEN}"
    phone_number_id = "123456789012345"
    verify_token    = "${WHATSAPP_CLOUD_VERIFY_TOKEN}"
    app_secret      = "${WHATSAPP_CLOUD_APP_SECRET}"
    allowed_user_ids = ["15551234567"]
    port = 8767

Requires::

    pip install 'maverick-channels[whatsapp-cloud]'   # fastapi + httpx
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, Request, Response
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = HTTPException = Request = Response = None  # type: ignore

GRAPH_BASE = "https://graph.facebook.com"
API_VERSION = "v19.0"


class WhatsAppCloudChannel(Channel):
    name = "whatsapp_cloud"

    def __init__(
        self,
        handler,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        verify_token: str | None = None,
        app_secret: str | None = None,
        port: int = 8767,
        allowed_user_ids=None,
        bind_host: str | None = None,
        api_version: str = API_VERSION,
    ):
        super().__init__(handler)
        if not _HAVE_DEPS:
            raise ImportError(
                "fastapi not installed. Run: pip install 'maverick-channels[whatsapp-cloud]'"
            )
        self.access_token = access_token or os.environ.get("WHATSAPP_CLOUD_ACCESS_TOKEN")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_CLOUD_PHONE_NUMBER_ID")
        self.verify_token = verify_token or os.environ.get("WHATSAPP_CLOUD_VERIFY_TOKEN")
        self.app_secret = app_secret or os.environ.get("WHATSAPP_CLOUD_APP_SECRET")
        if not all([self.access_token, self.phone_number_id, self.verify_token, self.app_secret]):
            raise ValueError(
                "WhatsApp Cloud credentials missing. Set access_token, "
                "phone_number_id, verify_token, and app_secret "
                "([channels.whatsapp_cloud] or WHATSAPP_CLOUD_* env)."
            )
        # The HMAC only proves Meta relayed the event; gate on the SENDER.
        # Cloud API wa_ids are bare digits (no 'whatsapp:' prefix).
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "WHATSAPP_CLOUD_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError(
                "Set WHATSAPP_CLOUD_ALLOWED_USER_IDS to restrict who can drive the agent"
            )
        self.port = port
        self.bind_host = bind_host or os.environ.get("WHATSAPP_CLOUD_BIND_HOST", "127.0.0.1")
        self.api_version = api_version
        self._app = FastAPI()
        self._app.get("/webhook/whatsapp-cloud")(self._handle_verify)
        self._app.post("/webhook/whatsapp-cloud")(self._handle_webhook)
        self._uvicorn_server = None

    # -- Meta webhook verification handshake (GET) ---------------------------

    @staticmethod
    def _constant_time_text_equal(left: str, right: str) -> bool:
        try:
            left_bytes = left.encode("utf-8")
            right_bytes = right.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(left_bytes, right_bytes)

    async def _handle_verify(self, request: Request):
        params = request.query_params
        if (params.get("hub.mode") == "subscribe"
                and self._constant_time_text_equal(
                    params.get("hub.verify_token", ""),
                    self.verify_token or "",
                )):
            return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
        raise HTTPException(status_code=403, detail="verification failed")

    # -- signed event delivery (POST) -----------------------------------------

    def _signature_ok(self, body: bytes, header: str | None) -> bool:
        if not header or not header.startswith("sha256="):
            return False
        signature = header[len("sha256="):]
        if len(signature) != hashlib.sha256().digest_size * 2:
            return False
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError:
            return False
        expected = hmac.new(
            (self.app_secret or "").encode("utf-8"), body, hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, signature_bytes)

    @staticmethod
    def _extract_messages(payload: dict) -> list[dict]:
        """Flatten Meta's entry/changes nesting to text-message dicts."""
        out = []
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                for m in value.get("messages") or []:
                    if m.get("type") == "text":
                        out.append(m)
        return out

    async def _handle_webhook(self, request: Request):
        body = await request.body()
        if not self._signature_ok(body, request.headers.get("X-Hub-Signature-256")):
            log.warning("WhatsApp Cloud webhook signature invalid; ignoring")
            raise HTTPException(status_code=403, detail="signature invalid")
        import json
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="bad JSON")

        for m in self._extract_messages(payload):
            sender = str(m.get("from") or "")
            text = str(((m.get("text") or {}).get("body")) or "")
            msg_id = str(m.get("id") or "")
            if not is_allowed(sender, self.allowed_user_ids):
                log.warning("unauthorized whatsapp-cloud access: from=%s", sender)
                continue
            if not text:
                continue

            # Claim the message id atomically BEFORE processing so Meta's
            # redelivery can't double-run a goal (same pattern as Twilio).
            wm = None
            if msg_id:
                try:
                    from maverick.world_model import DEFAULT_DB, WorldModel
                    wm = WorldModel(DEFAULT_DB)
                    if not wm.mark_message_processed("whatsapp_cloud", msg_id):
                        log.info("whatsapp-cloud message %s already claimed; skipping", msg_id)
                        continue
                except Exception:  # pragma: no cover
                    log.warning("whatsapp-cloud dedup claim failed; processing anyway")
                    wm = None

            incoming = IncomingMessage(
                user_id=sender, text=text, channel="whatsapp_cloud", message_id=msg_id or None,
            )
            try:
                reply = await self.handler(incoming)
            except Exception as e:  # pragma: no cover
                log.exception("handler error")
                if wm is not None and msg_id:
                    try:
                        wm.release_processed_message("whatsapp_cloud", msg_id)
                    except Exception:  # pragma: no cover
                        log.warning("whatsapp-cloud dedup release failed")
                reply = f"⚠ error: {e}"
            if reply:
                await self.send(sender, reply)

        # Meta expects a fast 200 regardless of how many messages were acted on.
        return {"status": "ok"}

    # -- outbound ------------------------------------------------------------

    async def send(self, user_id: str, text: str) -> None:
        import httpx
        url = f"{GRAPH_BASE}/{self.api_version}/{self.phone_number_id}/messages"
        # WhatsApp caps text bodies at 4096 chars.
        for chunk in [text[i:i + 4000] for i in range(0, max(len(text), 1), 4000)]:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": user_id,
                        "type": "text",
                        "text": {"body": chunk},
                    },
                )
                if r.status_code >= 400:
                    log.warning("whatsapp-cloud send failed (%s): %s",
                                r.status_code, r.text[:200])

    async def start(self) -> None:
        import uvicorn
        config = uvicorn.Config(
            self._app, host=self.bind_host, port=self.port, log_level="warning",
        )
        self._uvicorn_server = uvicorn.Server(config)
        log.info("WhatsApp Cloud webhook on %s:%d", self.bind_host, self.port)
        await self._uvicorn_server.serve()

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
