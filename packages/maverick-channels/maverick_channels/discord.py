"""Discord bot channel.

Uses the gateway WebSocket so no public webhook is needed. Set up:
  1. Create an application at https://discord.com/developers/applications
  2. Add a Bot user; enable Message Content Intent
  3. Copy the bot token to ${DISCORD_BOT_TOKEN}
  4. Invite the bot to your server with messages.read+send scope

Requires::

    pip install 'maverick-channels[discord]'
"""
from __future__ import annotations

import logging
import os

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

try:
    import discord
    _HAVE_DISCORD = True
except ImportError:
    _HAVE_DISCORD = False
    discord = None  # type: ignore


async def _handle_discord_message(message, *, bot_user, allowed_user_ids, dispatch_text):
    """Gate, dispatch, and reply to one inbound Discord message.

    Pulled OUT of the ``discord.Client`` subclass so the agent path is
    unit-testable without the discord.py dependency -- and, critically, so
    ``dispatch_text`` (a :class:`Channel` method) is passed in explicitly. The
    old ``on_message`` called ``self.dispatch_text``, but the client subclasses
    ``discord.Client`` (not ``Channel``), so EVERY message raised
    ``AttributeError`` and replied with an error -- the agent was never invoked.
    """
    if message.author == bot_user:
        return
    # Gate on the AUTHOR id, not the channel id (which is what we reply to).
    author_id = str(getattr(message.author, "id", ""))
    if not is_allowed(author_id, allowed_user_ids):
        log.warning("unauthorized discord access: author_id=%s", author_id)
        return
    msg = IncomingMessage(
        user_id=str(message.channel.id),
        text=message.content,
        channel="discord",
        raw=message,
        sender_id=author_id,
    )
    try:
        reply = await dispatch_text(msg)
    except Exception:
        # Don't leak internals (exception text / class names) to the chat.
        log.exception("discord handler error")
        reply = "⚠ error handling your message"
    # An empty reply (action-only goal, or a Reply whose text dispatch dropped)
    # must not be sent: split_for_discord("") returns [""], and channel.send("")
    # is rejected by Discord with a 400 "Cannot send an empty message", which
    # propagates out of on_message as an unhandled task error. Guard with
    # `if reply:` like the other channels.
    if not reply:
        return
    from .formatting import split_for_discord
    for chunk in split_for_discord(reply):
        await message.channel.send(chunk)


class DiscordChannel(Channel):
    name = "discord"

    def __init__(self, handler, token: str | None = None, allowed_user_ids=None):
        super().__init__(handler)
        if not _HAVE_DISCORD:
            raise ImportError(
                "discord.py not installed. Run: pip install 'maverick-channels[discord]'"
            )
        self.token = token or os.environ.get("DISCORD_BOT_TOKEN")
        if not self.token:
            raise ValueError("DISCORD_BOT_TOKEN not set")
        # Without an allowlist, ANY user in a channel the bot can see could
        # drive the agent. Require one (matches bluesky/telegram).
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "DISCORD_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError("Set DISCORD_ALLOWED_USER_IDS to restrict access")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = _MaverickDiscordClient(
            dispatch_text=self.dispatch_text,
            allowed_user_ids=self.allowed_user_ids, intents=intents,
        )

    async def start(self) -> None:
        log.info("Discord channel starting")
        await self._client.start(self.token)

    async def send(self, user_id: str, text: str) -> None:
        await self._client.wait_until_ready()
        channel = self._client.get_channel(int(user_id))
        if channel is None:
            log.warning("Discord channel %s not found", user_id)
            return
        from .formatting import split_for_discord
        for chunk in split_for_discord(text):
            await channel.send(chunk)

    async def stop(self) -> None:
        await self._client.close()


if _HAVE_DISCORD:
    class _MaverickDiscordClient(discord.Client):  # type: ignore[misc]
        def __init__(self, dispatch_text, allowed_user_ids=None, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._dispatch_text = dispatch_text  # bound Channel.dispatch_text
            self.allowed_user_ids = allowed_user_ids or set()

        async def on_ready(self):  # type: ignore[override]
            log.info("Discord ready as %s", self.user)

        async def on_message(self, message):  # type: ignore[override]
            await _handle_discord_message(
                message, bot_user=self.user,
                allowed_user_ids=self.allowed_user_ids,
                dispatch_text=self._dispatch_text,
            )
else:
    _MaverickDiscordClient = None  # type: ignore
