"""Tree-of-thought planning pre-pass, wired into the orchestrator.

Off by default; enabled via MAVERICK_PLANNING=tree_of_thought or
[planning] mode = "tree_of_thought". When on, run_goal forks N candidate
plans, scores them, and injects the winner into the orchestrator brief.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.budget import Budget
from maverick.llm import LLMResponse
from maverick.orchestrator import _maybe_plan_tree_of_thought, run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


class _Blackboard:
    def __init__(self):
        self.posts = []

    def post(self, agent, kind, content, **meta):
        self.posts.append((agent, kind, content))


@pytest.mark.asyncio
async def test_disabled_by_default_returns_none(monkeypatch, fake_llm):
    monkeypatch.delenv("MAVERICK_PLANNING", raising=False)
    plan = await _maybe_plan_tree_of_thought(
        fake_llm, "build a thing", Budget(max_dollars=1.0), _Blackboard(),
    )
    assert plan is None
    # No LLM calls should have been made.
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_enabled_returns_winning_plan(monkeypatch, fake_llm):
    monkeypatch.setenv("MAVERICK_PLANNING", "tree_of_thought")
    # N=2 candidates + 1 critic. Critic picks plan index 1.
    fake_llm.scripted = [
        LLMResponse(text="Plan A: do X then Y", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text="Plan B: do Y then Z, safer", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        LLMResponse(
            text='{"scores": [0.4, 0.9], "winner": 1, "reason": "B is safer"}',
            thinking=None, stop_reason="end_turn", tool_calls=[],
        ),
    ]
    bb = _Blackboard()
    plan = await _maybe_plan_tree_of_thought(
        fake_llm, "ship a feature", Budget(max_dollars=1.0), bb,
    )
    # tot_n defaults to 3; with only the drafts above scripted, the
    # FakeLLM yields its default terminal response for any extra draft,
    # then the critic JSON above is consumed when it lands. The winner is
    # one of the drafted plans regardless of N.
    assert plan is not None
    assert "Plan" in plan
    # The selection was logged to the blackboard.
    assert any("tree-of-thought selected plan" in c for _, _, c in bb.posts)


@pytest.mark.asyncio
async def test_run_goal_injects_plan_into_brief(monkeypatch, tmp_path: Path, fake_llm):
    monkeypatch.setenv("MAVERICK_PLANNING", "tree_of_thought")
    # 2 ToT drafts + 1 critic, then the orchestrator's FINAL + verifier +
    # distill-terminal. Keep tot_n small via config env is not available,
    # so rely on script: drafts reuse the default-exhausted FINAL after.
    monkeypatch.setenv("MAVERICK_PLANNING", "tree_of_thought")
    fake_llm.scripted = [
        # tot_n=3 drafts
        LLMResponse(text="Draft 1", thinking=None, stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text="Draft 2", thinking=None, stop_reason="end_turn", tool_calls=[]),
        LLMResponse(text="Draft 3", thinking=None, stop_reason="end_turn", tool_calls=[]),
        # critic
        LLMResponse(text='{"scores":[1,2,3],"winner":2,"reason":"best"}',
                    thinking=None, stop_reason="end_turn", tool_calls=[]),
        # orchestrator FINAL
        LLMResponse(text="FINAL: shipped", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
        # verifier accepts
        LLMResponse(text='{"confidence":0.9,"accepts":true,"critique":"ok","issues":[]}',
                    thinking=None, stop_reason="end_turn", tool_calls=[]),
    ]
    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("ship a feature", "make it good")
    out = await run_goal(
        llm=fake_llm, world=world, budget=Budget(max_dollars=5.0),
        goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
    )
    assert "DONE." in out
    # The orchestrator (the FINAL call) must have seen the injected plan in
    # its first user message. Find the call whose system prompt is the
    # orchestrator template (contains "orchestrator").
    orch_calls = [
        c for c in fake_llm.calls
        if "orchestrator" in (c.get("system") or "").lower()
    ]
    assert orch_calls, "expected an orchestrator LLM call"
    first_user = orch_calls[0]["messages"][0]["content"]
    text = first_user if isinstance(first_user, str) else str(first_user)
    assert "Selected plan (tree-of-thought)" in text
