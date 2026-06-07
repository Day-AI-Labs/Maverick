"""WebSocket tool (ROADMAP 2027 H2)."""
from __future__ import annotations

import asyncio

import pytest
from maverick.tools.websocket_tool import _check_url, websocket_tool


def test_check_url_rejects_bad_scheme():
    assert "ERROR" in _check_url("http://example.com")
    assert "ERROR" in _check_url("https://example.com")


def test_check_url_accepts_ws():
    assert _check_url("ws://example.com/socket") is None
    assert _check_url("wss://example.com/socket") is None


def test_run_blocks_ssrf_without_dep(monkeypatch):
    # link-local metadata host must be refused before importing websockets
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    out = asyncio.run(websocket_tool().fn({"url": "ws://169.254.169.254/x"}))
    assert "ERROR" in out and "SSRF" in out


def test_run_requires_url():
    out = asyncio.run(websocket_tool().fn({"url": ""}))
    assert out.startswith("ERROR")


def test_echo_roundtrip(monkeypatch):
    websockets = pytest.importorskip("websockets")
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")  # allow loopback

    async def scenario():
        async def handler(ws, *args):
            async for msg in ws:
                await ws.send("echo:" + msg)

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            return await websocket_tool().fn(
                {"url": f"ws://127.0.0.1:{port}", "message": "ping"})

    assert asyncio.run(scenario()) == "echo:ping"
