"""Stdin/stdout channel.

The default channel — reads lines from stdin, dispatches them to the
handler, prints replies to stdout. Used by ``maverick start`` directly
and by tests.
"""
from __future__ import annotations

import asyncio
import sys

from .base import Channel, IncomingMessage


class CLIChannel(Channel):
    name = "cli"

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            text = line.rstrip("\n")
            if not text:
                continue
            msg = IncomingMessage(user_id="local", text=text, channel="cli")
            reply = await self.handler(msg)
            await self.send("local", reply)

    async def send(self, user_id: str, text: str) -> None:
        print(text, flush=True)

    async def stop(self) -> None:
        pass
