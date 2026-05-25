"""Tool registry. Sync + async tools; same interface.

Each tool is a name + JSON schema + executor function. The executor may be a
sync function returning str, or an async coroutine returning str.

v0.1.2: ``base_registry`` accepts an optional list of MCPClient
instances. If provided, every tool the MCP servers expose is
registered as ``mcp_<server>__<tool>`` and routed through the
MCPClient. This is how Maverick consumes the wider MCP ecosystem.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

ToolFn = Callable[[dict[str, Any]], Union[str, Awaitable[str]]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_anthropic(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self._tools.values()]

    async def run(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool {name!r}"
        try:
            result = self._tools[name].fn(args)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"


def base_registry(world, sandbox, mcp_clients: Optional[list] = None) -> ToolRegistry:
    """Build the base tool set (no spawn tools).

    If ``mcp_clients`` is given, each one's discovered tools are
    registered as ``mcp_<server>__<tool>``.
    """
    from .ask_user import ask_user
    from .fs import list_dir, read_file, write_file
    from .shell import shell

    reg = ToolRegistry()
    reg.register(read_file(sandbox))
    reg.register(write_file(sandbox))
    reg.register(list_dir(sandbox))
    reg.register(shell(sandbox))
    reg.register(ask_user(world))

    if mcp_clients:
        from ..mcp_tools import tools_from_mcp
        for client in mcp_clients:
            for t in tools_from_mcp(client):
                reg.register(t)

    return reg


default_registry = base_registry
