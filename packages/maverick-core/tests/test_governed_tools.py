"""Governing enterprise-connector WRITES in the live tool path (opt-in).

A write is previewed + approval-gated against a standing operator approver (the
agent can't self-approve); reads pass through. Off by default leaves the
registry untouched.
"""
from __future__ import annotations

import asyncio

from maverick.governed_tools import (
    apply_governed_connectors,
    governance_enabled,
    wrap_connector_tool,
)
from maverick.tools import Tool, ToolRegistry

_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["get", "post", "put", "patch", "delete"]},
        "path": {"type": "string"},
        "confirm": {"type": "boolean"},
    },
    "required": ["op", "path"],
}


def _fake_tool(calls):
    def _fn(args):
        calls.append(dict(args))
        return f"DID {args.get('op')} {args.get('path')} confirm={args.get('confirm')}"
    return Tool(name="acme", description="Acme connector", input_schema=_SCHEMA, fn=_fn)



def _graphql_tool(calls):
    schema = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["query"]},
            "query": {"type": "string", "description": "GraphQL query or mutation."},
            "variables": {"type": "object"},
            "confirm": {"type": "boolean"},
        },
        "required": ["op", "query"],
    }

    def _fn(args):
        calls.append(dict(args))
        return f"GQL {args.get('op')} confirm={args.get('confirm')}"

    return Tool(name="monday", description="monday GraphQL", input_schema=schema, fn=_fn)


def _salesforce_tool(calls):
    schema = {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": ["soql", "record_create", "record_update", "record_delete"],
            },
            "sobject": {"type": "string"},
            "id": {"type": "string"},
            "fields": {"type": "object"},
            "confirm": {"type": "boolean"},
        },
        "required": ["op"],
    }

    def _fn(args):
        calls.append(dict(args))
        return f"SF {args.get('op')} {args.get('sobject')} confirm={args.get('confirm')}"

    return Tool(name="salesforce", description="Salesforce", input_schema=schema, fn=_fn)


class TestWrap:
    def test_read_passes_through(self):
        calls = []
        wrapped = wrap_connector_tool(_fake_tool(calls))
        out = wrapped.fn({"op": "get", "path": "/x"})
        assert "DID get /x" in out
        assert calls == [{"op": "get", "path": "/x"}]

    def test_write_without_approver_is_refused(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_GOVERNED_APPROVER", raising=False)
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["acme"], "approver": ""})
        calls = []
        wrapped = wrap_connector_tool(_fake_tool(calls))
        out = wrapped.fn({"op": "post", "path": "/accounts", "body": {"n": 1}})
        assert "REFUSED (governed)" in out
        assert "approver" in out
        assert calls == []  # the underlying write never ran

    def test_write_with_approver_commits(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_APPROVER", "ops@corp")
        calls = []
        wrapped = wrap_connector_tool(_fake_tool(calls))
        out = wrapped.fn({"op": "post", "path": "/accounts"})
        # The original write ran, with confirm forced true (approval cleared it).
        assert calls and calls[0]["confirm"] is True
        assert "DID post /accounts" in out

    def test_description_marks_governed(self):
        wrapped = wrap_connector_tool(_fake_tool([]))
        assert "governed" in wrapped.description

    def test_graphql_query_passes_through(self):
        calls = []
        wrapped = wrap_connector_tool(_graphql_tool(calls))
        out = wrapped.fn({"op": "query", "query": "query { boards { id } }"})
        assert "GQL query" in out
        assert calls == [{"op": "query", "query": "query { boards { id } }"}]

    def test_graphql_mutation_without_approver_is_refused(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_GOVERNED_APPROVER", raising=False)
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["monday"], "approver": ""})
        calls = []
        wrapped = wrap_connector_tool(_graphql_tool(calls))
        out = wrapped.fn({"op": "query", "query": "mutation { create_item { id } }", "confirm": True})
        assert "REFUSED (governed)" in out
        assert calls == []

    def test_graphql_mutation_with_approver_commits(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_APPROVER", "ops@corp")
        calls = []
        wrapped = wrap_connector_tool(_graphql_tool(calls))
        out = wrapped.fn({"op": "query", "query": "mutation { create_item { id } }"})
        assert "GQL query" in out
        assert calls and calls[0]["confirm"] is True


class TestApply:
    def test_off_by_default_is_noop(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_GOVERNED_CONNECTORS", raising=False)
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": False, "connectors": ["acme"], "approver": ""})
        reg = ToolRegistry()
        reg.register(_fake_tool([]))
        assert apply_governed_connectors(reg) == []
        assert "governed" not in reg.get("acme").description

    def test_enabled_wraps_configured(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "1")
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["acme"], "approver": "ops"})
        reg = ToolRegistry()
        reg.register(_fake_tool([]))
        assert apply_governed_connectors(reg) == ["acme"]
        assert "governed" in reg.get("acme").description

    def test_enabled_wraps_bespoke_salesforce_schema(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "1")
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["salesforce"], "approver": ""})
        calls = []
        reg = ToolRegistry()
        reg.register(_salesforce_tool(calls))
        assert apply_governed_connectors(reg) == ["salesforce"]
        assert "governed" in reg.get("salesforce").description
        out = reg.get("salesforce").fn({
            "op": "record_create",
            "sobject": "Account",
            "fields": {"Name": "poc"},
            "confirm": True,
        })
        assert "REFUSED (governed)" in out
        assert calls == []

    def test_skips_non_op_tool(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "1")
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["plain"], "approver": "ops"})
        reg = ToolRegistry()
        reg.register(Tool(name="plain", description="no op schema",
                          input_schema={"type": "object", "properties": {}}, fn=lambda a: "x"))
        assert apply_governed_connectors(reg) == []  # left ungoverned, not crashed

    def test_unknown_connector_skipped(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "1")
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_governed_connectors",
                            lambda: {"enable": True, "connectors": ["absent"], "approver": "ops"})
        assert apply_governed_connectors(ToolRegistry()) == []


class TestThroughRegistryRun:
    def test_governed_write_runs_via_registry(self, monkeypatch):
        # End-to-end through ToolRegistry.run (async), proving the wrapper's sync
        # fn executes correctly in the agent's tool-execution path.
        monkeypatch.setenv("MAVERICK_GOVERNED_APPROVER", "ops")
        calls = []
        reg = ToolRegistry()
        reg.register(wrap_connector_tool(_fake_tool(calls)))
        out = asyncio.run(reg.run("acme", {"op": "put", "path": "/x"}))
        assert "DID put /x" in out and calls[0]["confirm"] is True

    def test_governance_enabled_flag(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "1")
        assert governance_enabled() is True
        monkeypatch.setenv("MAVERICK_GOVERNED_CONNECTORS", "0")
        assert governance_enabled() is False
