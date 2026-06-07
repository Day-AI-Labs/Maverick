"""End-to-end orchestrator test: drive run_goal() with a scripted FakeLLM.

This is the highest-level test in the kernel — proves that:
  - the recursive agent loop, blackboard, world model, budget, sandbox,
    skill distill, and episode bookkeeping all integrate cleanly
  - the orchestrator persists goal status transitions correctly
    (pending -> active -> done / blocked)
  - blackboard posts mirror into `goal_events` so the dashboard can stream

The council called out that we had unit tests for every component but
nothing exercised the wire connecting them.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


@pytest.mark.asyncio
async def test_simple_final_answer_marks_goal_done(tmp_path: Path, fake_llm, make_llm_response):
    fake_llm.scripted = [
        make_llm_response(text="FINAL: the answer is 42"),
        # Wave 5: verifier runs on orchestrator's FINAL. Accept the answer.
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        # Skill distiller is called after FINAL; give it something terminal too.
        make_llm_response(text="FINAL: (no skill)"),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("compute the answer", "trivial")
    budget = Budget(max_dollars=1.0)

    out = await run_goal(
        llm=fake_llm,
        world=world,
        budget=budget,
        goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path),
        max_depth=1,
    )

    assert "DONE." in out
    assert "the answer is 42" in out

    goal = world.get_goal(gid)
    assert goal.status == "done"
    assert "the answer is 42" in (goal.result or "")

    # Episode was closed with success.
    eps = world.list_episodes()
    assert len(eps) == 1
    assert eps[0].outcome == "success"
    assert eps[0].ended_at is not None


@pytest.mark.asyncio
async def test_ask_user_pauses_goal_as_blocked(tmp_path: Path, fake_llm, make_llm_response):
    from maverick.llm import ToolCall
    fake_llm.scripted = [
        make_llm_response(
            text="I need clarification.",
            tool_calls=[ToolCall(id="t1", name="ask_user",
                                 input={"question": "Which dates?"})],
        ),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("plan a trip", "")
    budget = Budget(max_dollars=1.0)

    out = await run_goal(
        llm=fake_llm, world=world, budget=budget, goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )

    # Council UX fix: message is now sentence-case "Paused" not "PAUSED".
    assert "Paused" in out
    goal = world.get_goal(gid)
    assert goal.status == "blocked"
    qs = world.open_questions(gid)
    assert len(qs) == 1
    assert "Which dates?" in qs[0].question


@pytest.mark.asyncio
async def test_blackboard_posts_mirror_into_goal_events(tmp_path: Path, fake_llm, make_llm_response):
    """Live progress streaming depends on this."""
    fake_llm.scripted = [
        make_llm_response(text="FINAL: done"),
        # Wave 5 verifier call on orchestrator FINAL.
        make_llm_response(
            text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
        ),
        make_llm_response(text="FINAL: (no skill)"),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("emit events", "")
    budget = Budget(max_dollars=1.0)

    await run_goal(
        llm=fake_llm, world=world, budget=budget, goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )

    # Blackboard.attach_world ensures every post lands in goal_events.
    events = world.goal_events(gid)
    # At minimum the orchestrator agent should post its FINAL.
    assert len(events) >= 1
    kinds = {e.kind for e in events}
    # Some kind of "final" / "post" / "speak" arrives — don't pin the exact
    # string since the kernel can evolve, just the contract that *something*
    # gets emitted.
    assert kinds


@pytest.mark.asyncio
async def test_domain_build_failure_blocks_instead_of_falling_back(
    tmp_path: Path, monkeypatch, fake_llm,
):
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    (domains_dir / "broken.toml").write_text(
        'name = "broken"\n'
        'allow_tools = 123\n'
    )
    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(domains_dir))

    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("run in broken domain", "")
    budget = Budget(max_dollars=1.0)

    out = await run_goal(
        llm=fake_llm,
        world=world,
        budget=budget,
        goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path),
        max_depth=1,
        domain="broken",
    )

    assert "agent build failed" in out
    assert "Refusing to run without the requested domain capability envelope" in out
    assert fake_llm.calls == []
    goal = world.get_goal(gid)
    assert goal.status == "blocked"
    assert "agent build failed" in (goal.result or "")


@pytest.mark.asyncio
async def test_unknown_goal_returns_error_message(tmp_path: Path, fake_llm):
    world = WorldModel(path=tmp_path / "world.db")
    budget = Budget(max_dollars=1.0)

    out = await run_goal(
        llm=fake_llm, world=world, budget=budget, goal_id=99999,
        sandbox=LocalBackend(workdir=tmp_path),
    )
    assert "no such goal" in out
