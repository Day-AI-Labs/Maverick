"""Agent loop tests using the FakeLLM fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.agent import Agent, AgentResult
from maverick.blackboard import Blackboard
from maverick.budget import Budget, BudgetExceeded
from maverick.llm import LLMResponse, ToolCall
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
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
        max_depth=2,
        use_skills=False,
    )


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_final_parsing_returns_answer(self, ctx, fake_llm, make_llm_response):
        fake_llm.scripted = [make_llm_response(text="FINAL: the answer is 42")]
        agent = Agent(ctx=ctx, role="researcher", brief="compute the answer")
        result = await agent.run()
        assert isinstance(result, AgentResult)
        assert result.final == "the answer is 42"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_ask_user_marks_blocked(self, ctx, fake_llm, make_llm_response):
        fake_llm.scripted = [
            make_llm_response(
                text="I need more info.",
                tool_calls=[ToolCall(id="t1", name="ask_user",
                                     input={"question": "which dates?"})],
            ),
        ]
        agent = Agent(ctx=ctx, role="orchestrator",
                      brief="plan something only the user can answer")
        result = await agent.run()
        assert result.blocked_on_user is True
        assert result.final is None

    @pytest.mark.asyncio
    async def test_empty_response_yields_error(self, ctx, fake_llm, make_llm_response):
        fake_llm.scripted = [make_llm_response(text="", tool_calls=[])]
        agent = Agent(ctx=ctx, role="researcher", brief="trivial")
        result = await agent.run()
        assert result.error == "empty response with no tools"

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_error(self, ctx, fake_llm, make_llm_response):
        ctx.budget.input_tokens = ctx.budget.max_input_tokens - 1
        class _BoomLLM:
            async def complete_async(self, **kwargs):
                raise BudgetExceeded("out of money")
        ctx.llm = _BoomLLM()
        agent = Agent(ctx=ctx, role="researcher", brief="...")
        result = await agent.run()
        assert "out of money" in (result.error or "")

    @pytest.mark.asyncio
    async def test_max_steps_hit(self, ctx, fake_llm, make_llm_response):
        fake_llm.scripted = [
            make_llm_response(
                text="taking action",
                tool_calls=[ToolCall(id="t1", name="shell",
                                     input={"cmd": "echo hi"})],
            ),
        ]
        agent = Agent(
            ctx=ctx, role="researcher", brief="infinite loop", max_steps=1,
        )
        result = await agent.run()
        assert result.error is not None and "max_steps" in result.error

    @pytest.mark.asyncio
    async def test_shield_blocks_tool_call(self, ctx, fake_llm, make_llm_response):
        class _BlockingShield:
            def scan_tool_call(self, name, args):
                from maverick_shield import ShieldVerdict
                return ShieldVerdict.block("high", "test block")
        ctx.shield = _BlockingShield()
        fake_llm.scripted = [
            make_llm_response(
                text="using shell",
                tool_calls=[ToolCall(id="t1", name="shell",
                                     input={"cmd": "ls"})],
            ),
            make_llm_response(text="FINAL: blocked, gave up"),
        ]
        agent = Agent(ctx=ctx, role="coder", brief="...")
        result = await agent.run()
        observations = [e for e in ctx.blackboard.entries if e.kind == "observation"]
        assert any("BLOCKED" in o.content for o in observations)
        assert result.final == "blocked, gave up"

    @pytest.mark.asyncio
    async def test_interleaved_thinking_order_preserved_in_history(
        self, ctx, fake_llm,
    ):
        """May 28 fix: the echoed assistant turn must preserve the
        model's ORIGINAL block order. The old bucket-by-type rebuild
        hoisted all thinking before all tool_use, which Anthropic
        rejects on interleaved Opus 4.7 turns ("thinking blocks in the
        latest assistant message cannot be modified")."""
        interleaved = [
            {"type": "thinking", "thinking": "plan A", "signature": "sigA"},
            {"type": "tool_use", "id": "t1", "name": "shell",
             "input": {"cmd": "echo one"}},
            {"type": "thinking", "thinking": "plan B", "signature": "sigB"},
            {"type": "tool_use", "id": "t2", "name": "shell",
             "input": {"cmd": "echo two"}},
        ]
        fake_llm.scripted = [
            LLMResponse(
                text="", thinking=None,
                tool_calls=[
                    ToolCall(id="t1", name="shell", input={"cmd": "echo one"}),
                    ToolCall(id="t2", name="shell", input={"cmd": "echo two"}),
                ],
                stop_reason="tool_use",
                content_blocks=interleaved,
            ),
            LLMResponse(
                text="FINAL: done", thinking=None, tool_calls=[],
                stop_reason="end_turn",
            ),
        ]
        agent = Agent(ctx=ctx, role="coder", brief="do two things")
        result = await agent.run()
        assert result.final == "done"

        # Find turn-1's echoed assistant message across all recorded
        # calls (FINAL triggers an extra verifier call, so we can't
        # assume a fixed index). Its blocks must match the interleaved
        # order exactly — NOT all-thinking-then-all-tools.
        all_msgs = [m for call in fake_llm.calls for m in call["messages"]]
        turn1 = [
            m for m in all_msgs
            if m["role"] == "assistant"
            and any(isinstance(b, dict) and b.get("id") == "t1"
                    for b in m["content"])
        ]
        assert turn1, "turn-1 assistant message not found in echoed history"
        assert turn1[0]["content"] == interleaved
