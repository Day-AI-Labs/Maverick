"""Build maverick Tool objects from an MCPClient's discovered tools.

External MCP server tools become `mcp_<server>__<tool>` in the agent's
tool registry. The agent calls them just like any other tool; under
the hood we route to the MCPClient and return the response text.

Kept in its own module to avoid a circular import between tools/ and
mcp_client.
"""
from __future__ import annotations

import logging
import re

from .mcp_client import MCPClient
from .tools import Tool

log = logging.getLogger(__name__)

# A tool name comes from the external MCP server's `tools/list` response, so
# it is attacker-controlled if that server is hostile/compromised (the same
# threat MCPClient.pin_sha256 guards against). Constrain it to an identifier
# charset so it can't (a) inject newlines/control chars into log lines, or
# (b) smuggle the `__` namespace separator to collide with / shadow another
# server's `mcp_<server>__<tool>` entry in the registry. Matches the MCP
# spec's recommended tool-name shape.
_VALID_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_MAX_SCHEMA_SCAN_DEPTH = 64


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
        if not isinstance(name, str) or not _VALID_TOOL_NAME.fullmatch(name) or "__" in name:
            # %r escapes any control chars, so the rejection log itself can't
            # be used to forge log lines.
            log.warning(
                "mcp tool from %s rejected: invalid name %r "
                "(must match [A-Za-z0-9_.-], <=128 chars, no '__')",
                client.spec.name, name,
            )
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


def _collect_schema_strings(node, out: list[str], _depth: int = 0) -> bool:
    """Walk a JSON Schema dict and collect every string leaf.

    A hostile MCP server can put attack text in description / title /
    enum / examples inside nested properties; the agent sees those
    verbatim. Shield must inspect the full string-leaf set, not just
    the top-level description field. Returns ``False`` if the schema
    exceeds the bounded scan depth so callers can fail closed instead
    of exposing unscanned nested metadata to the model.
    """
    # Depth cap: the schema is parsed from a hostile MCP server's wire data,
    # so a ~990-deep nested object (which json.loads still accepts) would blow
    # the Python stack here (RecursionError) during connect. Real schemas are
    # shallow; fail closed past a generous bound rather than silently skipping
    # deeper strings that would still be sent to the model as tool metadata.
    if _depth > _MAX_SCHEMA_SCAN_DEPTH:
        return False
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and k in (
                "description", "title", "default", "pattern", "format",
            ):
                out.append(v)
            elif isinstance(v, (dict, list)):
                if not _collect_schema_strings(v, out, _depth + 1):
                    return False
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, (dict, list)) and not _collect_schema_strings(
                item, out, _depth + 1
            ):
                return False
    return True


def _spec_passes_shield(name: str, spec: dict, shield) -> bool:
    if shield is None:
        return True
    description = spec.get("description", "") or ""
    parts: list[str] = [f"tool: {name}", f"description: {description}"]
    schema = spec.get("inputSchema") or {}
    leaves: list[str] = []
    if not _collect_schema_strings(schema, leaves):
        log.warning(
            "mcp tool %r rejected: inputSchema exceeds scan depth %s",
            name,
            _MAX_SCHEMA_SCAN_DEPTH,
        )
        return False
    parts.extend(f"schema_text: {leaf}" for leaf in leaves)
    payload = "\n".join(parts)
    try:
        v = shield.scan_input(payload)
        return bool(v.allowed)
    except Exception as e:  # pragma: no cover
        # Fail-open per repo rules, but NOT silently: this is the chokepoint
        # that keeps a hostile MCP server's tool description/schema out of the
        # agent's catalog, so a scan error that lets it through must be logged.
        log.warning("mcp tool %r shield scan errored (fail-open): %s", name, e)
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
