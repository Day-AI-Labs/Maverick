"""iMessage channel (macOS only).

Reads incoming messages from ~/Library/Messages/chat.db and sends via
AppleScript. Requires Full Disk Access permission for the Python
process (System Settings > Privacy & Security > Full Disk Access).

Not available on Linux / Windows.

Config::

    [channels.imessage]
    enabled = true
    poll_interval = 5
"""
from __future__ import annotations

import asyncio
import logging
import platform
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


class iMessageChannel(Channel):  # noqa: N801 - product spelling
    name = "imessage"

    def __init__(self, handler, poll_interval: int = 5):
        super().__init__(handler)
        if platform.system() != "Darwin":
            raise RuntimeError(
                "iMessage channel is macOS only (current platform: "
                f"{platform.system()})"
            )
        if not CHAT_DB.exists():
            raise FileNotFoundError(
                f"Messages database not found at {CHAT_DB}. Ensure Messages.app "
                "has been opened at least once and grant Full Disk Access."
            )
        self.poll_interval = poll_interval
        self._last_rowid: Optional[int] = None
        self._stop = False

    async def start(self) -> None:
        log.info("iMessage channel polling chat.db every %ds", self.poll_interval)
        # Initialize cursor to current latest so we only handle NEW messages.
        self._last_rowid = await asyncio.to_thread(self._latest_rowid)
        while not self._stop:
            try:
                messages = await asyncio.to_thread(self._fetch_new)
            except Exception:  # pragma: no cover
                log.exception("iMessage poll failed")
                messages = []
            for handle, text, rowid in messages:
                self._last_rowid = max(self._last_rowid or 0, rowid)
                msg = IncomingMessage(
                    user_id=handle, text=text, channel="imessage",
                )
                try:
                    reply = await self.handler(msg)
                except Exception as e:  # pragma: no cover
                    log.exception("handler error")
                    reply = f"⚠ error: {e}"
                await self.send(handle, reply)
            await asyncio.sleep(self.poll_interval)

    def _latest_rowid(self) -> int:
        with sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT COALESCE(MAX(ROWID), 0) FROM message").fetchone()
            return row[0] if row else 0

    def _fetch_new(self) -> list[tuple[str, str, int]]:
        out: list[tuple[str, str, int]] = []
        with sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                """
                SELECT m.ROWID, h.id, m.text
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                  AND m.is_from_me = 0
                  AND m.text IS NOT NULL
                ORDER BY m.ROWID ASC
                """,
                (self._last_rowid or 0,),
            )
            for rowid, handle, text in cur.fetchall():
                if text:
                    out.append((handle, text, rowid))
        return out

    async def send(self, user_id: str, text: str) -> None:
        escaped = text.replace('"', '\\"')
        script = (
            f'tell application "Messages"\n'
            f'  send "{escaped}" to buddy "{user_id}" '
            f'of (service 1 whose service type is iMessage)\n'
            f'end tell'
        )
        await asyncio.to_thread(
            subprocess.run, ["osascript", "-e", script], check=False,
        )

    async def stop(self) -> None:
        self._stop = True
