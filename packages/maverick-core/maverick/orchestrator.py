"""Run a top-level goal through the swarm.

The orchestrator is just an Agent with role='orchestrator'. This module is
a thin convenience wrapper that wires up SwarmContext, runs the root agent,
verifies the result, and distills a skill on success.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from .agent import Agent
from .blackboard import Blackboard
from .budget import Budget, BudgetExceeded
from .llm import LLM
from .sandbox import LocalBackend
from .skills import distill
from .swarm import SwarmContext
from .world_model import WorldModel


async def run_goal(
    llm: LLM,
    world: WorldModel,
    budget: Budget,
    goal_id: int,
    sandbox: Optional[LocalBackend] = None,
    max_depth: int = 3,
) -> str:
    goal = world.get_goal(goal_id)
    if not goal:
        return f"no such goal: {goal_id}"

    world.set_goal_status(goal_id, "active")
    episode_id = world.start_episode(goal_id)
    blackboard = Blackboard()
    sandbox = sandbox or LocalBackend()

    ctx = SwarmContext(
        llm=llm,
        world=world,
        budget=budget,
        blackboard=blackboard,
        sandbox=sandbox,
        goal_id=goal_id,
        max_depth=max_depth,
    )

    facts = world.get_facts()
    facts_block = "\n".join(f"  {k}: {v}" for k, v in facts.items()) or "  (none)"
    brief = (
        f"Top-level goal: {goal.title}\n"
        f"Description: {goal.description or '(none)'}\n\n"
        f"Known facts about the user:\n{facts_block}\n\n"
        "Decompose into sub-tasks, spawn workers (parallel where possible), "
        "synthesize their findings, verify, and respond with FINAL:."
    )

    root = Agent(ctx=ctx, role="orchestrator", brief=brief, depth=0)

    try:
        result = await root.run()
    except BudgetExceeded as e:
        world.end_episode(episode_id, f"budget: {e}", "failure")
        world.set_goal_status(goal_id, "blocked", result=f"budget exceeded: {e}")
        return f"BUDGET EXCEEDED: {budget.summary()}"

    if result.blocked_on_user:
        world.end_episode(episode_id, "blocked awaiting user", "interrupted")
        world.set_goal_status(goal_id, "blocked")
        qs = world.open_questions(goal_id)
        return (
            f"PAUSED: waiting on user. {len(qs)} open question(s).\n"
            + "\n".join(f"  #{q.id}: {q.question}" for q in qs)
        )

    if result.error:
        world.end_episode(episode_id, result.error, "failure")
        world.set_goal_status(goal_id, "blocked", result=result.error)
        return f"FAILED: {result.error}\n[{budget.summary()}]"

    summary = result.final or "(no answer)"
    world.end_episode(episode_id, summary, "success")
    world.set_goal_status(goal_id, "done", result=summary)

    # Closed loop: distill the trajectory into a reusable skill.
    try:
        skill = distill(goal.title, summary, blackboard, llm, budget=budget)
        skill_note = f"\n\n[distilled skill: {skill.name}]" if skill else ""
    except BudgetExceeded:
        skill_note = "\n\n[skill distill skipped: budget]"
    except Exception as e:
        skill_note = f"\n\n[skill distill error: {e}]"

    return f"DONE.\n\n{summary}{skill_note}\n\n[{budget.summary()}]"


def run_goal_sync(*args, **kwargs) -> str:
    """Sync wrapper for callers that aren't running an event loop."""
    return asyncio.run(run_goal(*args, **kwargs))
