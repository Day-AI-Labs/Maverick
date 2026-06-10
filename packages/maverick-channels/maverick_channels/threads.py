"""Threads channel via Meta's Threads API (graph.threads.net).

Why polling, not webhooks: Threads has a webhook product, but subscribing is
partner-gated (business verification + App Review advanced access) — a wall
for self-hosters. The self-host-friendly path is polling the REST edges with
a plain Threads access token, so that is what this adapter does.

Edge choice: ``GET /v1.0/{user_id}/replies`` — the Reply Management edge for
the configured user — polled every ``poll_seconds``. Replies in the user's
own threads are the conversational surface a self-hosted agent actually
answers (someone replied under the bot's post); the alternative mentions
edge needs an extra permission grant and misses replies that don't
@-mention the account, and Threads has no DM API at all. Each reply carries
``username``/``from`` so the *author* — not the transport — is
allowlist-checked (default-deny), and replies authored by the configured
account itself are skipped so the bot can never loop on its own replies.

Dedup: polling re-sees recent replies every cycle, so reply ids are claimed
atomically (``mark_message_processed``) BEFORE processing and released if
the handler fails — the same pattern as whatsapp_cloud. One deliberate
difference: if the claim infrastructure is unavailable the reply is SKIPPED
(fail-closed) and retried next poll, because with no poll cursor "process
anyway" would re-run the same goal every ``poll_seconds``.

Outbound is the documented two-step publish: create a TEXT media container
(``POST /{user_id}/threads``, with ``reply_to_id`` when the target looks
like a media id — all digits, which is what the inbound flow passes), then
publish it (``POST /{user_id}/threads_publish``). Posts cap at 500 chars;
longer replies are chunked into sibling replies on the same target.

Config::

    [channels.threads]
    enabled = true
    access_token = "${THREADS_ACCESS_TOKEN}"
    user_id      = "17841400000000000"      # numeric Threads user id
    allowed_user_ids = ["yourhandle"]       # Threads usernames, no '@'
    poll_seconds = 30

Requires::

    pip install 'maverick-channels[threads]'   # httpx
"""
from __future__ import annotations

import asyncio
import logging
import os

from .base import Channel, Handler, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

THREADS_BASE = "https://graph.threads.net"
API_VERSION = "v1.0"
TEXT_LIMIT = 500  # Threads caps post text at 500 chars


