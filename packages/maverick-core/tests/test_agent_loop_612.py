"""#612 agent-loop audit: mid-dispatch budget trips must not orphan a
tool_use, and reserved spawn slots must be released when a child fails.

A `tool_use` block in an assistant message MUST be answered by a matching
`tool_result` in the immediately following user message, or Anthropic 400s
the next request. `budget.record_tool_call()` calls `check()` and can raise
`BudgetExceeded` *after* the assistant turn (with its tool_use blocks) is
already in the message history -- so the loop has to answer every pending
tool_use before it unwinds.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget, BudgetExceeded
from maverick.llm import LLMResponse, ToolCall
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
from maverick.world_model import WorldModel


def _assert_no_orphan_tool_use(messages: list[dict]) -> None:
    """Every tool_use id in an assistant message has a tool_result right after."""
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        tool_use_ids = [
            b["id"] for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        if not tool_use_ids:
            continue
        # The next message must answer all of them.
        assert i + 1 < len(messages), (
            f"assistant tool_use {tool_use_ids} has no following message"
        )
        nxt = messages[i + 1]
        assert nxt.get("role") == "user", f"tool_use {tool_use_ids} not answered"
        answered = {
            b["tool_use_id"] for b in nxt["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        }
        assert set(tool_use_ids) <= answered, (
            f"orphaned tool_use ids: {set(tool_use_ids) - answered}"
        )


class _CapturingLLM:
    """Records the (live) messages list it is handed each turn, so a test can
    inspect the history after the run unwinds."""

    model = "fake:test"

    def __init__(self, scripted: list[LLMResponse]):
        self.scripted = list(scripted)
        self.last_messages: list[dict] | None = None

    async def complete_async(self, *, system, messages, **kwargs) -> LLMResponse:
        self.last_messages = messages  # same object the loop mutates
        if self.scripted:
            return self.scripted.pop(0)
        return LLMResponse(
            text="FINAL: done", thinking=None, tool_calls=[],
            stop_reason="end_turn",
        )


def _ctx(tmp_path: Path, llm, **budget_kw) -> SwarmContext:
    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("test goal", "")
    return SwarmContext(
        llm=llm,
        world=world,
        budget=Budget(max_dollars=1.0, **budget_kw),
        blackboard=Blackboard(),
        sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id,
        max_depth=2,
        use_skills=False,
    )


class TestBudgetTripDoesNotOrphanToolUse:
    @pytest.mark.asyncio
    async def test_serial_path_budget_trip_answers_pending(self, tmp_path):
        # Two NON-parallel-safe tool calls in one turn -> serial path. Cap
        # tool calls at 1 so the SECOND record_tool_call() raises mid-turn,
        # after the first tool already produced a result.
        llm = _CapturingLLM([
            LLMResponse(
                text="acting",
                thinking=None,
                tool_calls=[
                    ToolCall(id="a", name="shell", input={"cmd": "echo 1"}),
                    ToolCall(id="b", name="shell", input={"cmd": "echo 2"}),
                ],
                stop_reason="tool_use",
            ),
        ])
        ctx = _ctx(tmp_path, llm, max_tool_calls=1)
        agent = Agent(ctx=ctx, role="researcher", brief="...")
        with pytest.raises(BudgetExceeded):
            await agent.run()
        assert llm.last_messages is not None
        _assert_no_orphan_tool_use(llm.last_messages)

    @pytest.mark.asyncio
    async def test_parallel_path_budget_trip_answers_pending(self, tmp_path):
        # Two parallel-safe reads -> parallel path records both up front; the
        # second record_tool_call() raises before any result is appended.
        f = tmp_path / "f.txt"
        f.write_text("hello")
        llm = _CapturingLLM([
            LLMResponse(
                text="reading",
                thinking=None,
                tool_calls=[
                    ToolCall(id="a", name="read_file", input={"path": "f.txt"}),
                    ToolCall(id="b", name="read_file", input={"path": "f.txt"}),
                ],
                stop_reason="tool_use",
            ),
        ])
        ctx = _ctx(tmp_path, llm, max_tool_calls=1)
        agent = Agent(ctx=ctx, role="researcher", brief="...")
        with pytest.raises(BudgetExceeded):
            await agent.run()
        assert llm.last_messages is not None
        _assert_no_orphan_tool_use(llm.last_messages)


class TestReleaseSpawns:
    def test_release_frees_capacity(self, tmp_path):
        ctx = _ctx(tmp_path, _CapturingLLM([]))
        ctx.max_total_spawns = 2
        assert ctx.try_reserve_spawns(2) is True
        # Cap reached: no more slots.
        assert ctx.try_reserve_spawns(1) is False
        # A child failed -> release its slot -> capacity frees up again.
        ctx.release_spawns(1)
        assert ctx.try_reserve_spawns(1) is True

    def test_release_clamps_at_zero(self, tmp_path):
        ctx = _ctx(tmp_path, _CapturingLLM([]))
        ctx.release_spawns(5)  # nothing reserved
        assert ctx._spawns_used == 0

    @pytest.mark.asyncio
    async def test_spawn_subagent_releases_on_child_raise(self, tmp_path):
        from maverick.tools.spawn import spawn_subagent_tool

        ctx = _ctx(tmp_path, _CapturingLLM([]))
        ctx.max_total_spawns = 1
        parent = Agent(ctx=ctx, role="orchestrator", brief="root")

        # Force the child's run() to raise (a genuine failure, not a return).
        async def _boom(self):
            raise RuntimeError("child blew up")

        from maverick.agent import Agent as _A
        orig_run = _A.run
        _A.run = _boom
        try:
            tool = spawn_subagent_tool(parent)
            with pytest.raises(RuntimeError):
                await tool.fn({"role": "researcher", "task": "do x"})
        finally:
            _A.run = orig_run

        # The failed child's reserved slot was returned.
        assert ctx._spawns_used == 0
        assert ctx.try_reserve_spawns(1) is True

    @pytest.mark.asyncio
    async def test_spawn_swarm_releases_failed_children_only(self, tmp_path):
        from maverick.tools.spawn import spawn_swarm_tool

        ctx = _ctx(tmp_path, _CapturingLLM([]))
        ctx.max_total_spawns = 4
        parent = Agent(ctx=ctx, role="orchestrator", brief="root")

        from maverick.agent import Agent as _A
        from maverick.agent import AgentResult
        calls = {"n": 0}

        async def _mixed(self):
            calls["n"] += 1
            # First child errors (raises), second returns a normal result.
            if calls["n"] == 1:
                raise RuntimeError("child 1 failed")
            return AgentResult(final="ok", role=self.role, name=self.name)

        orig_run = _A.run
        _A.run = _mixed
        try:
            tool = spawn_swarm_tool(parent)
            out = await tool.fn({"agents": [
                {"role": "researcher", "task": "a"},
                {"role": "researcher", "task": "b"},
            ]})
        finally:
            _A.run = orig_run

        assert "EXCEPTION" in out  # the raised child surfaced
        # 2 reserved, 1 failed -> only the failed slot released; the
        # successful child legitimately keeps its slot.
        assert ctx._spawns_used == 1
