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

from .base import (
    Channel,
    IncomingMessage,
    is_allowed,
    normalize_allowlist,
    public_url_for,
)

log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, Form, HTTPException, Request, Response
    from twilio.request_validator import RequestValidator
    from twilio.rest import Client as TwilioClient
    _HAVE_DEPS = True
except ImportError:
    _HAVE_DEPS = False
    FastAPI = HTTPException = Request = Response = None  # type: ignore
    RequestValidator = TwilioClient = None  # type: ignore

    def Form(*_a, **_k):  # type: ignore  # noqa: N802
        # Placeholder so the webhook method's ``Form(...)`` DEFAULT ARGUMENTS
        # (evaluated at class-definition time) don't crash with a confusing
        # "'NoneType' object is not callable" when fastapi/twilio are absent.
        # __init__ raises the real, actionable ImportError before the method --
        # and these defaults -- is ever used (user-testing finding).
        return None


class SMSChannel(Channel):
    name = "sms"

    def __init__(
        self,
        handler,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        port: int = 8766,
        allowed_user_ids=None,
        bind_host: str | None = None,
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
        # The Twilio signature only proves Twilio relayed the message, not
        # that the *sender* is authorized. A Twilio number is reachable by
        # any PSTN subscriber, so require a per-sender allowlist (default-deny
        # via base.is_allowed) -- list senders as Twilio delivers them, e.g.
        # "+14155551234".
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "SMS_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError(
                "Set SMS_ALLOWED_USER_IDS to restrict who can drive the agent"
            )
        self.port = port
        # Bind loopback by default: Twilio reaches this through a reverse
        # proxy (see deploy/vps/Caddyfile), so the listener itself needn't be
        # exposed to the LAN/internet. Binding 0.0.0.0 widened the attack
        # surface (signature-validation bugs, unauthenticated request floods)
        # for no benefit. Override with SMS_BIND_HOST=0.0.0.0 if a deploy
        # genuinely needs Twilio to hit the port directly.
        self.bind_host = bind_host or os.environ.get("SMS_BIND_HOST", "127.0.0.1")
        self._twilio = TwilioClient(self.account_sid, self.auth_token)
        self._validator = RequestValidator(self.auth_token)
        self._app = FastAPI()
        self._app.post("/webhook/sms")(self._handle_webhook)
        self._uvicorn_server = None

    async def _handle_webhook(
        self,
        request: Request,
        From: str = Form(...),  # noqa: N803
        Body: str = Form(...),  # noqa: N803
        MessageSid: str = Form(""),  # noqa: N803 -- Twilio dedup key
    ):
        signature = request.headers.get("X-Twilio-Signature", "")
        # Validate against the PUBLIC URL Twilio signed, not the loopback URL
        # the reverse proxy forwarded to (see public_url_for).
        url = public_url_for(request)
        form = await request.form()
        form_dict = {k: str(v) for k, v in form.items()}
        if not self._validator.validate(url, form_dict, signature):
            log.warning("SMS webhook signature invalid; ignoring")
            raise HTTPException(status_code=403, detail="signature invalid")

        # A valid signature only proves Twilio relayed this; gate on the
        # actual sender before spending any budget (default-deny).
        if not is_allowed(From, self.allowed_user_ids):
            log.warning("unauthorized sms access: from=%s", From)
            raise HTTPException(status_code=403, detail="sender not allowed")

        # Twilio retries within ~15s on a slow or non-2xx handler. CLAIM the
        # MessageSid atomically before processing: mark_message_processed
        # INSERTs under the UNIQUE(channel, external_id) constraint and returns
        # False if the row already exists. The old code checked
        # is_processed_message() here and only marked AFTER the handler -- so a
        # retry that raced a still-running handler passed the check too and
        # spawned a second goal + second spend. Claiming first makes the racing
        # retry a no-op.
        wm = None
        if MessageSid:
            try:
                from maverick.world_model import DEFAULT_DB, WorldModel
                wm = WorldModel(DEFAULT_DB)
                if not wm.mark_message_processed("sms", MessageSid):
                    log.info("SMS MessageSid %s already claimed; skipping", MessageSid)
                    return Response(content="", media_type="text/xml")
            except Exception:  # pragma: no cover
                log.warning("SMS dedup claim failed; processing anyway")
                wm = None

        msg = IncomingMessage(user_id=From, text=Body, channel="sms")
        try:
            reply = await self.dispatch_text(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            # The goal didn't complete -- release the claim so Twilio's retry
            # re-processes instead of being deduped against a failed run.
            if wm is not None and MessageSid:
                try:
                    wm.release_processed_message("sms", MessageSid)
                except Exception:  # pragma: no cover
                    log.warning("SMS dedup release failed")
            try:
                await self.send(From, f"⚠ error: {e}")
            except Exception:  # pragma: no cover
                log.exception("SMS error-reply send failed")
            return Response(content="", media_type="text/xml")

        # Already claimed above; a transient outbound-send failure must NOT
        # 500 (Twilio would retry and re-run the whole goal). Attempt the
        # reply, logging a send failure without re-raising.
        try:
            await self.send(From, reply)
        except Exception:  # pragma: no cover
            log.exception("SMS reply send failed (goal already processed)")
        return Response(content="", media_type="text/xml")

    async def start(self) -> None:
        import uvicorn
        log.info("SMS channel listening on %s:%d", self.bind_host, self.port)
        config = uvicorn.Config(
            self._app, host=self.bind_host, port=self.port, log_level="info",
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
