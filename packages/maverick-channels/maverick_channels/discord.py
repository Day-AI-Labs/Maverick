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
from typing import Optional

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)

try:
    import discord
    _HAVE_DISCORD = True
except ImportError:
    _HAVE_DISCORD = False
    discord = None  # type: ignore


class DiscordChannel(Channel):
    name = "discord"

    def __init__(self, handler, token: Optional[str] = None):
        super().__init__(handler)
        if not _HAVE_DISCORD:
            raise ImportError(
                "discord.py not installed. Run: pip install 'maverick-channels[discord]'"
            )
        self.token = token or os.environ.get("DISCORD_BOT_TOKEN")
        if not self.token:
            raise ValueError("DISCORD_BOT_TOKEN not set")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = _MaverickDiscordClient(handler=handler, intents=intents)

    async def start(self) -> None:
        log.info("Discord channel starting")
        await self._client.start(self.token)

    async def send(self, user_id: str, text: str) -> None:
        await self._client.wait_until_ready()
        channel = self._client.get_channel(int(user_id))
        if channel is None:
            log.warning("Discord channel %s not found", user_id)
            return
        await channel.send(text)

    async def stop(self) -> None:
        await self._client.close()


if _HAVE_DISCORD:
    class _MaverickDiscordClient(discord.Client):  # type: ignore[misc]
        def __init__(self, handler, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.handler = handler

        async def on_ready(self):  # type: ignore[override]
            log.info("Discord ready as %s", self.user)

        async def on_message(self, message):  # type: ignore[override]
            if message.author == self.user:
                return
            msg = IncomingMessage(
                user_id=str(message.channel.id),
                text=message.content,
                channel="discord",
                raw=message,
            )
            try:
                reply = await self.handler(msg)
            except Exception as e:  # pragma: no cover
                log.exception("handler error")
                reply = f"⚠ error: {e}"
            await message.channel.send(reply)
else:
    _MaverickDiscordClient = None  # type: ignore
