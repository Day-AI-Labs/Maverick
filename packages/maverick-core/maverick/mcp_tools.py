"""Build maverick Tool objects from an MCPClient's discovered tools.

External MCP server tools become `mcp_<server>__<tool>` in the agent's
tool registry. The agent calls them just like any other tool; under
the hood we route to the MCPClient and return the response text.

Kept in its own module to avoid a circular import between tools/ and
mcp_client.
"""
from __future__ import annotations

import logging

from .mcp_client import MCPClient
from .tools import Tool

log = logging.getLogger(__name__)


def tools_from_mcp(client: MCPClient) -> list[Tool]:
    """Return a Tool per MCP-exposed tool, namespaced by server.

    Council finding (Tier 0): MCP tool descriptions and inputSchema
    fields were rendered into the agent's tool catalog verbatim, so a
    hostile MCP server could put attack instructions in a description
    that the LLM would treat as authoritative. Each description is now
    run through Shield.scan_input; tools that fail are silently dropped
    with a warning log.
    """
    out: list[Tool] = []
    shield = _try_shield()
    for spec in client.tools:
        name = spec.get("name")
        if not name:
            continue
        if not _spec_passes_shield(name, spec, shield):
            log.warning(
                "mcp tool %s.%s rejected by Shield; not registering",
                client.spec.name, name,
            )
            continue
        prefixed = f"mcp_{client.spec.name}__{name}"
        out.append(_build_tool(client, prefixed, name, spec))
    return out


def _try_shield():
    try:
        from maverick_shield import Shield  # type: ignore
        return Shield.from_config()
    except ImportError:
        return None


def _spec_passes_shield(name: str, spec: dict, shield) -> bool:
    if shield is None:
        return True
    description = spec.get("description", "") or ""
    payload = f"tool: {name}\ndescription: {description}"
    try:
        v = shield.scan_input(payload)
        return bool(v.allowed)
    except Exception:  # pragma: no cover
        return True


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
