"""MCP Streamable HTTP: SSE streaming path (progress + final response).

The blocking JSON path is covered by test_http_transport.py; here we
exercise the `Accept: text/event-stream` branch.
"""
import time

import pytest

pytest.importorskip("fastapi")

import maverick_mcp.http_transport as ht  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from maverick_mcp.server import MCPServer  # noqa: E402


def _client(monkeypatch):
    monkeypatch.setenv("MAVERICK_MCP_TOKEN", "test-token")
    return TestClient(ht.build_app(MCPServer()))


_AUTH = {"Authorization": "Bearer test-token"}
_SSE = {**_AUTH, "Accept": "text/event-stream"}


def test_sse_streams_final_result(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
    })
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    # The final JSON-RPC response is delivered as an SSE `data:` event.
    assert "data:" in body
    assert '"result"' in body
    assert "maverick_start" in body


def test_blocking_path_when_sse_not_requested(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_AUTH, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
    })
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "result" in resp.json()


def test_sse_emits_progress_with_token(monkeypatch):
    # A slow dispatch + tiny heartbeat guarantees at least one progress
    # event before the final result.
    monkeypatch.setenv("MAVERICK_MCP_SSE_HEARTBEAT", "0.05")

    def _slow_dispatch(server, method, params):
        time.sleep(0.3)
        return {"ok": True}

    monkeypatch.setattr(ht, "_dispatch", _slow_dispatch)
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"_meta": {"progressToken": "tok-1"}},
    })
    assert resp.status_code == 200
    body = resp.text
    assert "notifications/progress" in body
    assert "tok-1" in body
    # final result still arrives after the progress events
    assert '"ok"' in body


def test_sse_no_progress_without_token(monkeypatch):
    monkeypatch.setenv("MAVERICK_MCP_SSE_HEARTBEAT", "0.05")

    def _slow_dispatch(server, method, params):
        time.sleep(0.2)
        return {"ok": True}

    monkeypatch.setattr(ht, "_dispatch", _slow_dispatch)
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {},
    })
    assert resp.status_code == 200
    body = resp.text
    assert "notifications/progress" not in body
    assert '"ok"' in body


def test_sse_rejects_oversized_progress_token(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"_meta": {"progressToken": "x" * 129}},
    })
    assert resp.status_code == 400
    assert "progressToken" in resp.text


def test_sse_rejects_non_scalar_progress_token(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 11, "method": "tools/call",
        "params": {"_meta": {"progressToken": ["tok"]}},
    })
    assert resp.status_code == 400
    assert "progressToken" in resp.text


def test_sse_caps_progress_events(monkeypatch):
    monkeypatch.setenv("MAVERICK_MCP_SSE_HEARTBEAT", "0.01")
    monkeypatch.setenv("MAVERICK_MCP_SSE_MAX_PROGRESS_EVENTS", "2")

    def _slow_dispatch(server, method, params):
        time.sleep(0.08)
        return {"ok": True}

    monkeypatch.setattr(ht, "_dispatch", _slow_dispatch)
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 12, "method": "tools/call",
        "params": {"_meta": {"progressToken": "tok-capped"}},
    })
    assert resp.status_code == 200
    body = resp.text
    assert body.count("notifications/progress") == 2
    assert '"ok"' in body


def test_sse_streams_error_as_event(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/mcp", headers=_SSE, json={
        "jsonrpc": "2.0", "id": 9, "method": "no/such/method",
    })
    assert resp.status_code == 200
    body = resp.text
    assert '"error"' in body
    assert "-32601" in body


def test_heartbeat_seconds_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_MCP_SSE_HEARTBEAT", "0.5")
    assert ht._heartbeat_seconds() == 0.5
    monkeypatch.setenv("MAVERICK_MCP_SSE_HEARTBEAT", "garbage")
    assert ht._heartbeat_seconds() == 15.0


def test_max_progress_events_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_MCP_SSE_MAX_PROGRESS_EVENTS", "3")
    assert ht._max_progress_events() == 3
    monkeypatch.setenv("MAVERICK_MCP_SSE_MAX_PROGRESS_EVENTS", "-1")
    assert ht._max_progress_events() == 0
    monkeypatch.setenv("MAVERICK_MCP_SSE_MAX_PROGRESS_EVENTS", "garbage")
    assert ht._max_progress_events() == 240
