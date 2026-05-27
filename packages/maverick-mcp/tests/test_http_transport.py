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
