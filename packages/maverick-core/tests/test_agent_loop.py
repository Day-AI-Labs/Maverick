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
    async def test_budget_checked_before_llm_call(self, ctx, make_llm_response):
        # Already over the dollar cap: the loop must refuse to spend another
        # call, not check only after the response lands.
        ctx.budget.dollars = ctx.budget.max_dollars + 1.0
        calls = {"n": 0}

        class _TrackingLLM:
            async def complete_async(self, **kwargs):
                calls["n"] += 1
                return make_llm_response(text="FINAL: should never run")

        ctx.llm = _TrackingLLM()
        agent = Agent(ctx=ctx, role="researcher", brief="...")
        result = await agent.run()
        assert calls["n"] == 0  # LLM never invoked
        assert result.final is None
        assert "$" in (result.error or "")

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
    async def test_killswitch_halts_at_turn_boundary(
        self, ctx, fake_llm, make_llm_response, monkeypatch,
    ):
        """`maverick halt` / the dashboard Halt button / the HALT file must
        actually stop a run: the loop calls killswitch.check() at the top of
        each turn, so an armed halt aborts BEFORE the next LLM call (no
        further spend). Regression for the wholly-unwired killswitch."""
        from maverick import killswitch
        # halt() best-effort writes a HALT audit event; neutralize it so the
        # test doesn't touch the real ~/.maverick/audit dir.
        monkeypatch.setattr("maverick.audit.record", lambda *a, **k: None)
        fake_llm.scripted = [
            make_llm_response(
                text="acting",
                tool_calls=[ToolCall(id="t1", name="shell",
                                     input={"cmd": "echo hi"})],
            ),
        ]
        killswitch.halt("test halt")
        try:
            agent = Agent(ctx=ctx, role="researcher", brief="should be halted")
            result = await agent.run()
        finally:
            killswitch.clear()
        assert result.error is not None and "halted" in result.error.lower()
        # Halt is checked before the LLM call, so the model was never invoked.
        assert fake_llm.calls == []

    @pytest.mark.asyncio
    async def test_killswitch_halts_before_tool_dispatch(
        self, ctx, make_llm_response, monkeypatch,
    ):
        """A halt that arrives DURING the LLM call (user hits Halt mid-think)
        is honoured at the tool-call boundary: the returned tool never runs."""
        from maverick import killswitch
        monkeypatch.setattr("maverick.audit.record", lambda *a, **k: None)

        class _HaltingLLM:
            model = "fake:test"

            def __init__(self):
                self.calls = []

            async def complete_async(self, **kwargs):
                self.calls.append(kwargs)
                killswitch.halt("halt during think")
                return make_llm_response(
                    text="acting",
                    tool_calls=[ToolCall(id="t1", name="shell",
                                         input={"cmd": "rm -rf /"})],
                )

        ctx.llm = _HaltingLLM()
        try:
            agent = Agent(ctx=ctx, role="coder", brief="...")
            result = await agent.run()
        finally:
            killswitch.clear()
        assert result.error is not None and "halted" in result.error.lower()
        # The LLM was called exactly once; the dangerous tool was never run.
        assert len(ctx.llm.calls) == 1

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

    @pytest.mark.asyncio
    async def test_final_with_interleaved_tools_does_not_merge_thinking(
        self, ctx,
    ):
        """May 28 fix #2: a turn that emits a FINAL: marker ALONGSIDE
        interleaved tool_use must not corrupt the thinking sequence when
        it is re-sent on a revision pass.

        The loop drops the tool attempt (FINAL wins) but the original
        tool_use blocks separated two thinking blocks. Dropping the
        tool_use while keeping the thinking would make those blocks
        CONSECUTIVE, which Anthropic rejects on the next request:
          messages.N.content.M: `thinking`/`redacted_thinking` blocks in
          the latest assistant message cannot be modified.
        The model never emits consecutive thinking blocks, so no echoed
        assistant message may contain a run of 2+ of them."""
        import copy as _copy

        class _RecordingLLM:
            # Deep-copies messages at call time; the loop mutates the live
            # list afterward, so a shallow ref would not show call-time state.
            def __init__(self, scripted):
                self.scripted = list(scripted)
                self.calls = []
                self.model = "claude-opus-4-7"

            async def complete_async(self, *, system, messages, tools=None,
                                     budget=None, max_tokens=4096,
                                     thinking_budget=None, model=None):
                self.calls.append({"messages": _copy.deepcopy(messages)})
                if self.scripted:
                    return self.scripted.pop(0)
                return LLMResponse(text="FINAL: done", thinking=None,
                                   tool_calls=[], stop_reason="end_turn")

        interleaved = [
            {"type": "thinking", "thinking": "plan A", "signature": "sigA"},
            {"type": "tool_use", "id": "t1", "name": "shell",
             "input": {"cmd": "echo one"}},
            {"type": "thinking", "thinking": "plan B", "signature": "sigB"},
            {"type": "tool_use", "id": "t2", "name": "shell",
             "input": {"cmd": "echo two"}},
            {"type": "text", "text": "FINAL: first answer"},
        ]
        reject = '{"confidence":0.1,"accepts":false,"critique":"no","issues":["x"]}'
        ctx.llm = _RecordingLLM([
            # turn 1: FINAL + interleaved tool_use (stop_reason tool_use)
            LLMResponse(
                text="FINAL: first answer", thinking=None,
                tool_calls=[
                    ToolCall(id="t1", name="shell", input={"cmd": "echo one"}),
                    ToolCall(id="t2", name="shell", input={"cmd": "echo two"}),
                ],
                stop_reason="tool_use",
                content_blocks=_copy.deepcopy(interleaved),
            ),
            LLMResponse(text=reject, thinking=None, tool_calls=[],
                        stop_reason="end_turn"),                  # verifier #1
            LLMResponse(text="FINAL: revised answer", thinking=None,
                        tool_calls=[], stop_reason="end_turn"),   # turn 2
            LLMResponse(text=reject, thinking=None, tool_calls=[],
                        stop_reason="end_turn"),                  # verifier #2
        ])
        # Orchestrator at depth 0 with a goal_id runs the verifier, whose
        # rejection forces the loop to CONTINUE and re-send turn 1.
        agent = Agent(ctx=ctx, role="orchestrator", brief="build a thing")
        result = await agent.run()
        # The verifier rejected both attempts, so the answer is accepted on
        # the one-revision cap but wrapped in an honest "couldn't fully
        # verify" caveat. The answer body itself is preserved verbatim.
        assert result.final.endswith("revised answer")
        assert "could not fully verify" in result.final

        def _max_thinking_run(content) -> int:
            longest = run = 0
            if not isinstance(content, list):
                return 0
            for b in content:
                if isinstance(b, dict) and b.get("type") in (
                        "thinking", "redacted_thinking"):
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            return longest

        # The revision pass must have happened (turn1 + verifier + re-send).
        assert len(ctx.llm.calls) >= 3, "FINAL+reject+continue path not exercised"
        # No echoed assistant message anywhere may contain consecutive
        # thinking blocks — that is the exact corruption Anthropic rejects.
        for call in ctx.llm.calls:
            for m in call["messages"]:
                if m.get("role") == "assistant":
                    assert _max_thinking_run(m.get("content")) <= 1, (
                        "consecutive thinking blocks in echoed assistant "
                        f"message: {m.get('content')}"
                    )


