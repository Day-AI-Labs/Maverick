"""Issue #471: background reader/dispatcher so concurrent requests on one
MCPClient run in parallel instead of serializing on a single lock held across
the whole send->read cycle.

These tests drive an in-memory transport (no subprocess). The fake stdout is a
real asyncio.StreamReader the test feeds bytes into; the fake stdin records the
JSON-RPC the client sends so a test can reply to specific ids -- and reply OUT
OF ORDER -- to prove each response is correlated to the right caller.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from maverick.mcp_client import MCPClient, MCPClientError, MCPServerSpec


class _FakeStdin:
    """Records each line the client writes; exposes the parsed requests."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def write(self, data: bytes) -> None:
        for line in data.decode().splitlines():
            if line.strip():
                self.requests.append(json.loads(line))

    async def drain(self) -> None:
        return None


class _FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process.

    stdout is a real StreamReader so the client's reader loop awaits it exactly
    as it would the subprocess pipe; the test pushes framed JSON-RPC lines into
    it (in any order) and signals EOF via feed_eof().
    """

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = None

    @property
    def requests(self) -> list[dict]:
        return self.stdin.requests

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode or 0


def _make_client(timeout: float = 5.0) -> tuple[MCPClient, _FakeProc]:
    c = MCPClient(MCPServerSpec(name="x", command="true"), timeout=timeout)
    proc = _FakeProc()
    c._proc = proc  # type: ignore[assignment]
    return c, proc


def _feed_response(proc: _FakeProc, req_id: int, result: dict) -> None:
    line = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"
    proc.stdout.feed_data(line.encode())


def _id_for_method(proc: _FakeProc, method: str) -> int:
    for req in proc.requests:
        if req.get("method") == method:
            return req["id"]
    raise AssertionError(f"no request for method {method!r} was sent")


async def _wait_until_sent(proc: _FakeProc, n: int) -> None:
    """Yield until the client has written at least n requests to stdin."""
    for _ in range(1000):
        if len(proc.requests) >= n:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"only {len(proc.requests)} of {n} requests sent")


@pytest.mark.asyncio
async def test_out_of_order_responses_correlate_to_their_caller():
    c, proc = _make_client()

    t1 = asyncio.create_task(c._request("tools/call", {"name": "a"}))
    t2 = asyncio.create_task(c._request("tools/call", {"name": "b"}))
    await _wait_until_sent(proc, 2)

    # Both ids are on the wire concurrently (no serialization): if _request
    # still held the lock across the read, only one would have been sent.
    id_a = _id_for_method_by_arg(proc, "a")
    id_b = _id_for_method_by_arg(proc, "b")
    assert {id_a, id_b} == {1, 2}

    # Reply in REVERSE order: b before a.
    _feed_response(proc, id_b, {"who": "b"})
    _feed_response(proc, id_a, {"who": "a"})

    r1, r2 = await asyncio.gather(t1, t2)
    # Despite the out-of-order delivery, each caller gets ITS OWN result.
    assert r1 == {"who": "a"}
    assert r2 == {"who": "b"}


def _id_for_method_by_arg(proc: _FakeProc, name: str) -> int:
    for req in proc.requests:
        if req.get("params", {}).get("name") == name:
            return req["id"]
    raise AssertionError(f"no request with name {name!r}")


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_serialize():
    # If the two requests serialized, resolving them "together" would still
    # force the second to wait on the first's full round-trip. With per-id
    # futures, one feed of both responses resolves both immediately.
    c, proc = _make_client(timeout=5.0)

    t1 = asyncio.create_task(c._request("m1", {}))
    t2 = asyncio.create_task(c._request("m2", {}))
    await _wait_until_sent(proc, 2)

    id1 = _id_for_method(proc, "m1")
    id2 = _id_for_method(proc, "m2")
    _feed_response(proc, id1, {"n": 1})
    _feed_response(proc, id2, {"n": 2})

    # A tight timeout on the gather: both must complete without either waiting
    # on the other's timeout.
    r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)
    assert r1 == {"n": 1}
    assert r2 == {"n": 2}


@pytest.mark.asyncio
async def test_timed_out_request_deregisters_and_late_reply_is_dropped():
    c, proc = _make_client(timeout=5.0)

    # req A has a short personal timeout via wait_for wrapping; emulate by
    # giving the client a small timeout for this call only.
    c.timeout = 0.05
    ta = asyncio.create_task(c._request("slow", {"name": "a"}))
    await _wait_until_sent(proc, 1)
    id_a = _id_for_method(proc, "slow")

    with pytest.raises(asyncio.TimeoutError):
        await ta

    # The client should have emitted notifications/cancelled for id_a (#541).
    cancels = [r for r in proc.requests
               if r.get("method") == "notifications/cancelled"]
    assert len(cancels) == 1
    assert cancels[0]["params"]["requestId"] == id_a

    # Now start a concurrent in-flight request, then deliver the LATE reply for
    # the timed-out id_a. It must be dropped (id no longer registered) without
    # disturbing the live request.
    c.timeout = 5.0
    tb = asyncio.create_task(c._request("live", {"name": "b"}))
    for _ in range(1000):  # wait until the live request is on the wire
        if any(r.get("params", {}).get("name") == "b" for r in proc.requests):
            break
        await asyncio.sleep(0)
    id_b = _id_for_method_by_arg(proc, "b")

    # Late reply for the dead request first -- must be silently dropped.
    _feed_response(proc, id_a, {"who": "late-a"})
    # Then the real reply for the live request.
    _feed_response(proc, id_b, {"who": "b"})

    rb = await asyncio.wait_for(tb, timeout=1.0)
    assert rb == {"who": "b"}
    # Reader survived the dropped late reply (task still running, not crashed).
    assert c._reader_task is not None and not c._reader_task.done()

    await c.stop()


@pytest.mark.asyncio
async def test_eof_fails_all_pending_requests():
    c, proc = _make_client(timeout=5.0)

    t1 = asyncio.create_task(c._request("m1", {}))
    t2 = asyncio.create_task(c._request("m2", {}))
    await _wait_until_sent(proc, 2)

    # Transport closes (server died / stdout EOF) with both requests in flight.
    proc.stdout.feed_eof()

    # Neither caller hangs: both raise a clear error promptly.
    for t in (t1, t2):
        with pytest.raises(MCPClientError):
            await asyncio.wait_for(t, timeout=1.0)


@pytest.mark.asyncio
async def test_stop_fails_pending_requests():
    c, proc = _make_client(timeout=5.0)

    t1 = asyncio.create_task(c._request("m1", {}))
    await _wait_until_sent(proc, 1)

    await c.stop()

    with pytest.raises(MCPClientError):
        await asyncio.wait_for(t1, timeout=1.0)


@pytest.mark.asyncio
async def test_single_request_behaves_as_before():
    # A lone request must round-trip exactly as the old serialized path did.
    c, proc = _make_client(timeout=5.0)
    t = asyncio.create_task(c._request("solo", {}))
    await _wait_until_sent(proc, 1)
    _feed_response(proc, _id_for_method(proc, "solo"), {"ok": True})
    assert await asyncio.wait_for(t, timeout=1.0) == {"ok": True}
    await c.stop()
