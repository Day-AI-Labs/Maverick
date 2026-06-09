"""IRC channel adapter — pure protocol logic + dispatch (ROADMAP connector)."""
from __future__ import annotations

import asyncio

import pytest
from maverick_channels.irc import (
    IRCChannel,
    format_privmsg,
    is_ping,
    parse_line,
    parse_privmsg,
    pong_for,
)


def test_parse_line_with_prefix_and_trailing():
    m = parse_line(":alice!u@host PRIVMSG #room :hello world\r\n")
    assert m.command == "PRIVMSG"
    assert m.sender_nick == "alice"
    assert m.params == ["#room"]
    assert m.trailing == "hello world"


def test_parse_line_blank_is_none():
    assert parse_line("\r\n") is None
    assert parse_line("") is None


def test_ping_pong():
    m = parse_line("PING :LAG1234")
    assert is_ping(m)
    assert pong_for(m) == "PONG :LAG1234"


def test_parse_privmsg_room_vs_dm():
    room = parse_privmsg(parse_line(":bob!u@h PRIVMSG #chan :hi"), own_nick="mav")
    assert room == ("bob", "#chan", "hi")  # reply to the channel
    dm = parse_privmsg(parse_line(":bob!u@h PRIVMSG mav :hi"), own_nick="mav")
    assert dm == ("bob", "bob", "hi")      # reply to the sender


def test_parse_privmsg_ignores_non_privmsg():
    assert parse_privmsg(parse_line(":x JOIN #chan"), own_nick="mav") is None


def test_format_privmsg_wraps_long_and_splits_newlines():
    lines = format_privmsg("#chan", "a" * 950, max_chars=400)
    assert len(lines) == 3
    assert all(line.startswith("PRIVMSG #chan :") for line in lines)
    multi = format_privmsg("#chan", "one\ntwo")
    assert multi == ["PRIVMSG #chan :one", "PRIVMSG #chan :two"]


def test_format_privmsg_empty_has_placeholder():
    assert format_privmsg("#chan", "") == ["PRIVMSG #chan :(no content)"]


def test_requires_allowlist():
    with pytest.raises(ValueError):
        IRCChannel(lambda m: None, "irc.example", nick="mav", allowed_user_ids=[])


def test_requires_server():
    with pytest.raises(ValueError):
        IRCChannel(lambda m: None, "", allowed_user_ids=["alice"])


def test_dispatch_allowed_sender_replies():
    sent = []

    async def handler(msg):
        assert msg.sender_id == "alice"
        assert msg.user_id == "#chan"   # reply target is the room
        assert msg.text == "do it"
        return "on it"

    ch = IRCChannel(handler, "irc.example", nick="mav", allowed_user_ids=["alice"])

    async def fake_send(line):
        sent.append(line)

    ch._send_line = fake_send  # type: ignore[assignment]
    asyncio.run(ch._handle_raw(":alice!u@h PRIVMSG #chan :do it\r\n"))
    assert sent == ["PRIVMSG #chan :on it"]


def test_dispatch_blocks_disallowed_sender():
    sent = []

    async def handler(msg):  # pragma: no cover -- must not be called
        return "should not run"

    ch = IRCChannel(handler, "irc.example", nick="mav", allowed_user_ids=["alice"])

    async def fake_send(line):
        sent.append(line)

    ch._send_line = fake_send  # type: ignore[assignment]
    asyncio.run(ch._handle_raw(":mallory!u@h PRIVMSG #chan :pwn\r\n"))
    assert sent == []  # ignored


def test_ping_is_answered_in_loop():
    sent = []

    async def handler(msg):  # pragma: no cover
        return ""

    ch = IRCChannel(handler, "irc.example", nick="mav", allowed_user_ids=["alice"])

    async def fake_send(line):
        sent.append(line)

    ch._send_line = fake_send  # type: ignore[assignment]
    asyncio.run(ch._handle_raw("PING :TOKEN42\r\n"))
    assert sent == ["PONG :TOKEN42"]
