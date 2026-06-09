"""Glasses/wearable channel — ack-then-run bridge (ROADMAP connector)."""
from __future__ import annotations

import asyncio

import pytest
from maverick_channels.glasses import (
    GlassesChannel,
    ack_message,
    classify_utterance,
    hud_trim,
)


@pytest.mark.parametrize("text,expected", [
    ("what's the weather", "quick"),
    ("who won the game", "quick"),
    ("write a python script to sort a file", "long"),
    ("research the best EV batteries", "long"),
    ("deploy the staging build", "long"),
    ("analyze last quarter's revenue", "long"),
    ("hello there", "quick"),
])
def test_classify_utterance(text, expected):
    assert classify_utterance(text) == expected


def test_hud_trim_caps_length():
    assert hud_trim("ok") == "ok"
    long = "x" * 500
    assert len(hud_trim(long)) <= 240
    assert hud_trim(long).endswith("…")


def test_ack_message_mentions_secondary():
    assert "Telegram" in ack_message("Telegram")
    assert ack_message(None)  # non-empty even without a secondary


def _channel(handler, **kw):
    return GlassesChannel(handler, allowed_user_ids=["alice"], **kw)


def test_quick_query_answered_synchronously():
    async def handler(msg):
        return "It's sunny."

    ch = _channel(handler)
    out = asyncio.run(ch.handle_utterance("alice", "what's the weather"))
    assert out == "It's sunny."


def test_long_task_acks_and_delivers_to_secondary():
    delivered = []

    async def handler(msg):
        return "Here is your 2000-word article."

    async def deliver(user_id, text):
        delivered.append((user_id, text))

    # Run background tasks inline so the test is deterministic.
    spawned = []

    def spawn(coro):
        spawned.append(coro)
        return coro

    ch = _channel(handler, secondary_channel="Telegram", deliver=deliver, spawn=spawn)

    async def go():
        ack = await ch.handle_utterance("alice", "write an article about EVs")
        assert "working on it" in ack.lower()
        assert "Telegram" in ack
        # The background task was scheduled; run it.
        for coro in spawned:
            await coro

    asyncio.run(go())
    assert delivered == [("alice", "Here is your 2000-word article.")]


def test_slow_quick_query_falls_back_to_ack_then_run():
    calls = 0
    release = asyncio.Event()

    async def slow_handler(msg):
        nonlocal calls
        calls += 1
        await release.wait()
        return "late answer"

    delivered = []

    async def deliver(user_id, text):
        delivered.append((user_id, text))

    spawned = []

    ch = _channel(
        slow_handler, deadline_s=0.01, secondary_channel="Telegram",
        deliver=deliver, spawn=lambda c: spawned.append(c),
    )

    async def go():
        out = await ch.handle_utterance("alice", "what is the meaning of life")
        # The quick path timed out -> acked, and a background delivery was scheduled.
        assert "working on it" in out.lower()
        assert len(spawned) == 1
        assert calls == 1
        release.set()
        await spawned[0]

    asyncio.run(go())
    assert calls == 1
    assert delivered == [("alice", "late answer")]


def test_unauthorized_user_refused():
    async def handler(msg):  # pragma: no cover -- must not run
        return "secret"

    ch = _channel(handler)
    out = asyncio.run(ch.handle_utterance("mallory", "write code"))
    assert "not authorized" in out.lower()


def test_requires_allowlist():
    with pytest.raises(ValueError):
        GlassesChannel(lambda m: None, allowed_user_ids=[])
