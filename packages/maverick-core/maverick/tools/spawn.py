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

from .._envparse import env_float, env_int
from . import Tool

if TYPE_CHECKING:
    from ..agent import Agent


MAX_SWARM_FANOUT = env_int("MAVERICK_MAX_SWARM_FANOUT", 8)

# #611: budget reserved for the top-level goal's synthesis/write step. Once
# cumulative spend crosses (1 - this) of the cap, spawn_swarm refuses new
# fan-out so a recursive research swarm can't consume the budget needed to
# actually produce the answer. Mirrors agent.py's per-worker soft-stop.
SYNTHESIS_RESERVE = env_float("MAVERICK_SYNTHESIS_RESERVE", 0.25)

_RESERVED_CHILD_ROLES = {"orchestrator"}


def _reserved_role_error(role: object) -> str | None:
    """Reject child roles reserved for kernel-created agents.

    Spawn tool arguments are model-controlled, so role strings must not be able
    to claim privileged kernel identities used by containment logic.
    """
    if isinstance(role, str) and role.strip().lower() in _RESERVED_CHILD_ROLES:
        return (
            f"ERROR: role '{role}' is reserved for the root orchestrator and "
            "cannot be used for spawned agents"
        )
    return None


def _fanout_cap_for_depth(depth: int) -> int:
    """Per-call fan-out width, DECAYING with depth.

    A flat cap lets a recursive swarm explode geometrically (8 -> 64 -> 512).
    Halving the width each level keeps the deep tail bounded while still letting
    the root parallelize: depth 0 gets the full ``MAVERICK_MAX_SWARM_FANOUT``,
    each level below halves it (floor 1).
    """
    return max(1, MAX_SWARM_FANOUT >> max(0, depth))


def _synthesis_reserve_block(parent: Agent) -> str | None:
    """If spend has crossed the synthesis reserve, return a refusal string.

    #611: once cumulative spend crosses ``(1 - SYNTHESIS_RESERVE)`` of the cap,
    refuse new fan-out so the budget the top-level goal needs to write its
    answer isn't consumed by deeper spawning. Returns ``None`` when spawning is
    still allowed. Shared by ``spawn_swarm`` and ``spawn_subagent`` so a
    sequential spawn chain (notably from the depth-0 orchestrator, which the
    per-worker soft-stop in agent.py doesn't cover) can't bypass the reserve.
    """
    if SYNTHESIS_RESERVE <= 0:
        return None
    b = parent.ctx.budget
    if b.dollars < b.max_dollars * (1.0 - SYNTHESIS_RESERVE):
        return None
    parent.ctx.blackboard.post(
        parent.name, "plan",
        f"spawning paused: ${b.dollars:.2f}/${b.max_dollars:.2f} spent; "
        f"holding the final {SYNTHESIS_RESERVE:.0%} for synthesis",
    )
    return (
        f"ERROR: spawning paused to reserve budget for the final answer "
        f"(spent ${b.dollars:.2f} of ${b.max_dollars:.2f}; the last "
        f"{SYNTHESIS_RESERVE:.0%} is held for synthesis). Do NOT spawn "
        "more — synthesize and finalize with the findings you already have."
    )


def _child_capability(parent, role: str, depth: int):
    """A child's capability grant: the parent's, attenuated (never broadened)
    and re-bound to the child principal. ``None`` when the parent runs
    unrestricted (capability enforcement off), so this is a no-op by default.
    """
    cap = getattr(parent, "capability", None)
    if cap is None:
        return None
    return cap.attenuate(principal=f"agent:{role}-{depth}")


