"""MCPClient dispatcher: concurrent requests, cancel-on-timeout, structured
errors (#471).

Drives MCPClient with a fake asyncio subprocess so the request/response
cycle is exercised without spawning a real MCP server.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from maverick.mcp_client import MCPClient, MCPClientError, MCPServerSpec


class _FakeStdout:
    """An async stream of newline-delimited JSON lines fed by the test."""

    def __init__(self):
        self._q: asyncio.Queue[bytes] = asyncio.Queue()

    def feed(self, obj):
        self._q.put_nowait((json.dumps(obj) + "\n").encode())

    def feed_eof(self):
        self._q.put_nowait(b"")

    async def readline(self) -> bytes:
        return await self._q.get()


class _FakeStdin:
    def __init__(self, on_write):
        self._on_write = on_write

    def write(self, data: bytes):
        self._on_write(data)

    async def drain(self):
        return None


class _FakeStderr:
    async def readline(self) -> bytes:
        # Never produces output; block forever until cancelled.
        await asyncio.Event().wait()
        return b""


class _FakeProc:
    def __init__(self, stdout, on_write):
        self.stdout = stdout
        self.stdin = _FakeStdin(on_write)
        self.stderr = _FakeStderr()
        self.returncode = None

    def terminate(self): self.returncode = 0
    def kill(self): self.returncode = -9
    async def wait(self): return self.returncode


def _make_client(timeout=0.2):
    spec = MCPServerSpec(name="fake", command="/bin/true")
    client = MCPClient(spec, timeout=timeout)
    sent: list[dict] = []
    stdout = _FakeStdout()

    def on_write(data: bytes):
        for line in data.decode().splitlines():
            if line.strip():
                sent.append(json.loads(line))

    client._proc = _FakeProc(stdout, on_write)
    # Start the reader loop the way start() would (skip the real subprocess).
    client._reader_task = asyncio.ensure_future(client._read_loop())
    return client, stdout, sent


@pytest.mark.asyncio
async def test_concurrent_requests_resolve_by_id():
    client, stdout, sent = _make_client(timeout=2.0)
    try:
        # Fire two requests "concurrently" before answering either.
        t1 = asyncio.ensure_future(client._request("a/x", {}))
        t2 = asyncio.ensure_future(client._request("b/y", {}))
        await asyncio.sleep(0.01)  # let both register + send
        ids = [m["id"] for m in sent]
        assert len(ids) == 2 and ids[0] != ids[1]
        # Answer them OUT OF ORDER; each must resolve its own caller.
        stdout.feed({"jsonrpc": "2.0", "id": ids[1], "result": {"who": "second"}})
        stdout.feed({"jsonrpc": "2.0", "id": ids[0], "result": {"who": "first"}})
        r1, r2 = await asyncio.gather(t1, t2)
        assert r1 == {"who": "first"}
        assert r2 == {"who": "second"}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_timeout_raises_and_sends_cancel():
    client, stdout, sent = _make_client(timeout=0.05)
    try:
        with pytest.raises(MCPClientError, match="timed out"):
            await client._request("slow/call", {})
        # A cancelled notification for the timed-out request was sent.
        cancels = [m for m in sent if m.get("method") == "notifications/cancelled"]
        assert cancels, "expected a notifications/cancelled after timeout"
        assert cancels[0]["params"]["requestId"] == sent[0]["id"]
        # The future was unregistered so a late response is harmless.
        assert client._pending == {}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_late_response_after_timeout_is_ignored():
    client, stdout, sent = _make_client(timeout=0.05)
    try:
        with pytest.raises(MCPClientError):
            await client._request("slow/call", {})
        late_id = sent[0]["id"]
        # The server finally answers; the reader must not crash on it.
        stdout.feed({"jsonrpc": "2.0", "id": late_id, "result": {"late": True}})
        await asyncio.sleep(0.02)
        assert client._reader_task is not None and not client._reader_task.done()
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_call_tool_raises_on_iserror():
    client, stdout, sent = _make_client(timeout=2.0)
    try:
        t = asyncio.ensure_future(client.call_tool("dangerous", {}))
        await asyncio.sleep(0.01)
        rid = sent[0]["id"]
        stdout.feed({
            "jsonrpc": "2.0", "id": rid,
            "result": {"isError": True,
                       "content": [{"type": "text", "text": "boom"}]},
        })
        with pytest.raises(MCPClientError, match="returned an error"):
            await t
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_call_tool_success_starting_with_error_word():
    # A SUCCESSFUL tool whose text happens to start with 'ERROR:' must be
    # returned as-is, not treated as a failure (the whole point of #471 #3).
    client, stdout, sent = _make_client(timeout=2.0)
    try:
        t = asyncio.ensure_future(client.call_tool("grep", {}))
        await asyncio.sleep(0.01)
        rid = sent[0]["id"]
        stdout.feed({
            "jsonrpc": "2.0", "id": rid,
            "result": {"content": [{"type": "text",
                                    "text": "ERROR: log line matched"}]},
        })
        out = await t
        assert out == "ERROR: log line matched"
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_stop_fails_pending_awaiters():
    client, stdout, sent = _make_client(timeout=5.0)
    t = asyncio.ensure_future(client._request("never/answered", {}))
    await asyncio.sleep(0.01)
    await client.stop()
    with pytest.raises(MCPClientError):
        await t


@pytest.mark.asyncio
async def test_eof_fails_pending_awaiters():
    client, stdout, sent = _make_client(timeout=5.0)
    try:
        t = asyncio.ensure_future(client._request("pending", {}))
        await asyncio.sleep(0.01)
        stdout.feed_eof()
        with pytest.raises(MCPClientError, match="closed stdout"):
            await t
    finally:
        await client.stop()
