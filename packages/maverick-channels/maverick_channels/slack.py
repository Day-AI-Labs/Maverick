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
        app_token: str | None = None,
        bot_token: str | None = None,
        allowed_user_ids=None,
        thread_replies: bool | None = None,
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
        # Without an allowlist, ANY workspace user who can message the bot
        # drives the agent (and burns the operator's budget). Require one,
        # matching discord/telegram. Default-deny via base.is_allowed.
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "SLACK_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError("Set SLACK_ALLOWED_USER_IDS to restrict access")
        # Opt-in reply threading: answers post under the asking message's
        # thread (thread_ts) instead of interleaving into the channel.
        # [channels.slack] thread_replies / SLACK_THREAD_REPLIES.
        if thread_replies is None:
            thread_replies = os.environ.get(
                "SLACK_THREAD_REPLIES", "").strip().lower() in {"1", "true", "yes", "on"}
        self.thread_replies = bool(thread_replies)
        self._web = AsyncWebClient(token=self.bot_token)
        self._sm = SocketModeClient(app_token=self.app_token, web_client=self._web)
        self._sm.socket_mode_request_listeners.append(self._on_request)
        self._stop_event = asyncio.Event()

    async def _on_request(self, client, req):
        # Ack IMMEDIATELY, before doing any work. Slack redelivers an event
        # (up to ~3x) if the Socket Mode ack doesn't arrive within ~3s, and the
        # handler below runs a full agent swarm that routinely takes far longer
        # -- so acking at the end caused Slack to redeliver and the agent to run
        # (and bill) 2-3x per message. Acking first trades at-least-once for
        # at-most-once delivery, which is the right call for an expensive,
        # side-effecting handler.
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )
        if req.type == "events_api":
            event = req.payload.get("event", {})
            if event.get("type") == "message" and "bot_id" not in event:
                # Gate on the SENDER (event["user"]); user_id below is the
                # channel we reply to, not the author. Unlisted senders are
                # silently ignored.
                sender = event.get("user", "")
                if not is_allowed(sender, self.allowed_user_ids):
                    log.warning("unauthorized slack access: user=%s", sender)
                else:
                    msg = IncomingMessage(
                        user_id=event.get("channel", ""),
                        text=event.get("text", ""),
                        channel="slack",
                        raw=event,
                        sender_id=sender,
                        message_id=event.get("ts"),
                    )
                    try:
                        reply = await self.dispatch_text(msg)
                    except Exception:  # pragma: no cover
                        log.exception("handler error")
                        reply = "⚠ An internal error occurred."
                    # An empty reply (action-only goal, or a Reply whose text
                    # dispatch dropped) must not be sent: chat_postMessage(text="")
                    # is rejected by Slack with `no_text`, raising out of the
                    # handler. Guard with `if reply:` like the other channels.
                    if reply and self.thread_replies and event.get("ts"):
                        await self.send_threaded(
                            event["channel"], reply, reply_to=event["ts"])
                    elif reply:
                        # Route through send() so the reply gets to_slack_mrkdwn
                        # + mrkdwn=True like every other outbound path; the raw
                        # chat_postMessage here left markdown unrendered whenever
                        # thread_replies was off.
                        await self.send(event["channel"], reply)

    async def start(self) -> None:
        await self._sm.connect()
        log.info("Slack channel connected")
        await self._stop_event.wait()

    async def send(self, user_id: str, text: str) -> None:
        from .formatting import to_slack_mrkdwn
        await self._web.chat_postMessage(
            channel=user_id, text=to_slack_mrkdwn(text), mrkdwn=True,
        )

    async def send_threaded(
        self, user_id: str, text: str, *, reply_to: str | None = None,
    ) -> None:
        from .formatting import to_slack_mrkdwn
        kwargs = {"channel": user_id, "text": to_slack_mrkdwn(text), "mrkdwn": True}
        if reply_to:
            kwargs["thread_ts"] = reply_to
        await self._web.chat_postMessage(**kwargs)

    async def stop(self) -> None:
        self._stop_event.set()
        await self._sm.disconnect()
