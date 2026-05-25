"""Tool registry. Sync + async tools; same interface.

Each tool is a name + JSON schema + executor function. The executor may be a
sync function returning str, or an async coroutine returning str.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Union

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


def base_registry(world, sandbox) -> ToolRegistry:
    """Build the base tool set (no spawn tools)."""
    from .fs import read_file, write_file, list_dir
    from .shell import shell
    from .ask_user import ask_user

    reg = ToolRegistry()
    reg.register(read_file(sandbox))
    reg.register(write_file(sandbox))
    reg.register(list_dir(sandbox))
    reg.register(shell(sandbox))
    reg.register(ask_user(world))
    return reg


# Back-compat alias for older callers.
default_registry = base_registry
