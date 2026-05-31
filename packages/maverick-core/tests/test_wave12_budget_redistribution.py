"""Wave 12 (council F10c): best-of-N budget redistribution.

When an early attempt crashes (or finishes cheaply), the remaining
attempts get bigger per-attempt caps instead of leaving budget unused.
Prior behaviour fixed per_attempt = budget/N at the top of the loop
so a crashed attempt 0 wasted (N-1)/N of the parent budget.
"""
from __future__ import annotations

import pytest
from maverick.budget import Budget
from maverick.orchestrator import run_goal_best_of_n
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


@pytest.mark.asyncio
async def test_per_attempt_cap_grows_after_crash(tmp_path, monkeypatch):
    """Attempt 0 raises; attempt 1 should see a doubled cap."""
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    monkeypatch.setenv("MAVERICK_BON_LADDER", "model_a:0.3,model_b:0.7")
    caps_seen: list[float] = []

    async def fake_run_goal(llm, world, budget, goal_id, **kwargs):
        caps_seen.append(budget.max_dollars)
        if len(caps_seen) == 1:
            raise RuntimeError("simulated crash on attempt 0")
        return "FINAL:\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-x\n+y\n"

    monkeypatch.setattr(
        "maverick.orchestrator.run_goal", fake_run_goal,
    )

    world = WorldModel(path=tmp_path / "w.db")
    gid = world.create_goal("test", "test")
    budget = Budget(max_dollars=4.0, max_wall_seconds=120.0)

    await run_goal_best_of_n(
        llm=None, world=world, budget=budget,
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path),
        n=2,
    )

    assert len(caps_seen) == 2, "both attempts should have been invoked"
    # Attempt 0 saw $2.00 (4.0 / 2). It crashed without spending.
    assert abs(caps_seen[0] - 2.0) < 0.05
    # Attempt 1 should see the FULL remaining budget — ~$4.00 — because
    # crashed attempt 0 left budget.dollars at $0, and remaining = 4.0
    # with remaining_attempts = 1.
    assert caps_seen[1] > 3.5, (
        f"attempt 1 cap should have grown after crash; got {caps_seen[1]}"
    )


@pytest.mark.asyncio
async def test_per_attempt_cap_redistributes_after_cheap_finish(
    tmp_path, monkeypatch,
):
    """Attempt 0 finishes spending $0.10 of $1.50 cap. Attempt 1 (the
    LAST in the ladder) should see remaining ($3 - $0.10) ≈ $2.90 cap
    instead of the prior fixed $1.50."""
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    monkeypatch.setenv("MAVERICK_BON_LADDER", "model_a:0.3,model_b:0.7")
    caps_seen: list[float] = []

    async def fake_run_goal(llm, world, budget, goal_id, **kwargs):
        caps_seen.append(budget.max_dollars)
        # Spend $0.10 worth of fake input tokens.
        budget.dollars = 0.10
        return "FINAL:\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-x\n+y\n"

    monkeypatch.setattr(
        "maverick.orchestrator.run_goal", fake_run_goal,
    )

    world = WorldModel(path=tmp_path / "w.db")
    gid = world.create_goal("test", "test")
    budget = Budget(max_dollars=3.0, max_wall_seconds=120.0)

    await run_goal_best_of_n(
        llm=None, world=world, budget=budget,
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path),
        n=2,
    )

    assert len(caps_seen) >= 1
    # Attempt 0 sees half of parent ($1.50).
    assert abs(caps_seen[0] - 1.5) < 0.05
    if len(caps_seen) >= 2:
        # Attempt 1 should see the remaining budget (~$2.90 if attempt
        # 0 only spent $0.10 of its $1.50).
        assert caps_seen[1] > 2.0, (
            "attempt 1 cap did not grow after cheap finish; "
            f"got {caps_seen[1]}"
        )


@pytest.mark.asyncio
async def test_breaks_when_budget_exhausted(tmp_path, monkeypatch):
    """A runaway attempt that overshoots its cap should short-circuit
    subsequent attempts via the 95% parent-budget check + the
    remaining_dollars <= 0 guard."""
    monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
    monkeypatch.setenv("MAVERICK_BON_LADDER", "model_a:0.3,model_b:0.7,model_c:0.4")

    attempts_run = 0

    async def fake_run_goal(llm, world, budget, goal_id, **kwargs):
        nonlocal attempts_run
        attempts_run += 1
        # Simulate runaway: spend 2x the per-attempt cap so parent
        # budget climbs to its hard ceiling within the first 1-2 attempts.
        budget.dollars = budget.max_dollars * 2.0
        return "no patch here"

    monkeypatch.setattr(
        "maverick.orchestrator.run_goal", fake_run_goal,
    )

    world = WorldModel(path=tmp_path / "w.db")
    gid = world.create_goal("test", "test")
    budget = Budget(max_dollars=1.0, max_wall_seconds=120.0)

    await run_goal_best_of_n(
        llm=None, world=world, budget=budget,
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path),
        n=3,
    )

    # Two runaway attempts push parent over its $1.00 cap. The 3rd
    # attempt must short-circuit.
    assert attempts_run < 3, (
        f"runaway budget should short-circuit; ran {attempts_run} attempts"
    )
