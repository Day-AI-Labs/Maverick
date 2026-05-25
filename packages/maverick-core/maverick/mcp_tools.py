"""Build maverick Tool objects from an MCPClient's discovered tools.

External MCP server tools become `mcp_<server>__<tool>` in the agent's
tool registry. The agent calls them just like any other tool; under
the hood we route to the MCPClient and return the response text.

Kept in its own module to avoid a circular import between tools/ and
mcp_client.
"""
from __future__ import annotations

import logging
from typing import Any

from .mcp_client import MCPClient
from .tools import Tool

log = logging.getLogger(__name__)


def tools_from_mcp(client: MCPClient) -> list[Tool]:
    """Return a Tool per MCP-exposed tool, namespaced by server."""
    out: list[Tool] = []
    for spec in client.tools:
        name = spec.get("name")
        if not name:
            continue
        prefixed = f"mcp_{client.spec.name}__{name}"
        out.append(_build_tool(client, prefixed, name, spec))
    return out


def _build_tool(client: MCPClient, prefixed: str, original: str, spec: dict) -> Tool:
    description = spec.get("description", "") or "(no description)"
    schema = spec.get("inputSchema") or {"type": "object", "properties": {}}

    async def fn(args: dict) -> str:
        try:
            return await client.call_tool(original, args)
        except Exception as e:
            log.exception("mcp tool %s failed", prefixed)
            return f"ERROR: {type(e).__name__}: {e}"

    return Tool(
        name=prefixed,
        description=f"[mcp:{client.spec.name}] {description}",
        input_schema=schema,
        fn=fn,
    )
