"""Signal channel via signal-cli jsonRpc daemon.

Set up (one-time):
  1. Install signal-cli (https://github.com/AsamK/signal-cli)
  2. Register your number:  signal-cli -u +12345550199 register
  3. Verify:                signal-cli -u +12345550199 verify <code>
  4. Set [channels.signal] phone_number = "+12345550199" in config

This adapter spawns signal-cli in jsonRpc mode and pipes JSON over
stdin/stdout. No public network exposure needed; everything happens on
the local machine.

Requires signal-cli installed on PATH (Java runtime under the hood).
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Optional

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)


class SignalChannel(Channel):
    name = "signal"

    def __init__(
        self,
        handler,
        phone_number: str,
        signal_cli_path: Optional[str] = None,
    ):
        super().__init__(handler)
        self.phone_number = phone_number
        self.signal_cli_path = signal_cli_path or shutil.which("signal-cli")
        if not self.signal_cli_path:
            raise FileNotFoundError(
                "signal-cli not found on PATH. Install from "
                "https://github.com/AsamK/signal-cli"
            )
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send_rpc(self, method: str, params: Optional[dict] = None) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("signal-cli not running")
        req = {"jsonrpc": "2.0", "method": method, "id": self._next_id()}
        if params:
            req["params"] = params
        line = (json.dumps(req) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self.signal_cli_path,
            "-u", self.phone_number,
            "jsonRpc",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("Signal channel started (signal-cli pid=%s)", self._proc.pid)

        assert self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                log.warning("signal-cli exited")
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("method") != "receive":
                continue
            envelope = data.get("params", {}).get("envelope", {})
            source = envelope.get("source", "")
            text = envelope.get("dataMessage", {}).get("message")
            if not text or not source:
                continue
            msg = IncomingMessage(
                user_id=source, text=text, channel="signal", raw=envelope,
            )
            try:
                reply = await self.handler(msg)
            except Exception as e:  # pragma: no cover
                log.exception("handler error")
                reply = f"⚠ error: {e}"
            await self.send(source, reply)

    async def send(self, user_id: str, text: str) -> None:
        await self._send_rpc("send", {"recipient": [user_id], "message": text})

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover
                self._proc.kill()
