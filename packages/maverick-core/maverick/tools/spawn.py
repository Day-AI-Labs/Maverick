"""Spawn tools. Let any agent recursively launch sub-agents.

`spawn_subagent` blocks until the child returns. `spawn_swarm` runs many
children in parallel via asyncio.gather and returns their findings.

Both respect the swarm's max_depth and the shared budget.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from . import Tool

if TYPE_CHECKING:
    from ..agent import Agent


def spawn_subagent_tool(parent: "Agent") -> Tool:
    async def fn(args: dict) -> str:
        role = args["role"]
        task = args["task"]
        from ..agent import Agent

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"

        child = Agent(
            ctx=parent.ctx,
            role=role,
            brief=task,
            depth=parent.depth + 1,
            parent=parent,
        )
        result = await child.run()
        if result.final:
            return result.final
        if result.blocked_on_user:
            return "BLOCKED_ON_USER: child agent queued a question."
        return f"ERROR: child finished without final answer: {result.error or 'unknown'}"

    return Tool(
        name="spawn_subagent",
        description=(
            "Spawn a single specialist sub-agent and block until it returns. "
            "Use for a focused sub-task that needs its own context window. "
            "Role names: researcher, coder, writer, analyst, summarizer."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "task": {"type": "string", "description": "Concrete sub-goal for the child."},
            },
            "required": ["role", "task"],
        },
        fn=fn,
    )


def spawn_swarm_tool(parent: "Agent") -> Tool:
    async def fn(args: dict) -> str:
        from ..agent import Agent

        agents_spec = args["agents"]
        if not isinstance(agents_spec, list) or not agents_spec:
            return "ERROR: 'agents' must be a non-empty list"

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"

        children = [
            Agent(
                ctx=parent.ctx,
                role=spec["role"],
                brief=spec["task"],
                depth=parent.depth + 1,
                parent=parent,
            )
            for spec in agents_spec
        ]

        parent.ctx.blackboard.post(
            parent.name,
            "plan",
            f"spawning swarm of {len(children)}: "
            + ", ".join(f"{c.role}({c.name})" for c in children),
        )

        results = await asyncio.gather(*(c.run() for c in children), return_exceptions=True)

        parts: list[str] = []
        for child, res in zip(children, results):
            if isinstance(res, Exception):
                parts.append(f"[{child.role}/{child.name}] EXCEPTION: {res}")
            elif res.final:
                parts.append(f"[{child.role}/{child.name}] {res.final}")
            elif res.blocked_on_user:
                parts.append(f"[{child.role}/{child.name}] BLOCKED_ON_USER")
            else:
                parts.append(f"[{child.role}/{child.name}] ERROR: {res.error}")
        return "\n\n".join(parts)

    return Tool(
        name="spawn_swarm",
        description=(
            "Spawn many sub-agents in PARALLEL and wait for all of them. "
            "Use when sub-tasks are independent (e.g., research three topics simultaneously). "
            "Each entry: {role, task}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "task": {"type": "string"},
                        },
                        "required": ["role", "task"],
                    },
                    "minItems": 1,
                }
            },
            "required": ["agents"],
        },
        fn=fn,
    )
