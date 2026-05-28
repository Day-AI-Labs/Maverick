"""Mastodon channel adapter.

Polls the authenticated account's notifications timeline for mentions
+ DMs (direct visibility statuses) and dispatches them as
IncomingMessages.

Auth: env vars MASTODON_INSTANCE (e.g. "mastodon.social") and
MASTODON_ACCESS_TOKEN. Create an access token at
``<instance>/settings/applications`` with the ``read`` + ``write``
scopes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional, Set

from .base import Channel, Handler, IncomingMessage

log = logging.getLogger(__name__)


_POLL_INTERVAL_SEC = 30.0
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Mastodon returns toots as HTML; for the agent we want plain text."""
    text = _HTML_TAG_RE.sub("", html or "")
    # Decode the two entities Mastodon emits most often.
    return text.replace("&amp;", "&").replace("&quot;", '"').strip()


class MastodonChannel(Channel):
    """Mastodon channel using the public REST API.

    Default scope: mentions + direct-visibility statuses. Other
    notification kinds (favourite, reblog, follow) are ignored.
    """

    name = "mastodon"

    def __init__(
        self,
        handler: Handler,
        *,
        instance: Optional[str] = None,
        access_token: Optional[str] = None,
        allowed_user_ids: Optional[set[str]] = None,
        poll_interval: float = _POLL_INTERVAL_SEC,
    ):
        super().__init__(handler)
        self.instance = (
            instance
            or os.environ.get("MASTODON_INSTANCE", "mastodon.social")
        ).strip().rstrip("/")
        self.access_token = (
            access_token or os.environ.get("MASTODON_ACCESS_TOKEN", "")
        )
        self.allowed_user_ids = self._normalize_allowlist(
            allowed_user_ids,
            env_name="MASTODON_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError(
                "Set MASTODON_ALLOWED_USER_IDS to restrict access"
            )
        self.poll_interval = poll_interval
        self._last_seen_id: Optional[str] = None
        self._running = False
        self._stop_event = asyncio.Event()

    @staticmethod
    def _normalize_allowlist(values: Optional[set[str]], env_name: str) -> Set[str]:
        if values is not None:
            return {str(v).strip() for v in values if str(v).strip()}
        raw = os.environ.get(env_name, "")
        return {item.strip() for item in raw.split(",") if item.strip()}

    @property
    def _base_url(self) -> str:
        if self.instance.startswith("http"):
            return self.instance
        return f"https://{self.instance}"

    def _headers(self) -> dict:
        if not self.access_token:
            raise RuntimeError(
                "Mastodon channel requires MASTODON_ACCESS_TOKEN."
            )
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _poll_once(self) -> list[dict]:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx not installed. Run: pip install 'maverick-channels[mastodon]'"
            ) from e
        params = {"types[]": "mention", "limit": 30}
        if self._last_seen_id:
            params["since_id"] = self._last_seen_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/notifications",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "Mastodon rejected the access token (401). "
                    "Regenerate at <instance>/settings/applications."
                )
            resp.raise_for_status()
            notifs = resp.json() or []
        if notifs:
            self._last_seen_id = max(n["id"] for n in notifs)
        return notifs

    async def _dispatch(self, notif: dict) -> None:
        status = notif.get("status") or {}
        account = notif.get("account") or {}
        text = _strip_html(status.get("content", ""))
        user_id = account.get("acct") or account.get("username") or "anonymous"
        if user_id not in self.allowed_user_ids:
            log.warning("unauthorized mastodon access: user_id=%s", user_id)
            return
        msg = IncomingMessage(
            user_id=user_id, text=text,
            channel=self.name, raw=notif,
        )
        try:
            reply = await self.handler(msg)
        except Exception as e:
            log.exception("mastodon handler raised: %s", e)
            return
        if reply:
            await self._post_reply(status, account, reply)

    async def _post_reply(self, parent_status: dict, account: dict, text: str) -> None:
        try:
            import httpx
        except ImportError:
            return
        body = {
            "status": f"@{account.get('acct')} {text}"[:480],
            "in_reply_to_id": parent_status.get("id"),
            "visibility": parent_status.get("visibility", "public"),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/statuses",
                headers=self._headers(),
                data=body,
            )
            if resp.status_code >= 400:
                log.warning(
                    "mastodon post failed (%d): %s",
                    resp.status_code, resp.text[:200],
                )

    async def start(self) -> None:
        self._running = True
        log.info("Mastodon channel started (instance=%s)", self.instance)
        try:
            while not self._stop_event.is_set():
                try:
                    notifs = await self._poll_once()
                except Exception as e:
                    log.warning("mastodon poll failed: %s", e)
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
        try:
            import httpx
        except ImportError:
            return
        # Direct-visibility status mentioning the user. Mastodon turns
        # this into a thread that the user gets notified about.
        body = {
            "status": f"@{user_id} {text}"[:480],
            "visibility": "direct",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{self._base_url}/api/v1/statuses",
                headers=self._headers(),
                data=body,
            )

    async def stop(self) -> None:
        self._stop_event.set()
        self._running = False
