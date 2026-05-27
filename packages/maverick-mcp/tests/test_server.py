"""MCP server smoke + protocol tests.

v0.1.6: handle_tools_call now RAISES `_ProtocolError` for unknown tool /
missing required args (per MCP spec -- protocol errors must come back as
JSON-RPC `-32602`, not `isError`). Tests assert the exception is raised
and carries the right code. The `isError` envelope is only for tool
*execution* failures (e.g., the tool raised mid-call).
"""
from __future__ import annotations

import pytest

from maverick_mcp.server import (
    PROTOCOL_VERSION,
    TOOLS,
    MCPServer,
    _ProtocolError,
)


class TestTools:
    def test_all_tools_have_required_fields(self):
        for t in TOOLS:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
            assert t["inputSchema"].get("type") == "object"

    def test_known_tool_names(self):
        names = {t["name"] for t in TOOLS}
        for expected in (
            "maverick_start",
            "maverick_status",
            "maverick_skill_install",
            "maverick_fact_set",
        ):
            assert expected in names


class TestProtocol:
    def test_initialize_response_shape(self):
        s = MCPServer()
        out = s.handle_initialize({})
        assert out["protocolVersion"] == PROTOCOL_VERSION
        assert out["serverInfo"]["name"] == "maverick"
        assert "capabilities" in out

    def test_tools_list_returns_full_catalog(self):
        s = MCPServer()
        out = s.handle_tools_list({})
        assert len(out["tools"]) == len(TOOLS)

    def test_unknown_tool_raises_protocol_error(self):
        """Unknown tool -> JSON-RPC -32602, not isError envelope."""
        s = MCPServer()
        with pytest.raises(_ProtocolError) as excinfo:
            s.handle_tools_call({"name": "does_not_exist", "arguments": {}})
        assert excinfo.value.code == -32602
        assert "unknown tool" in excinfo.value.message

    def test_missing_required_arg_raises_protocol_error(self):
        """Missing required arg -> JSON-RPC -32602."""
        s = MCPServer()
        # maverick_answer requires question_id + answer
        with pytest.raises(_ProtocolError) as excinfo:
            s.handle_tools_call({"name": "maverick_answer", "arguments": {}})
        assert excinfo.value.code == -32602
        assert "question_id" in excinfo.value.message
        assert "answer" in excinfo.value.message

    def test_tool_execution_failure_returns_isError_envelope(self):
        """Tool that raises mid-execution -> isError (not protocol error).

        maverick_facts_get touches WorldModel and would normally succeed;
        we'd need to mock it to force a raise. Skip the full path test and
        just verify the contract via _dispatch_tool returning isError when
        dispatch raises.
        """
        s = MCPServer()
        # All registered names dispatch normally. Force an exception
        # by passing a name the dispatch can find but the tool raises on.
        # maverick_answer with bad question_id type -> int() raises.
        out = s.handle_tools_call({
            "name": "maverick_answer",
            "arguments": {"question_id": "not-a-number", "answer": "x"},
        })
        assert out["isError"] is True
        assert "text" in out["content"][0]


class TestProtocol2025_11_25:
    """Tests for the new MCP 2025-11-25 primitives."""

    def test_initialize_advertises_new_capabilities(self):
        s = MCPServer()
        out = s.handle_initialize({"protocolVersion": "2025-11-25"})
        assert "resources" in out["capabilities"]
        assert "prompts" in out["capabilities"]
        assert "elicitation" in out["capabilities"]

    def test_initialize_negotiates_down_for_old_clients(self):
        s = MCPServer()
        out = s.handle_initialize({"protocolVersion": "2024-11-05"})
        assert out["protocolVersion"] == "2024-11-05"

    def test_initialize_uses_current_version_for_new_clients(self):
        s = MCPServer()
        out = s.handle_initialize({"protocolVersion": "2025-11-25"})
        assert out["protocolVersion"] == "2025-11-25"

    def test_resources_list_includes_static_namespaces(self):
        s = MCPServer()
        out = s.handle_resources_list({})
        uris = {r["uri"] for r in out["resources"]}
        assert "maverick://goals" in uris
        assert "maverick://skills" in uris

    def test_resources_read_rejects_unsupported_scheme(self):
        s = MCPServer()
        with pytest.raises(_ProtocolError):
            s.handle_resources_read({"uri": "file:///etc/passwd"})

    def test_prompts_list_returns_three_templates(self):
        s = MCPServer()
        out = s.handle_prompts_list({})
        names = {p["name"] for p in out["prompts"]}
        assert "research_topic" in names
        assert "draft_message" in names
        assert "compare_options" in names

    def test_prompts_get_renders_with_args(self):
        s = MCPServer()
        out = s.handle_prompts_get({
            "name": "research_topic",
            "arguments": {"topic": "fusion reactors", "depth": "deep"},
        })
        text = out["messages"][0]["content"]["text"]
        assert "fusion reactors" in text
        assert "deep" in text

    def test_prompts_get_unknown_raises(self):
        s = MCPServer()
        with pytest.raises(_ProtocolError):
            s.handle_prompts_get({"name": "nonexistent", "arguments": {}})
