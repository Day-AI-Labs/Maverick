"""PRM step-scoring + early abandonment in the agent loop.

Default backend is NullPRM, so scoring is skipped and the loop is
unchanged. With MAVERICK_PRM=heuristic, each step is scored; a trajectory
whose trailing-window promise stays below MAVERICK_PRM_FLOOR is abandoned
before it burns the whole budget.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.llm import LLMResponse, ToolCall
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
from maverick.tools import Tool
from maverick.world_model import WorldModel


@pytest.fixture
def ctx(tmp_path: Path, fake_llm):
    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("test goal", "")
    return SwarmContext(
        llm=fake_llm,
        world=world,
        budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(),
        sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id,
        max_depth=1,
        use_skills=False,
    )


def _erroring_tool() -> Tool:
    def fn(args: dict) -> str:
        return "ERROR: boom"

    return Tool(
        name="boom",
        description="always errors",
        input_schema={"type": "object", "properties": {}},
        fn=fn,
    )


def _call_boom() -> LLMResponse:
    return LLMResponse(
        text="trying",
        thinking=None,
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="b", name="boom", input={})],
    )


class TestPrmInactiveByDefault:
    @pytest.mark.asyncio
    async def test_null_prm_does_not_abandon(self, ctx, fake_llm, monkeypatch):
        monkeypatch.delenv("MAVERICK_PRM", raising=False)
        # Many erroring steps, then a FINAL. With NullPRM the loop must
        # run to the FINAL, never abandoning.
        fake_llm.scripted = [_call_boom() for _ in range(5)] + [
            LLMResponse(text="FINAL: done anyway", thinking=None,
                        stop_reason="end_turn", tool_calls=[]),
        ]
        agent = Agent(ctx=ctx, role="researcher", brief="x", max_steps=10)
        agent.tools.register(_erroring_tool())
        result = await agent.run()
        assert result.final == "done anyway"
        # No PRM posts on the blackboard.
        assert not any(e.kind == "prm" for e in ctx.blackboard.entries)


class TestPrmEarlyAbandon:
    @pytest.mark.asyncio
    async def test_heuristic_prm_abandons_doomed_trajectory(
        self, ctx, fake_llm, monkeypatch,
    ):
        monkeypatch.setenv("MAVERICK_PRM", "heuristic")
        monkeypatch.setenv("MAVERICK_PRM_WINDOW", "2")
        monkeypatch.setenv("MAVERICK_PRM_FLOOR", "-0.3")
        # Heuristic PRM scores an erroring step promise=-0.5. Two in a row
        # average -0.5 < -0.3 -> abandon on step index 1 (the 2nd step).
        fake_llm.scripted = [_call_boom() for _ in range(10)]
        agent = Agent(ctx=ctx, role="coder", brief="x", max_steps=10)
        agent.tools.register(_erroring_tool())
        result = await agent.run()
        assert result.error is not None
        assert "abandoned by PRM" in result.error
        # It abandoned EARLY: far fewer than max_steps LLM calls.
        assert len(fake_llm.calls) <= 3
        # PRM scores were recorded.
        assert any(e.kind == "prm" for e in ctx.blackboard.entries)

    @pytest.mark.asyncio
    async def test_prm_active_but_progress_keeps_running(
        self, ctx, fake_llm, monkeypatch,
    ):
        monkeypatch.setenv("MAVERICK_PRM", "heuristic")
        monkeypatch.setenv("MAVERICK_PRM_WINDOW", "2")
        monkeypatch.setenv("MAVERICK_PRM_FLOOR", "-0.3")

        # A succeeding tool keeps promise positive (0.6), so no abandon.
        def ok_fn(args: dict) -> str:
            return "fine"

        ok = Tool(name="ok", description="ok",
                  input_schema={"type": "object", "properties": {}}, fn=ok_fn)
        fake_llm.scripted = [
            LLMResponse(text="t", thinking=None, stop_reason="tool_use",
                        tool_calls=[ToolCall(id="o", name="ok", input={})]),
            LLMResponse(text="t", thinking=None, stop_reason="tool_use",
                        tool_calls=[ToolCall(id="o2", name="ok", input={})]),
            LLMResponse(text="FINAL: completed", thinking=None,
                        stop_reason="end_turn", tool_calls=[]),
        ]
        agent = Agent(ctx=ctx, role="coder", brief="x", max_steps=10)
        agent.tools.register(ok)
        result = await agent.run()
        assert result.final == "completed"
