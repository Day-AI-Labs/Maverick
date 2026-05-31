"""MCP Streamable HTTP transport tests."""
from __future__ import annotations

import pytest


def _have_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_fastapi(), reason="fastapi not installed")
class TestHTTPTransport:
    def _client(self):
        from fastapi.testclient import TestClient

        from maverick_mcp.http_transport import build_app
        from maverick_mcp.server import MCPServer
        app = build_app(MCPServer())
        return TestClient(app)

    def test_a2a_agent_card_served_when_enabled(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_A2A_ENABLED", "1")
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Maverick"
        assert body["protocolVersion"] == "1.0"

    def test_initialize_returns_capabilities(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        }, headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert "result" in body
        assert "capabilities" in body["result"]

    def test_tools_call_runs_sync_asyncio_tool_without_loop_crash(self, monkeypatch):
        """Regression: the HTTP endpoint dispatched synchronously inside
        FastAPI's running loop, so maverick_start (run_goal_sync ->
        asyncio.run) crashed with 'asyncio.run() cannot be called from a
        running event loop'. The dispatch now runs in a worker thread."""
        import asyncio

        from maverick_mcp import server as srv

        async def _trivial():
            return "DONE: stub run"

        def _fake_start(self, args):
            # Mirror run_goal_sync's pattern (asyncio.run on a coroutine) --
            # exactly what crashed before the to_thread fix.
            return asyncio.run(_trivial())

        monkeypatch.setattr(srv.MCPServer, "_tool_start", _fake_start, raising=True)
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "maverick_start", "arguments": {"title": "hi"}},
        }, headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["isError"] is False, body
        assert "DONE: stub run" in body["result"]["content"][0]["text"]

    def test_skill_install_rejects_bare_local_path(self, monkeypatch):
        """The MCP skill-install must pass trusted_local=False so a network
        client can't read arbitrary host files via a bare local path."""
        from types import SimpleNamespace

        from maverick import skills as skills_mod
        captured: dict = {}

        def _fake_install(source, *, trusted_local=True):
            captured["trusted_local"] = trusted_local
            return SimpleNamespace(name="x", path="/tmp/x")

        monkeypatch.setattr(skills_mod, "install_skill", _fake_install)
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "maverick_skill_install",
                       "arguments": {"source": "/etc/passwd"}},
        }, headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status_code == 200, resp.text
        assert captured.get("trusted_local") is False

    def test_unknown_method_returns_jsonrpc_error(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "no/such/method",
            "params": {},
        }, headers={"Authorization": "Bearer s3cr3t"})
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == -32601

    def test_resources_list_works_over_http(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "resources/list",
            "params": {},
        }, headers={"Authorization": "Bearer s3cr3t"})
        body = resp.json()
        assert "result" in body
        assert "resources" in body["result"]

    def test_bearer_required_when_token_set(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {},
        })
        assert resp.status_code == 401

    def test_bearer_accepted_when_correct(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {},
        }, headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status_code == 200

    def test_wrong_bearer_rejected(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {},
        }, headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_auth_required_when_token_unset(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_MCP_TOKEN", raising=False)
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {},
        })
        assert resp.status_code == 401

    def test_healthz_exempt(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["transport"] == "http"

    def test_notification_returns_204(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_MCP_TOKEN", "s3cr3t")
        client = self._client()
        resp = client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
            "params": {},
        }, headers={"Authorization": "Bearer s3cr3t"})
        # No "id" -> notification -> 204
        assert resp.status_code == 204