class TestMemoryInLoop:
    """Cross-session memory wired into the loop's system prompt (A3)."""

    def test_memory_index_injected_at_root(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_MEMORY_DIR", str(tmp_path / "mem"))
        from maverick.tools.memory import memory
        memory().fn({"command": "create", "path": "conventions.md",
                     "file_text": "always run the linter"})
        root = Agent(ctx=ctx, role="orchestrator", brief="ship the feature")
        assert "Your long-term memory" in root.system
        assert "conventions.md" in root.system
        # A deep worker keeps lean context -> no memory index injected.
        worker = Agent(ctx=ctx, role="researcher", brief="sub", depth=1)
        assert "Your long-term memory" not in worker.system

    def test_empty_memory_leaves_prompt_unchanged(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_MEMORY_DIR", str(tmp_path / "empty"))
        root = Agent(ctx=ctx, role="orchestrator", brief="x")
        assert "Your long-term memory" not in root.system  # empty -> no injection

    def test_memory_tool_is_advertised_in_the_prompt(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_MEMORY_DIR", str(tmp_path / "m"))
        # Even with empty memory, the agent is told it HAS a memory tool.
        worker = Agent(ctx=ctx, role="researcher", brief="x", depth=1)
        assert "`memory`" in worker.system


class TestLoopGuard:
    """Repeated-identical-failure guard in the loop (long-horizon robustness)."""

    def test_repeated_identical_failure_nudges(self, ctx):
        from maverick import agent as agent_mod
        a = Agent(ctx=ctx, role="researcher", brief="x")
        thr = agent_mod._LOOP_GUARD_THRESHOLD
        notes = [a._loop_guard_note("shell", {"cmd": "boom"}, "ERROR: nope")
                 for _ in range(thr)]
        assert all(n == "" for n in notes[:thr - 1])   # below threshold: silent
        assert "[loop-guard]" in notes[-1]             # at threshold: nudge
        assert str(thr) in notes[-1]                   # reports the streak count

    def test_success_resets_the_streak(self, ctx):
        a = Agent(ctx=ctx, role="researcher", brief="x")
        a._loop_guard_note("shell", {"cmd": "x"}, "ERROR: a")
        a._loop_guard_note("shell", {"cmd": "x"}, "all good")  # success resets
        # Streak restarted, so the very next failure is well below threshold.
        assert a._loop_guard_note("shell", {"cmd": "x"}, "ERROR: a") == ""

    def test_distinct_calls_have_independent_streaks(self, ctx):
        from maverick import agent as agent_mod
        a = Agent(ctx=ctx, role="researcher", brief="x")
        for _ in range(agent_mod._LOOP_GUARD_THRESHOLD):
            a._loop_guard_note("shell", {"cmd": "A"}, "ERROR")
        # Different args are tracked separately -> no nudge on their first fail.
        assert a._loop_guard_note("shell", {"cmd": "B"}, "ERROR") == ""

    def test_can_be_disabled(self, ctx, monkeypatch):
        from maverick import agent as agent_mod
        monkeypatch.setattr(agent_mod, "_LOOP_GUARD_ENABLED", False)
        a = Agent(ctx=ctx, role="researcher", brief="x")
        for _ in range(agent_mod._LOOP_GUARD_THRESHOLD + 2):
            assert a._loop_guard_note("shell", {"cmd": "x"}, "ERROR") == ""

    @pytest.mark.asyncio
    async def test_run_tool_appends_note_after_the_framed_block(self, ctx, monkeypatch):
        from maverick import agent as agent_mod

        async def _boom(name, args):
            return "ERROR: boom"

        a = Agent(ctx=ctx, role="researcher", brief="x")
        monkeypatch.setattr(a.tools, "run", _boom)
        outs = [await a._run_tool("shell", {"cmd": "x"})
                for _ in range(agent_mod._LOOP_GUARD_THRESHOLD)]
        assert "[loop-guard]" not in outs[0]
        assert "[loop-guard]" in outs[-1]
        # The raw error is preserved inside the frame; the nudge is appended
        # OUTSIDE it (trusted loop-control guidance, not tool data).
        assert "ERROR: boom" in outs[-1]
        assert outs[-1].index("</tool_output") < outs[-1].index("[loop-guard]")


class TestToolFailureClassification:
    """is_error + per-step score must see PAST the <tool_output> frame.

    Regression: tool results are wrapped in a `<tool_output …>` security frame,
    so a leading-`ERROR` check on the framed string was always false -- is_error
    was never set on a failed tool, and every failure scored as a success."""

    def test_classifier_sees_through_the_frame(self):
        from maverick.agent import _tool_call_failed
        err = "<tool_output tool='shell' id=ab12>\nERROR: boom\n</tool_output ab12>"
        ok = "<tool_output tool='read_file' id=ab12>\nhello world\n</tool_output ab12>"
        assert _tool_call_failed(err) is True
        assert _tool_call_failed(ok) is False

    def test_classifier_on_unframed_errors_and_blocks(self):
        from maverick.agent import _tool_call_failed
        assert _tool_call_failed("ERROR: nope") is True
        assert _tool_call_failed("⚠ BLOCKED by Shield (high): x. Not executed.") is True
        assert _tool_call_failed("⚠ BLOCKED by hook. The tool was not executed.") is True
        assert _tool_call_failed("BLOCKED by Shield") is True
        assert _tool_call_failed("") is False
        assert _tool_call_failed("the answer is 42") is False

    def test_make_tool_result_flags_a_framed_error(self):
        from maverick.agent import Agent
        err = "<tool_output tool='shell' id=ab12>\nERROR: boom\n</tool_output ab12>"
        ok = "<tool_output tool='shell' id=ab12>\nall good\n</tool_output ab12>"
        assert Agent._make_tool_result("t1", err).get("is_error") is True
        assert "is_error" not in Agent._make_tool_result("t2", ok)
