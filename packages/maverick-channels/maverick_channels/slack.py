"""Slack channel via Socket Mode (no public webhook needed).

Set up:
  1. Create a Slack app at https://api.slack.com/apps
  2. Enable Socket Mode; copy the App-Level Token to ${SLACK_APP_TOKEN}
  3. Install to your workspace; copy the Bot Token to ${SLACK_BOT_TOKEN}
  4. Subscribe to `message.im` events; add `chat:write`, `im:history` scopes

Requires::

    pip install 'maverick-channels[slack]'
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

try:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web.async_client import AsyncWebClient
    _HAVE_SLACK = True
except ImportError:
    _HAVE_SLACK = False
    SocketModeClient = AsyncWebClient = SocketModeResponse = None  # type: ignore


class SlackChannel(Channel):
    name = "slack"

    def __init__(
        self,
        handler,
        app_token: Optional[str] = None,
        bot_token: Optional[str] = None,
        allowed_user_ids=None,
    ):
        super().__init__(handler)
        if not _HAVE_SLACK:
            raise ImportError(
                "slack_sdk not installed. Run: pip install 'maverick-channels[slack]'"
            )
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
        if not self.app_token or not self.bot_token:
            raise ValueError("SLACK_APP_TOKEN and SLACK_BOT_TOKEN must be set")
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "SLACK_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError("Set SLACK_ALLOWED_USER_IDS to restrict access")
        self._web = AsyncWebClient(token=self.bot_token)
        self._sm = SocketModeClient(app_token=self.app_token, web_client=self._web)
        self._sm.socket_mode_request_listeners.append(self._on_request)
        self._stop_event = asyncio.Event()

    async def _on_request(self, client, req):
        if req.type == "events_api":
            event = req.payload.get("event", {})
            if event.get("type") == "message" and "bot_id" not in event:
                sender = event.get("user", "")
                if not is_allowed(sender, self.allowed_user_ids):
                    log.warning("unauthorized slack access: user=%s", sender)
                else:
                    msg = IncomingMessage(
                        user_id=event.get("channel", ""),
                        text=event.get("text", ""),
                        channel="slack",
                        raw=event,
                    )
                    try:
                        reply = await self.handler(msg)
                    except Exception:  # pragma: no cover
                        log.exception("handler error")
                        reply = "⚠ An internal error occurred."
                    await self._web.chat_postMessage(channel=event["channel"], text=reply)
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

    async def start(self) -> None:
        await self._sm.connect()
        log.info("Slack channel connected")
        await self._stop_event.wait()

    async def send(self, user_id: str, text: str) -> None:
        await self._web.chat_postMessage(channel=user_id, text=text)

    async def stop(self) -> None:
        self._stop_event.set()
        await self._sm.disconnect()
