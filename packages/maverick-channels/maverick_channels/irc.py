"""IRC channel adapter (RFC 1459 / 2812).

Drives Maverick from an IRC channel or direct message. The agent joins one or
more channels on a server, answers messages from allow-listed nicks, and replies
with PRIVMSG. TLS is supported (``[channels.irc] tls = true``).

Set up (``[channels.irc]``)::

    server   = "irc.libera.chat"
    port     = 6697
    tls      = true
    nick     = "maverickbot"
    channels = ["#maverick"]
    # IRC_ALLOWED_NICKS, comma-separated, restricts who can drive the agent.

The wire protocol is line-based; the parse/format helpers below are pure and
unit-tested. The socket transport (:meth:`IRCChannel.start`) needs a live IRC
server, the same as every other external-service channel.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

# IRC lines are capped at 512 bytes including the "\r\n" and the
# ":prefix COMMAND target :" envelope. 400 leaves comfortable headroom.
_MAX_LINE_CHARS = 400


@dataclass(frozen=True)
class IRCMessage:
    prefix: str
    command: str
    params: list[str]
    trailing: str

    @property
    def sender_nick(self) -> str:
        """The nick from ``nick!user@host``, or the bare prefix."""
        return self.prefix.split("!", 1)[0] if self.prefix else ""


def parse_line(line: str) -> IRCMessage | None:
    """Parse one IRC protocol line. Returns ``None`` for blank lines."""
    line = line.rstrip("\r\n")
    if not line:
        return None
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    # The trailing param starts at the first " :".
    head, sep, trailing = line.partition(" :")
    tokens = head.split()
    if not tokens:
        return None
    command = tokens[0].upper()
    params = tokens[1:]
    return IRCMessage(prefix=prefix, command=command, params=params,
                      trailing=trailing if sep else "")


def is_ping(msg: IRCMessage) -> bool:
    return msg.command == "PING"


def pong_for(msg: IRCMessage) -> str:
    """The PONG reply for a PING (echo its token)."""
    token = msg.trailing or (msg.params[0] if msg.params else "")
    return f"PONG :{token}"


def parse_privmsg(msg: IRCMessage, *, own_nick: str) -> tuple[str, str, str] | None:
    """For a PRIVMSG, return ``(sender_nick, reply_target, text)``.

    ``reply_target`` is the channel for a room message, or the sender for a DM
    (a PRIVMSG addressed to our own nick). Returns ``None`` for non-PRIVMSG."""
    if msg.command != "PRIVMSG" or not msg.params:
        return None
    target = msg.params[0]
    sender = msg.sender_nick
    text = msg.trailing
    reply_target = sender if target == own_nick else target
    return sender, reply_target, text


def format_privmsg(target: str, text: str, *, max_chars: int = _MAX_LINE_CHARS) -> list[str]:
    """Split ``text`` into PRIVMSG lines for ``target`` (IRC has no newlines and
    a 512-byte line cap). Each physical newline starts a new PRIVMSG; long lines
    are hard-wrapped at ``max_chars``."""
    lines: list[str] = []
    for raw in (text or "").split("\n"):
        chunk = raw
        if not chunk:
            continue
        while len(chunk) > max_chars:
            lines.append(f"PRIVMSG {target} :{chunk[:max_chars]}")
            chunk = chunk[max_chars:]
        lines.append(f"PRIVMSG {target} :{chunk}")
    return lines or [f"PRIVMSG {target} :(no content)"]


class IRCChannel(Channel):
    name = "irc"

    def __init__(
        self,
        handler,
        server: str,
        *,
        nick: str = "maverick",
        port: int = 6697,
        tls: bool = True,
        channels=None,
        password: str | None = None,
        allowed_user_ids=None,
    ):
        super().__init__(handler)
        if not server:
            raise ValueError("IRC channel requires a server host")
        self.server = server
        self.nick = nick
        self.port = int(port)
        self.tls = bool(tls)
        self.channels = list(channels or [])
        self.password = password
        # Without an allowlist any nick could drive the agent; default-deny.
        self.allowed_user_ids = normalize_allowlist(allowed_user_ids, "IRC_ALLOWED_NICKS")
        if not self.allowed_user_ids:
            raise ValueError("Set IRC_ALLOWED_NICKS to restrict who can drive the agent")
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._running = False

    async def _send_line(self, line: str) -> None:
        if self._writer is None:  # pragma: no cover -- guarded by start()
            return
        self._writer.write((line + "\r\n").encode("utf-8", errors="replace"))
        await self._writer.drain()

    async def start(self) -> None:  # pragma: no cover -- needs a live IRC server
        self._reader, self._writer = await asyncio.open_connection(
            self.server, self.port, ssl=self.tls,
        )
        self._running = True
        if self.password:
            await self._send_line(f"PASS {self.password}")
        await self._send_line(f"NICK {self.nick}")
        await self._send_line(f"USER {self.nick} 0 * :Maverick agent")
        for chan in self.channels:
            await self._send_line(f"JOIN {chan}")
        while self._running:
            raw = await self._reader.readline()
            if not raw:
                break
            try:
                await self._handle_raw(raw.decode("utf-8", errors="replace"))
            except Exception:  # pragma: no cover -- one bad line never kills the loop
                log.exception("irc: error handling line")

    async def _handle_raw(self, raw: str) -> None:
        msg = parse_line(raw)
        if msg is None:
            return
        if is_ping(msg):
            await self._send_line(pong_for(msg))
            return
        parsed = parse_privmsg(msg, own_nick=self.nick)
        if parsed is None:
            return
        sender, reply_target, text = parsed
        if not is_allowed(sender, self.allowed_user_ids):
            return
        incoming = IncomingMessage(
            user_id=reply_target, text=text, channel=self.name,
            raw=msg, sender_id=sender,
        )
        reply = await self.handler(incoming)
        if reply:
            await self.send(reply_target, reply)

    async def send(self, user_id: str, text: str) -> None:
        for line in format_privmsg(user_id, text):
            await self._send_line(line)

    async def stop(self) -> None:
        self._running = False
        if self._writer is not None:
            try:
                self._writer.write(b"QUIT :Maverick shutting down\r\n")
                await self._writer.drain()
                self._writer.close()
            except Exception:  # pragma: no cover
                pass


__all__ = [
    "IRCChannel", "IRCMessage", "parse_line", "parse_privmsg",
    "format_privmsg", "is_ping", "pong_for",
]
