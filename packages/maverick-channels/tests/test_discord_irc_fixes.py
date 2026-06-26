"""Round-3 channel regressions: Discord dispatch wiring + IRC CRLF injection."""
from __future__ import annotations

import asyncio

from maverick_channels import discord as dmod
from maverick_channels.irc import IRCChannel, format_privmsg

# --- Discord: CRITICAL -- on_message hit AttributeError on every message ------

class _Author:
    def __init__(self, id_):
        self.id = id_


class _Chan:
    def __init__(self):
        self.id = 555
        self.sent: list[str] = []
        self.mentions: list = []

    async def send(self, chunk, allowed_mentions=None):
        self.sent.append(chunk)
        self.mentions.append(allowed_mentions)


class _Msg:
    def __init__(self, author_id, text, chan):
        self.author = _Author(author_id)
        self.content = text
        self.channel = chan


def test_discord_invokes_agent_via_passed_dispatch_text():
    chan = _Chan()
    seen = []

    async def fake_dispatch(m):
        seen.append(m.text)
        return "world"

    asyncio.run(dmod._handle_discord_message(
        _Msg("123", "hello", chan), bot_user=object(),
        allowed_user_ids={"123"}, dispatch_text=fake_dispatch))

    assert seen == ["hello"]      # the agent WAS invoked (no AttributeError)
    assert chan.sent == ["world"]  # reply delivered


def test_discord_gates_unauthorized_author():
    chan = _Chan()
    called = []

    async def fake_dispatch(m):
        called.append(1)
        return "x"

    asyncio.run(dmod._handle_discord_message(
        _Msg("999", "hi", chan), bot_user=object(),
        allowed_user_ids={"123"}, dispatch_text=fake_dispatch))

    assert called == [] and chan.sent == []


def test_discord_empty_reply_is_not_sent():
    # An empty reply (action-only goal, or a Reply whose text dispatch dropped)
    # must not be sent: split_for_discord("") -> [""] and channel.send("") is a
    # Discord 400 "Cannot send an empty message" that escapes on_message.
    chan = _Chan()

    async def empty(m):
        return ""

    asyncio.run(dmod._handle_discord_message(
        _Msg("123", "hi", chan), bot_user=object(),
        allowed_user_ids={"123"}, dispatch_text=empty))

    assert chan.sent == []  # nothing sent, no empty-message API error


def test_discord_suppresses_mention_amplification(monkeypatch):
    # Agent output containing @everyone must NOT ping the guild: every send
    # pins an AllowedMentions that suppresses mentions. We stub _no_mentions to
    # a sentinel so the assertion holds whether or not discord.py is installed.
    chan = _Chan()
    monkeypatch.setattr(dmod, "_no_mentions", lambda: "SUPPRESSED")

    async def echo(m):
        return "@everyone free nitro"

    asyncio.run(dmod._handle_discord_message(
        _Msg("123", "hi", chan), bot_user=object(),
        allowed_user_ids={"123"}, dispatch_text=echo))

    assert chan.sent == ["@everyone free nitro"]   # text still delivered
    assert chan.mentions == ["SUPPRESSED"]          # ...with mentions suppressed


def test_discord_handler_error_does_not_leak_internals():
    chan = _Chan()

    async def boom(m):
        raise RuntimeError("secret internal detail")

    asyncio.run(dmod._handle_discord_message(
        _Msg("123", "hi", chan), bot_user=object(),
        allowed_user_ids={"123"}, dispatch_text=boom))

    assert chan.sent == ["⚠ error handling your message"]
    assert "secret internal detail" not in chan.sent[0]


# --- IRC: HIGH -- bare \r injected an IRC command ----------------------------

def test_format_privmsg_splits_on_bare_cr():
    lines = format_privmsg("#chan", "hello\rJOIN #evil")
    # No raw CR/LF survives into any wire line...
    assert all("\r" not in ln and "\n" not in ln for ln in lines)
    # ...and the injected command is now PRIVMSG *text*, not a second command.
    assert lines == ["PRIVMSG #chan :hello", "PRIVMSG #chan :JOIN #evil"]


def test_format_privmsg_handles_crlf_and_lf():
    assert format_privmsg("#c", "a\r\nb\nc") == [
        "PRIVMSG #c :a", "PRIVMSG #c :b", "PRIVMSG #c :c",
    ]


class _FakeWriter:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b

    async def drain(self):
        pass


def test_send_line_strips_embedded_crlf():
    ch = IRCChannel.__new__(IRCChannel)  # bypass __init__ (needs server config)
    ch._writer = _FakeWriter()
    asyncio.run(ch._send_line("PRIVMSG #c :hi\r\nQUIT"))
    # Exactly one wire line (single trailing CRLF); the embedded CRLF is gone.
    assert ch._writer.data == b"PRIVMSG #c :hiQUIT\r\n"
