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
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            text = line.rstrip("\n")
            if not text:
                continue
            msg = IncomingMessage(user_id="local", text=text, channel="cli")
            try:
                reply = await self.dispatch_text(msg)
            except Exception as e:  # one bad run must not kill the session
                reply = f"Sorry, I ran into an error: {e}"
            await self.send("local", reply)

    async def send(self, user_id: str, text: str) -> None:
        print(text, flush=True)

    async def stop(self) -> None:
        pass
