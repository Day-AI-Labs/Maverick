"""A budget/wall-clock exhaustion must give the helpful 'raise the cap'
message, not a generic 'ran into an error'.

The agent swallows BudgetExceeded into result.error (so spawned children
return gracefully), which meant the orchestrator's nice budget message was
unreachable for the common case -- the user saw a generic error with no hint
to raise --max-dollars.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


@pytest.mark.asyncio
async def test_budget_exhaustion_gives_helpful_message(tmp_path: Path, fake_llm):
    world = WorldModel(tmp_path / "world.db")
    gid = world.create_goal("expensive goal", "")
    bud = Budget(max_dollars=0.01)
    # Push spend over the cap directly (bypassing record_tokens' own check)
    # so the agent's first budget.check() trips -- no LLM call needed.
    with bud._lock:
        bud.dollars = 5.0

    out = await run_goal(
        fake_llm, world, bud, gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )

    assert "hit your spending or time limit" in out
    assert "--max-dollars" in out
    assert "ran into an error" not in out
    # The message reports spend AGAINST the configured cap, not spend alone, so
    # the user can see how far over they went and what the limit was (#598).
    assert "$5.00 of $0.01 cap" in out
    assert world.get_goal(gid).status == "blocked"
