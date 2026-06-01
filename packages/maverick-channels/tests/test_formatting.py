"""Channel rich-formatting helpers (Slack mrkdwn + Discord chunking).

Pure functions -- no platform SDK needed.
"""
from __future__ import annotations

from maverick_channels.formatting import (
    DISCORD_LIMIT,
    split_for_discord,
    to_slack_mrkdwn,
)


def test_slack_bold_and_links_and_headings():
    assert to_slack_mrkdwn("**bold**") == "*bold*"
    assert to_slack_mrkdwn("__also bold__") == "*also bold*"
    assert to_slack_mrkdwn("[docs](https://x.io/y)") == "<https://x.io/y|docs>"
    assert to_slack_mrkdwn("## Heading") == "*Heading*"


def test_slack_preserves_code_fences():
    src = "see **this**\n```\nx = a ** b  # not bold\n```\nand **that**"
    out = to_slack_mrkdwn(src)
    # Bold converted outside the fence...
    assert "see *this*" in out
    assert "and *that*" in out
    # ...but the code body (including the `**`) is untouched.
    assert "x = a ** b  # not bold" in out


def test_slack_empty_passthrough():
    assert to_slack_mrkdwn("") == ""


def test_discord_short_message_single_chunk():
    assert split_for_discord("hello") == ["hello"]
    assert split_for_discord("") == [""]


def test_discord_splits_long_message_under_limit():
    text = "\n".join(f"line {i}" for i in range(1000))  # well over 2000 chars
    chunks = split_for_discord(text)
    assert len(chunks) > 1
    assert all(len(c) <= DISCORD_LIMIT for c in chunks)
    # No content lost.
    assert "".join(chunks) == text


def test_discord_hard_splits_a_single_oversized_line():
    line = "x" * (DISCORD_LIMIT * 2 + 5)
    chunks = split_for_discord(line)
    assert all(len(c) <= DISCORD_LIMIT for c in chunks)
    assert "".join(chunks) == line