def spawn_subagent_tool(parent: Agent) -> Tool:
    async def fn(args: dict) -> str:
        role = args["role"]
        task = args["task"]
        from ..agent import Agent

        _blocked_role = _reserved_role_error(role)
        if _blocked_role is not None:
            return _blocked_role

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"
        _blocked = _synthesis_reserve_block(parent)
        if _blocked is not None:
            return _blocked
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
            capability=_child_capability(parent, role, parent.depth + 1),
        )
        # #612: a child that RAISES (budget/halt/unexpected error) never
        # consumed its slot productively -- give it back so transient child
        # failures don't permanently erode the per-goal spawn cap. A child
        # that returns (even with result.error set) legitimately ran, so we
        # keep its slot.
        try:
            result = await child.run()
        except BaseException:
            parent.ctx.release_spawns(1)
            raise
        from ..hooks import HookEvent
        from ..hooks import emit as _emit_hook
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
                "role": {
                    "type": "string",
                    "description": "Child specialist role; 'orchestrator' is reserved.",
                },
                "task": {"type": "string", "description": "Concrete sub-goal for the child."},
            },
            "required": ["role", "task"],
        },
        fn=fn,
    )


def spawn_swarm_tool(parent: Agent) -> Tool:
    async def fn(args: dict) -> str:
        from ..agent import Agent

        agents_spec = args["agents"]
        if not isinstance(agents_spec, list) or not agents_spec:
            return "ERROR: 'agents' must be a non-empty list"

        for spec in agents_spec:
            if not isinstance(spec, dict):
                return "ERROR: each swarm agent must be an object"
            _blocked_role = _reserved_role_error(spec.get("role"))
            if _blocked_role is not None:
                return _blocked_role

        if parent.depth + 1 > parent.ctx.max_depth:
            return f"ERROR: max depth {parent.ctx.max_depth} reached"

        # #611 synthesis reserve: once spend crosses (1 - reserve) of the cap,
        # refuse new fan-out so the budget the top-level goal needs to write its
        # answer isn't consumed by deeper research. Tell the agent to synthesize.
        _blocked = _synthesis_reserve_block(parent)
        if _blocked is not None:
            return _blocked

        # Cap per-call fan-out, DECAYING with depth so a recursive swarm can't
        # explode geometrically (#611). An agent asking for 50 siblings on a
        # trivial sub-goal is almost always confused / under attack too.
        cap = _fanout_cap_for_depth(parent.depth)
        if len(agents_spec) > cap:
            parent.ctx.blackboard.post(
                parent.name, "error",
                f"swarm fan-out capped: requested {len(agents_spec)}, "
                f"max {cap} at depth {parent.depth}",
            )
            agents_spec = agents_spec[:cap]

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
                capability=_child_capability(parent, spec["role"], parent.depth + 1),
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

        # #612: every child that RAISED never consumed its slot productively;
        # return those slots so a swarm with transient child failures doesn't
        # permanently erode the per-goal spawn cap. Children that returned
        # (even with result.error set) legitimately ran and keep their slot.
        n_failed = sum(1 for res in results if isinstance(res, BaseException))
        if n_failed:
            parent.ctx.release_spawns(n_failed)

        # A child hitting the budget cap or the killswitch is a STOP signal for
        # the whole swarm, not a per-child failure -- re-raise it instead of
        # folding it into the result string (matches agent.py's gather handler).
        from .. import killswitch as _ks
        from ..budget import BudgetExceeded as _BE
        for res in results:
            if isinstance(res, (_BE, _ks.Halted)):
                raise res

        # SubagentStop hooks: one per child that completed without raising.
        from ..hooks import HookEvent
        from ..hooks import emit as _emit_hook
        for child, res in zip(children, results):
            if not isinstance(res, Exception):
                await _emit_hook(
                    HookEvent.SUBAGENT_STOP,
                    goal_id=parent.ctx.goal_id, agent_role=child.role,
                    extra={"name": child.name, "final": res.final or ""},
                )

        # Karpathy SOTA-review item: measure disagreement across the
        # children's FINAL answers and record it on the blackboard so
        # the orchestrator can decide whether to spend more compute or
        # trust the consensus. (Acting on it -- adaptive re-fan-out -- is
        # a deferred follow-up; today this is an observability signal.)
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
                            "role": {
                                "type": "string",
                                "description": "Child specialist role; 'orchestrator' is reserved.",
                            },
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
