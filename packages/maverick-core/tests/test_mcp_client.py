"""MCP client tests."""
from __future__ import annotations

import asyncio
import json

import pytest
from maverick.mcp_client import (
    MCPClient,
    MCPClientError,
    MCPServerSpec,
    _content_to_str,
    load_mcp_specs_from_config,
)


class TestMCPServerSpec:
    def test_from_config_basic(self):
        spec = MCPServerSpec.from_config("fs", {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        })
        assert spec.name == "fs"
        assert spec.command == "npx"
        assert spec.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        assert spec.env == {}

    def test_from_config_with_env(self):
        spec = MCPServerSpec.from_config("gh", {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xyz"},
        })
        assert spec.env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xyz"}


class TestContentToStr:
    def test_string_passthrough(self):
        assert _content_to_str("hello") == "hello"

    def test_text_blocks_flattened(self):
        blocks = [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ]
        assert _content_to_str(blocks) == "line 1\nline 2"

    def test_non_text_blocks_json_serialized(self):
        blocks = [{"type": "image", "url": "http://x"}]
        # Non-text blocks fall through to JSON for round-trip preservation.
        out = _content_to_str(blocks)
        assert "image" in out

    def test_text_resource_surfaces_its_text(self):
        # An embedded text resource reads as its contents, not a JSON dump.
        blocks = [{"type": "resource",
                   "resource": {"uri": "file:///x", "text": "hello from file"}}]
        assert _content_to_str(blocks) == "hello from file"

    def test_binary_resource_falls_back_to_json(self):
        # No `text` (a blob/uri) -> JSON so the uri isn't silently lost.
        blocks = [{"type": "resource",
                   "resource": {"uri": "file:///x", "blob": "QQ=="}}]
        out = _content_to_str(blocks)
        assert "file:///x" in out

    def test_none(self):
        assert _content_to_str(None) == ""


class TestLoadSpecsFromConfig:
    def test_no_mcp_servers_returns_empty(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[deploy]\ntarget = \"desktop\"\n")
        monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
        assert load_mcp_specs_from_config() == []

    def test_disabled_server_skipped(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[mcp_servers.fs]\n'
            'enabled = false\n'
            'command = "npx"\n'
            'args = ["-y", "x"]\n'
        )
        monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
        assert load_mcp_specs_from_config() == []

    def test_missing_command_skipped(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[mcp_servers.bad]\n'
            'args = ["-y"]\n'  # no `command`
        )
        monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
        assert load_mcp_specs_from_config() == []

    def test_enabled_server_loaded(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[mcp_servers.fs]\n'
            'command = "npx"\n'
            'args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]\n'
        )
        monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
        # Clear LRU cache by re-importing or re-running load_config.
        from maverick.config import load_config
        load_config.__wrapped__ if hasattr(load_config, "__wrapped__") else load_config
        specs = load_mcp_specs_from_config()
        assert len(specs) == 1
        assert specs[0].name == "fs"


class TestStartLogging:
    def test_start_log_redacts_args(self, monkeypatch, caplog):
        class DummyStderr:
            async def readline(self):
                return b""

        class DummyProc:
            returncode = None
            stdin = object()
            stdout = object()
            stderr = DummyStderr()

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return DummyProc()

        async def _fake_request(self, method, params):
            if method == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if method == "tools/list":
                return {"tools": []}
            return {}

        async def _fake_send_notification(self, method, params):
            return None

        monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(MCPClient, "_request", _fake_request)
        monkeypatch.setattr(MCPClient, "_notify", _fake_send_notification)
        spec = MCPServerSpec(
            name="pg",
            command="npx",
            args=["postgres://user:pass@db/prod", "--token=argv-secret"],
        )
        client = MCPClient(spec)

        caplog.set_level("INFO")
        import asyncio
        asyncio.run(client.start())

        msg = "\n".join(r.getMessage() for r in caplog.records)
        assert "argv-secret" not in msg
        assert "postgres://user:pass@db/prod" not in msg
        assert "args=2" in msg


class TestCallTool:
    """call_tool surfaces tool errors as exceptions (not an "ERROR:" string)
    and doesn't drop a server's structuredContent."""

    @staticmethod
    def _client_returning(monkeypatch, resp):
        async def fake_request(self, method, params):
            return resp
        monkeypatch.setattr(MCPClient, "_request", fake_request)
        return MCPClient(MCPServerSpec(name="x", command="true"))

    def test_is_error_raises(self, monkeypatch):
        c = self._client_returning(
            monkeypatch,
            {"isError": True, "content": [{"type": "text", "text": "boom"}]})
        with pytest.raises(MCPClientError) as ei:
            asyncio.run(c.call_tool("t", {}))
        assert "boom" in str(ei.value)

    def test_success_text_starting_with_error_is_not_an_error(self, monkeypatch):
        # The old "ERROR: " prefix made this verbatim success look like a
        # failure. It must now come back unchanged.
        c = self._client_returning(
            monkeypatch, {"content": [{"type": "text", "text": "ERROR: not really"}]})
        assert asyncio.run(c.call_tool("t", {})) == "ERROR: not really"

    def test_structured_only_result_falls_back_to_json(self, monkeypatch):
        # A server that returns only structuredContent (no text block) still
        # gets its data to the model instead of an empty string.
        c = self._client_returning(
            monkeypatch, {"content": [], "structuredContent": {"rows": 3}})
        assert json.loads(asyncio.run(c.call_tool("t", {}))) == {"rows": 3}

    def test_text_wins_when_both_present(self, monkeypatch):
        c = self._client_returning(
            monkeypatch,
            {"content": [{"type": "text", "text": "hi"}],
             "structuredContent": {"rows": 3}})
        assert asyncio.run(c.call_tool("t", {})) == "hi"


class TestTimeoutCancellation:
    """On a request timeout the client emits notifications/cancelled so the
    server stops working on an id it will never read a reply for."""

    def test_timeout_emits_cancelled_for_the_request_id(self, monkeypatch):
        sent: list[dict] = []

        async def fake_send(self, payload):
            sent.append(payload)

        async def never(self, expected_id):
            await asyncio.sleep(10)

        monkeypatch.setattr(MCPClient, "_check_alive", lambda self: None)
        monkeypatch.setattr(MCPClient, "_send", fake_send)
        monkeypatch.setattr(MCPClient, "_read_response", never)
        c = MCPClient(MCPServerSpec(name="x", command="true"), timeout=0.01)

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(c._request("tools/call", {"name": "t"}))

        cancels = [p for p in sent if p.get("method") == "notifications/cancelled"]
        assert len(cancels) == 1
        # The cancel must target the same id the timed-out request used (1).
        assert cancels[0]["params"] == {"requestId": 1, "reason": "client timeout"}
