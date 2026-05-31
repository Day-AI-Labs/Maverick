"""Spawn tools. Let any agent recursively launch sub-agents.

`spawn_subagent` blocks until the child returns. `spawn_swarm` runs many
children in parallel via asyncio.gather and returns their findings.

Both respect the swarm's max_depth and the shared budget.

v0.2 (council AI-safety review): added a fan-out anomaly cap. An agent
asking to spawn 50 siblings burns budget before refusal triggers.
``MAVERICK_MAX_SWARM_FANOUT`` (default 8) caps the per-call branching
factor. Excess agents are dropped with a warning posted to the
blackboard.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .._envparse import env_int
from . import Tool

if TYPE_CHECKING:
    from ..agent import Agent


MAX_SWARM_FANOUT = env_int("MAVERICK_MAX_SWARM_FANOUT", 8)


def spawn_subagent_tool(parent: "Agent") -> Tool:
    async def fn(args: dict) -> str:
        role = args["role"]
        task = args["task"]
        from ..agent import Agent

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"
        if not parent.ctx.try_reserve_spawns(1):
            return (
                f"ERROR: per-goal spawn cap ({parent.ctx.max_total_spawns}) reached"
            )

        # May 26 council fix (agent-loop audit #3): inherit max_steps
        # from the parent. Without this, sub-agents fall back to env
        # MAVERICK_MAX_STEPS or the 25 default — silently dropping the
        # operator's intent when the parent was constructed with a
        # specific max_steps value.
        child = Agent(
            ctx=parent.ctx,
            role=role,
            brief=task,
            depth=parent.depth + 1,
            parent=parent,
            max_steps=parent.max_steps,
        )
        result = await child.run()
        from ..hooks import HookEvent, emit as _emit_hook
        await _emit_hook(
            HookEvent.SUBAGENT_STOP,
            goal_id=parent.ctx.goal_id, agent_role=child.role,
            extra={"name": child.name, "final": result.final or ""},
        )
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

        # Cap per-call fan-out: an agent asking for 50 siblings on a
        # trivial sub-goal is almost always confused / under attack, and
        # the budget shouldn't bear the cost of refusing per-spawn.
        if len(agents_spec) > MAX_SWARM_FANOUT:
            parent.ctx.blackboard.post(
                parent.name, "error",
                f"swarm fan-out capped: requested {len(agents_spec)}, "
                f"max {MAX_SWARM_FANOUT}",
            )
            agents_spec = agents_spec[:MAX_SWARM_FANOUT]

        if not parent.ctx.try_reserve_spawns(len(agents_spec)):
            return (
                f"ERROR: per-goal spawn cap ({parent.ctx.max_total_spawns}) reached"
            )

        children = [
            Agent(
                ctx=parent.ctx,
                role=spec["role"],
                brief=spec["task"],
                depth=parent.depth + 1,
                parent=parent,
                max_steps=parent.max_steps,
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

        # SubagentStop hooks: one per child that completed without raising.
        from ..hooks import HookEvent, emit as _emit_hook
        for child, res in zip(children, results):
            if not isinstance(res, Exception):
                await _emit_hook(
                    HookEvent.SUBAGENT_STOP,
                    goal_id=parent.ctx.goal_id, agent_role=child.role,
                    extra={"name": child.name, "final": res.final or ""},
                )

        # Karpathy SOTA-review item: measure disagreement across the
        # children's FINAL answers and record it on the blackboard so
        # the orchestrator can decide whether to spend more compute
        # (re-spawn with adaptive_fanout) or trust the consensus.
        finals = [
            res.final for res in results
            if not isinstance(res, Exception) and res.final
        ]
        if len(finals) > 1:
            from ..disagreement import answer_entropy
            entropy = answer_entropy(finals)
            parent.ctx.blackboard.post(
                parent.name, "verify",
                f"swarm disagreement entropy={entropy:.3f} across {len(finals)} answers",
            )
            # Stamp on the context so the orchestrator's verify branch
            # and the donation selector can read it.
            try:
                parent.ctx.last_disagreement = entropy  # type: ignore[attr-defined]
            except Exception:
                pass

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
