"""CLI channel smoke test.

Stub stdin, drive a single roundtrip through CLIChannel, assert the
handler saw the right IncomingMessage and the reply hit stdout. This is
the cheapest end-to-end channel test we can run in CI (no network, no
process, no platform dependency).
"""
from __future__ import annotations

import asyncio
import io
import sys

import pytest
from maverick_channels import IncomingMessage
from maverick_channels.cli import CLIChannel


class _StdinOneShot(io.StringIO):
    """Yields one line then EOF so CLIChannel.start() returns cleanly."""

    def __init__(self, line: str):
        super().__init__(line + "\n")
        self._returned_line = False

    def readline(self) -> str:  # type: ignore[override]
        if self._returned_line:
            return ""  # EOF
        self._returned_line = True
        return super().readline()


@pytest.mark.asyncio
async def test_cli_roundtrip(monkeypatch, capsys):
    saw: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        saw.append(msg)
        return f"echo: {msg.text}"

    monkeypatch.setattr(sys, "stdin", _StdinOneShot("hello world"))

    channel = CLIChannel(handler=handler)
    await asyncio.wait_for(channel.start(), timeout=2.0)

    captured = capsys.readouterr()
    assert "echo: hello world" in captured.out

    assert len(saw) == 1
    assert saw[0].user_id == "local"
    assert saw[0].text == "hello world"
    assert saw[0].channel == "cli"


@pytest.mark.asyncio
async def test_cli_skips_blank_lines(monkeypatch, capsys):
    """Empty input lines are skipped, not dispatched."""
    saw: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        saw.append(msg)
        return "ok"

    class _Stdin(io.StringIO):
        def __init__(self):
            super().__init__("\nreal\n")
            self._fed = 0

        def readline(self):
            if self._fed == 0:
                self._fed = 1
                return "\n"
            if self._fed == 1:
                self._fed = 2
                return "real\n"
            return ""

    monkeypatch.setattr(sys, "stdin", _Stdin())

    channel = CLIChannel(handler=handler)
    await asyncio.wait_for(channel.start(), timeout=2.0)

    # Only the non-blank line dispatched.
    assert [m.text for m in saw] == ["real"]
