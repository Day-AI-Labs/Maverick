"""iMessage channel (macOS only).

Reads incoming messages from ~/Library/Messages/chat.db and sends via
AppleScript. Requires Full Disk Access permission for the Python
process (System Settings > Privacy & Security > Full Disk Access).

Not available on Linux / Windows.

Config::

    [channels.imessage]
    enabled = true
    poll_interval = 5

v0.1.1 fix: send() previously did `osascript -e 'send "%s" to buddy "%s"'`
with naive escaping (only replaced `"` -> `\\"`), so LLM-controlled
message text containing `;`, `\\n`, or `$` could break out of the
string literal and execute arbitrary AppleScript / shell. The send
path now passes the script via stdin and the user-supplied text +
handle as positional argv to a parameterized `on run argv` script.
AppleScript treats argv items as literal strings -- no interpolation.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


_SEND_SCRIPT = (
    'on run argv\n'
    '    set theText to item 1 of argv\n'
    '    set theHandle to item 2 of argv\n'
    '    tell application "Messages"\n'
    '        send theText to buddy theHandle of '
    '(service 1 whose service type is iMessage)\n'
    '    end tell\n'
    'end run\n'
)


class iMessageChannel(Channel):  # noqa: N801 - product spelling
    name = "imessage"

    def __init__(self, handler, poll_interval: int = 5, allowed_user_ids=None):
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
        self.allowed_user_ids = normalize_allowlist(
            allowed_user_ids, "IMESSAGE_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError("Set IMESSAGE_ALLOWED_USER_IDS to restrict access")
        self.poll_interval = poll_interval
        self._last_rowid: Optional[int] = None
        self._stop = False

    async def start(self) -> None:
        log.info("iMessage channel polling chat.db every %ds", self.poll_interval)
        self._last_rowid = await asyncio.to_thread(self._latest_rowid)
        while not self._stop:
            try:
                messages = await asyncio.to_thread(self._fetch_new)
            except Exception:  # pragma: no cover
                log.exception("iMessage poll failed")
                messages = []
            for handle, text, rowid in messages:
                self._last_rowid = max(self._last_rowid or 0, rowid)
                if not is_allowed(handle, self.allowed_user_ids):
                    log.warning("unauthorized imessage access: handle=%s", handle)
                    continue
                msg = IncomingMessage(
                    user_id=handle, text=text, channel="imessage",
                )
                try:
                    reply = await self.handler(msg)
                except Exception:  # pragma: no cover
                    log.exception("handler error")
                    reply = "⚠ An internal error occurred."
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
        """Send via parameterized AppleScript (no shell-style interpolation).

        argv items are treated as literal strings by AppleScript, so even
        adversarial LLM output (quotes, semicolons, newlines, `$`) cannot
        escape into command execution.
        """
        await asyncio.to_thread(
            subprocess.run,
            ["osascript", "-", text, user_id],
            input=_SEND_SCRIPT,
            text=True,
            check=False,
            timeout=10,
        )

    async def stop(self) -> None:
        self._stop = True
