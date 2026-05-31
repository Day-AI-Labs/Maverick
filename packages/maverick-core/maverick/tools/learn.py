"""The ``learn_capability`` tool: close a capability gap mid-run.

Bound to the calling agent (like the spawn tools) so it can mutate the
LIVE tool registry — a capability acquired here is in the tool catalog
the model sees on its NEXT turn, no restart required.

Ops:
  - search          : find existing skills / MCP servers / plugins in the
                      catalog that match a need, plus already-loaded tools.
  - acquire_skill   : install a catalog skill by name (hash-verified) and
                      return its steps so they're usable immediately.
  - add_mcp_server  : persist + hot-start an MCP server; its tools register
                      live as ``mcp_<server>__<tool>``.
  - create_tool     : GENERATE a Python tool from a spec, validate it, and
                      register it live (full-autonomy; gated by settings).
  - find_api        : guidance for driving an arbitrary REST API via the
                      built-in ``openapi_runner`` tool.

Gated entirely by ``self_learning.enabled()``; the kernel never registers
this tool otherwise.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import Tool

if TYPE_CHECKING:
    from ..agent import Agent


def _fmt_candidates(cands: list) -> str:
    if not cands:
        return "(no catalog matches)"
    lines = []
    for c in cands:
        summary = f" — {c.summary}" if c.summary else ""
        lines.append(f"  [{c.kind}] {c.name} (score {c.score:.2f}){summary}")
    return "\n".join(lines)


def learn_capability(agent: "Agent") -> Tool:
    ctx = agent.ctx

    async def fn(args: dict) -> str:
        from .. import self_learning

        op = (args.get("op") or "").strip()
        need = (args.get("need") or "").strip()
        st = self_learning.settings()
        bb = ctx.blackboard

        if op == "search":
            if not need:
                return "ERROR: 'need' is required for op=search"
            cands = self_learning.search_capabilities(need)
            local = sorted(
                t.name for t in agent.tools.all()
                if any(w in t.name.lower() or w in (t.description or "").lower()
                       for w in need.lower().split())
            )[:8]
            return (
                f"Catalog matches for {need!r}:\n{_fmt_candidates(cands)}\n\n"
                f"Already-loaded tools that may fit: {', '.join(local) or '(none)'}\n\n"
                "Next: acquire_skill <name> for a [skill]; add_mcp_server for an "
                "[mcp]; or create_tool to build a new one."
            )

        if op == "acquire_skill":
            name = (args.get("name") or "").strip()
            if not name:
                return "ERROR: 'name' (catalog skill name) is required"
            try:
                body = self_learning.acquire_skill(name, need=need)
            except Exception as e:
                return f"ERROR: could not install skill {name!r}: {e}"
            bb.post(agent.name, "observation", f"learned skill: {name}")
            return (
                f"Installed skill {name!r}. Use these steps now:\n\n{body}"
            )

        if op == "add_mcp_server":
            if not st.get("add_mcp_servers", True):
                return "ERROR: adding MCP servers is disabled ([self_learning] add_mcp_servers=false)"
            name = (args.get("name") or "").strip()
            command = (args.get("command") or "").strip()
            if not name or not command:
                return "ERROR: 'name' and 'command' are required for add_mcp_server"
            try:
                spec = self_learning.add_mcp_server(
                    name, command,
                    args=args.get("args") or [],
                    env=args.get("env") or {},
                    need=need,
                )
            except Exception as e:
                return f"ERROR: invalid MCP server spec: {e}"
            # Hot-start so the server's tools are live this turn.
            try:
                from ..mcp_client import MCPClient
                from ..mcp_tools import tools_from_mcp
                client = MCPClient(spec)
                await client.start()
            except Exception as e:
                return (
                    f"Saved [mcp_servers.{name}] to config, but it failed to "
                    f"start now ({e}). It will be retried on the next run."
                )
            registered = []
            for t in tools_from_mcp(client):
                agent.tools.register(t)
                registered.append(t.name)
            ctx.mcp_clients.append(client)  # children spawned later inherit it
            bb.post(agent.name, "observation",
                    f"learned MCP server {name}: {len(registered)} tool(s)")
            return (
                f"MCP server {name!r} started. New tools available now: "
                f"{', '.join(registered) or '(none exposed)'}"
            )

        if op == "create_tool":
            if not st.get("create_tools", True):
                return "ERROR: tool creation is disabled ([self_learning] create_tools=false)"
            name = (args.get("name") or "").strip()
            spec = (args.get("spec") or need).strip()
            if not name or not spec:
                return "ERROR: 'name' and 'spec' (what the tool should do) are required"
            from ..llm import model_for_role
            try:
                resp = await ctx.llm.complete_async(
                    system=self_learning.TOOL_AUTHOR_SYSTEM,
                    messages=[{"role": "user", "content": (
                        f"Build a tool named {name!r}.\nIt should: {spec}"
                    )}],
                    budget=ctx.budget,
                    max_tokens=2048,
                    model=model_for_role("coder"),
                )
            except Exception as e:
                return f"ERROR: tool generation call failed: {e}"
            try:
                tool = self_learning.write_generated_tool(
                    name, resp.text or "", need=need or spec,
                )
            except Exception as e:
                return f"ERROR: generated tool was rejected: {e}"
            agent.tools.register(tool)
            bb.post(agent.name, "observation", f"created tool: {tool.name}")
            return (
                f"Created and registered tool {tool.name!r}. It is available "
                f"now and will persist for future runs.\nDescription: {tool.description}"
            )

        if op == "find_api":
            return (
                "Use the built-in `openapi_runner` tool to call any REST API "
                "from its OpenAPI spec without writing a new tool:\n"
                "  1. Find the API's OpenAPI/Swagger spec URL (web_search if enabled).\n"
                "  2. openapi_runner op=list_ops spec=<spec-url> to see operations.\n"
                "  3. openapi_runner op=call spec=<spec-url> op_id=<id> params={...} "
                "headers={...} for auth.\n"
                f"Need: {need or '(unspecified)'}"
            )

        return (
            "ERROR: unknown op. Use one of: search, acquire_skill, "
            "add_mcp_server, create_tool, find_api"
        )

    return Tool(
        name="learn_capability",
        description=(
            "Acquire a NEW capability when you lack the skill/tool/integration "
            "to do the task. op=search to find existing skills/MCP servers; "
            "op=acquire_skill to install one; op=add_mcp_server to wire in an "
            "external MCP server (hot-loaded); op=create_tool to generate a new "
            "tool from a description (persists for future runs); op=find_api to "
            "drive a REST API via openapi_runner. Prefer search before create."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "enum": [
                        "search", "acquire_skill", "add_mcp_server",
                        "create_tool", "find_api",
                    ],
                },
                "need": {
                    "type": "string",
                    "description": "The capability gap in plain language.",
                },
                "name": {
                    "type": "string",
                    "description": "Catalog skill name (acquire_skill), or id for "
                                   "the new MCP server / tool.",
                },
                "command": {"type": "string", "description": "add_mcp_server: server launch command."},
                "args": {"type": "array", "items": {"type": "string"},
                         "description": "add_mcp_server: command args."},
                "env": {"type": "object", "description": "add_mcp_server: env vars for the server."},
                "spec": {
                    "type": "string",
                    "description": "create_tool: detailed description of what the "
                                   "tool should do and its inputs/outputs.",
                },
            },
            "required": ["op"],
        },
        fn=fn,
    )