class ThreadsChannel(Channel):
    name = "threads"

    def __init__(
        self,
        handler: Handler,
        access_token: str | None = None,
        user_id: str | None = None,
        allowed_user_ids=None,
        poll_seconds: float = 30,
    ):
        super().__init__(handler)
        self.access_token = access_token or os.environ.get("THREADS_ACCESS_TOKEN")
        self.user_id = user_id or os.environ.get("THREADS_USER_ID")
        if not all([self.access_token, self.user_id]):
            raise ValueError(
                "Threads credentials missing. Set access_token and user_id "
                "([channels.threads] or THREADS_ACCESS_TOKEN / THREADS_USER_ID env)."
            )
        # The token only proves WE can read the account; gate on the reply
        # AUTHOR (Threads username, no '@').
        self.allowed_user_ids = normalize_allowlist(allowed_user_ids, "THREADS_ALLOWED_USER_IDS")
        if not self.allowed_user_ids:
            raise ValueError(
                "Set THREADS_ALLOWED_USER_IDS to restrict who can drive the agent"
            )
        self.poll_seconds = float(poll_seconds)
        self._running = False
        self._stop_event = asyncio.Event()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    # -- inbound (poll loop) ---------------------------------------------------

    async def _poll_once(self) -> list[dict]:
        """Fetch recent replies in the user's threads (newness is decided by
        the dedup claim, not a cursor — the edge re-serves recent replies)."""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx not installed. Run: pip install 'maverick-channels[threads]'"
            ) from e
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{THREADS_BASE}/{API_VERSION}/{self.user_id}/replies",
                headers=self._headers(),
                params={"fields": "id,text,username,from"},
            )
            resp.raise_for_status()
            return (resp.json() or {}).get("data") or []

    async def _dispatch(self, reply: dict) -> None:
        reply_id = str(reply.get("id") or "")
        text = str(reply.get("text") or "")
        sender = reply.get("from") or {}
        username = str(reply.get("username") or sender.get("username") or "")
        if not reply_id or not text:
            return
        if str(sender.get("id") or "") == str(self.user_id):
            return  # our own reply; never respond to ourselves (loop guard)
        if not is_allowed(username, self.allowed_user_ids):
            log.warning("unauthorized threads access: username=%s", username)
            return

        # Claim the reply id atomically BEFORE processing (same pattern as
        # whatsapp_cloud). Polling has no cursor — every poll re-sees recent
        # replies — so unlike the webhook adapters we fail CLOSED when the
        # claim infrastructure is down: skip now, retry next poll. "Process
        # anyway" here would re-run the goal every poll_seconds.
        try:
            from maverick.world_model import DEFAULT_DB, WorldModel
            wm = WorldModel(DEFAULT_DB)
            if not wm.mark_message_processed("threads", reply_id):
                return  # already handled (this run or an earlier one)
        except Exception:
            log.warning("threads dedup claim failed; deferring reply %s to next poll", reply_id)
            return

        incoming = IncomingMessage(
            user_id=reply_id,  # the media id send() replies to
            text=text,
            channel="threads",
            message_id=reply_id,
            sender_id=username,
            raw=reply,
        )
        try:
            reply_text = await self.handler(incoming)
        except Exception:
            log.exception("threads handler error")
            try:
                wm.release_processed_message("threads", reply_id)
            except Exception:  # pragma: no cover
                log.warning("threads dedup release failed")
            return
        if reply_text:
            await self.send(reply_id, reply_text)

    async def start(self) -> None:
        self._running = True
        log.info("Threads channel started (user_id=%s)", self.user_id)
        try:
            while not self._stop_event.is_set():
                try:
                    replies = await self._poll_once()
                except Exception as e:
                    log.warning("threads poll failed: %s", e)
                    replies = []
                for reply in replies:
                    await self._dispatch(reply)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False

    # -- outbound --------------------------------------------------------------

    async def send(self, user_id: str, text: str) -> None:
        """Publish ``text``, threaded under ``user_id`` when it is a media id.

        Two-step Threads publish: create a TEXT media container, then publish
        it. An all-digit ``user_id`` is treated as a media id to reply to
        (the inbound flow passes the reply id); anything else (e.g. a
        username — Threads has no DM or post-to-user API) publishes a
        standalone thread on the configured account. Chunks land as sibling
        replies to the same target.
        """
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx not installed. Run: pip install 'maverick-channels[threads]'"
            ) from e
        base = f"{THREADS_BASE}/{API_VERSION}/{self.user_id}"
        reply_to = user_id if str(user_id or "").isdigit() else None
        for chunk in [text[i:i + TEXT_LIMIT] for i in range(0, max(len(text), 1), TEXT_LIMIT)]:
            data = {"media_type": "TEXT", "text": chunk}
            if reply_to:
                data["reply_to_id"] = reply_to
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base}/threads", headers=self._headers(), data=data)
                if r.status_code >= 400:
                    log.warning("threads create failed (%s): %s", r.status_code, r.text[:200])
                    return
                creation_id = (r.json() or {}).get("id")
                if not creation_id:
                    log.warning("threads create returned no creation id")
                    return
                r2 = await client.post(
                    f"{base}/threads_publish",
                    headers=self._headers(),
                    data={"creation_id": creation_id},
                )
                if r2.status_code >= 400:
                    log.warning("threads publish failed (%s): %s", r2.status_code, r2.text[:200])
                    return

    async def stop(self) -> None:
        self._stop_event.set()
        self._running = False
