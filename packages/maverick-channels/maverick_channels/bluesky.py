"""Bluesky / AT Protocol channel adapter.

Polls the user's notifications timeline for mentions + DMs, dispatches
each as an IncomingMessage. Replies go back via the AT Proto REST API.

Auth: env vars BLUESKY_HANDLE + BLUESKY_PASSWORD. The 'password' is an
app password generated at bsky.app -> Settings -> App Passwords; never
the account password.

Heavy deps deferred to import time; the optional install is
``pip install 'maverick-channels[bluesky]'`` which pulls in httpx
(already a transitive of openai-compat providers).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Set

from .base import Channel, Handler, IncomingMessage

log = logging.getLogger(__name__)


_API_BASE = "https://bsky.social/xrpc"
_POLL_INTERVAL_SEC = 30.0


class BlueskyChannel(Channel):
    """Bluesky AT Proto channel.

    Reuses the same Handler / IncomingMessage shape as the other
    channel adapters. Polls notifications every 30s; on a `mention`
    or `reply` event, dispatches to the handler and posts the reply
    as a thread reply.
    """

    name = "bluesky"

    def __init__(
        self,
        handler: Handler,
        *,
        handle: Optional[str] = None,
        password: Optional[str] = None,
        allowed_user_ids: Optional[set[str]] = None,
        poll_interval: float = _POLL_INTERVAL_SEC,
    ):
        super().__init__(handler)
        self.handle = handle or os.environ.get("BLUESKY_HANDLE", "")
        self.password = password or os.environ.get("BLUESKY_PASSWORD", "")
        self.allowed_user_ids = self._normalize_allowlist(
            allowed_user_ids,
            env_name="BLUESKY_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError(
                "Set BLUESKY_ALLOWED_USER_IDS to restrict access"
            )
        self.poll_interval = poll_interval
        self._session: dict = {}
        self._last_seen_indexed_at: Optional[str] = None
        self._running = False
        self._stop_event = asyncio.Event()

    @staticmethod
    def _normalize_allowlist(values: Optional[set[str]], env_name: str) -> Set[str]:
        if values is not None:
            return {str(v).strip() for v in values if str(v).strip()}
        raw = os.environ.get(env_name, "")
        return {item.strip() for item in raw.split(",") if item.strip()}

    async def _ensure_session(self) -> dict:
        if self._session.get("accessJwt"):
            return self._session
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx not installed. Run: pip install 'maverick-channels[bluesky]'"
            ) from e
        if not self.handle or not self.password:
            raise RuntimeError(
                "Bluesky channel requires BLUESKY_HANDLE and BLUESKY_PASSWORD."
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_API_BASE}/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.password},
            )
            resp.raise_for_status()
            self._session = resp.json()
        return self._session

    async def _poll_once(self) -> list[dict]:
        """Fetch any new notifications since last poll."""
        sess = await self._ensure_session()
        try:
            import httpx
        except ImportError:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_API_BASE}/app.bsky.notification.listNotifications",
                headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                params={"limit": 50},
            )
            if resp.status_code == 401:
                # Session expired; force a re-login on next call.
                self._session = {}
                return []
            resp.raise_for_status()
            notifs = (resp.json() or {}).get("notifications") or []
        # Filter: only new mentions / replies / DMs.
        new: list[dict] = []
        for n in notifs:
            reason = n.get("reason")
            if reason not in ("mention", "reply"):
                continue
            ts = n.get("indexedAt", "")
            if self._last_seen_indexed_at and ts <= self._last_seen_indexed_at:
                continue
            new.append(n)
        if new:
            self._last_seen_indexed_at = max(n.get("indexedAt", "") for n in new)
        return new

    async def _dispatch(self, notif: dict) -> None:
        record = notif.get("record") or {}
        text = record.get("text", "")
        author = notif.get("author") or {}
        user_id = author.get("did") or author.get("handle") or "anonymous"
        if user_id not in self.allowed_user_ids:
            log.warning("unauthorized bluesky access: user_id=%s", user_id)
            return
        msg = IncomingMessage(
            user_id=user_id, text=text,
            channel=self.name, raw=notif,
        )
        try:
            reply = await self.handler(msg)
        except Exception as e:
            log.exception("bluesky handler raised: %s", e)
            return
        if reply:
            await self._reply(notif, reply)

    async def _reply(self, parent_notif: dict, text: str) -> None:
        """Post a reply in-thread to a notification."""
        sess = await self._ensure_session()
        try:
            import httpx
        except ImportError:
            return
        record = parent_notif.get("record") or {}
        reply_root = record.get("reply", {}).get("root") or {
            "uri": parent_notif.get("uri"),
            "cid": parent_notif.get("cid"),
        }
        body = {
            "repo": sess.get("did"),
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text[:300],  # 300-char limit
                "createdAt": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "reply": {
                    "root": reply_root,
                    "parent": {
                        "uri": parent_notif.get("uri"),
                        "cid": parent_notif.get("cid"),
                    },
                },
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_API_BASE}/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                json=body,
            )
            if resp.status_code >= 400:
                log.warning("bluesky post failed (%d): %s", resp.status_code, resp.text[:200])

    async def start(self) -> None:
        self._running = True
        await self._ensure_session()
        log.info("Bluesky channel started (handle=%s)", self.handle)
        try:
            while not self._stop_event.is_set():
                try:
                    notifs = await self._poll_once()
                except Exception as e:
                    log.warning("bluesky poll failed: %s", e)
                    notifs = []
                for n in notifs:
                    await self._dispatch(n)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False

    async def send(self, user_id: str, text: str) -> None:
        """Send a stand-alone message to a user (not in-thread)."""
        # Bluesky doesn't have proper DMs in the public API yet;
        # this falls back to a top-level post mentioning the user.
        sess = await self._ensure_session()
        try:
            import httpx
        except ImportError:
            return
        body = {
            "repo": sess.get("did"),
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": f"@{user_id}: {text[:280]}",
                "createdAt": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{_API_BASE}/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                json=body,
            )

    async def stop(self) -> None:
        self._stop_event.set()
        self._running = False
