"""Reflexion learning loop, wired into the orchestrator.

The reflexion module persists a postmortem when a run fails and recalls
it on the next similar goal. Off by default; enabled via MAVERICK_REFLEXION
or [reflexion] enable = true. These tests cover the helpers and the
record-on-failure integration through run_goal.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick import reflexion
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.llm import LLMResponse
from maverick.orchestrator import _maybe_record_reflexion, run_goal
from maverick.sandbox import LocalBackend
from maverick.world_model import WorldModel


class TestReflexionHelpers:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_REFLEXION", raising=False)
        assert reflexion.enabled() is False

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_REFLEXION", "1")
        assert reflexion.enabled() is True

    def test_tools_from_blackboard(self):
        bb = Blackboard()
        bb.post("a", "plan", "thinking")
        bb.post("a", "observation", "tool=read_file -> contents")
        bb.post("a", "observation", "tool=shell -> output")
        bb.post("a", "observation", "tool=read_file -> more")  # dup
        bb.post("a", "finding", "done")
        assert reflexion.tools_from_blackboard(bb) == ["read_file", "shell"]

    def test_synthesize_reflection_is_informative(self):
        text = reflexion.synthesize_reflection(
            "budget", "out of money", ["read_file", "shell"],
        )
        assert "budget" in text
        assert "read_file" in text
        assert "out of money" in text


class TestReflexionStorageRoundtrip:
    def test_record_then_recall(self, tmp_path):
        path = tmp_path / "reflexions.ndjson"
        reflexion.record(
            goal_text="Fix the flaky parser test",
            failure_class="agent_error",
            failure_msg="hit max_steps=25",
            reflection="plan first, verify in isolation",
            tools_used=["read_file"],
            path=path,
        )
        hits = reflexion.recall("Fix the flaky parser test", path=path)
        assert hits
        _, entry = hits[0]
        assert entry.failure_class == "agent_error"
        assert "read_file" in entry.tools_used


class TestReflexionWiring:
    def test_record_called_when_enabled(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_REFLEXION", "1")
        captured: list[dict] = []
        monkeypatch.setattr(
            reflexion, "record",
            lambda **kw: captured.append(kw) or True,
        )

        class _Goal:
            title = "Fix the flaky parser test"
            description = "intermittent pytest failures"

        bb = Blackboard()
        bb.post("a", "observation", "tool=read_file -> x")
        _maybe_record_reflexion(
            _Goal(), failure_class="agent_error",
            failure_msg="hit max_steps=25", blackboard=bb,
        )
        assert len(captured) == 1
        assert captured[0]["failure_class"] == "agent_error"
        assert "Fix the flaky parser test" in captured[0]["goal_text"]
        assert captured[0]["tools_used"] == ["read_file"]

    def test_record_skipped_when_disabled(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_REFLEXION", raising=False)
        captured: list[dict] = []
        monkeypatch.setattr(
            reflexion, "record",
            lambda **kw: captured.append(kw) or True,
        )

        class _Goal:
            title = "x"
            description = ""

        _maybe_record_reflexion(
            _Goal(), failure_class="budget", failure_msg="nope",
            blackboard=Blackboard(),
        )
        assert captured == []


@pytest.mark.asyncio
async def test_failed_run_records_reflexion(monkeypatch, tmp_path: Path, fake_llm):
    """A run that errors out invokes reflexion.record when enabled."""
    monkeypatch.setenv("MAVERICK_REFLEXION", "1")
    captured: list[dict] = []
    monkeypatch.setattr(
        reflexion, "record", lambda **kw: captured.append(kw) or True,
    )

    # Empty response with no tools -> AgentResult(error=...) -> failure path.
    fake_llm.scripted = [
        LLMResponse(text="", thinking=None, stop_reason="end_turn", tool_calls=[]),
    ]

    world = WorldModel(path=tmp_path / "world.db")
    gid = world.create_goal("Summarize the quarterly report", "10-K filing")

    out = await run_goal(
        llm=fake_llm,
        world=world,
        budget=Budget(max_dollars=1.0),
        goal_id=gid,
        sandbox=LocalBackend(workdir=tmp_path),
        max_depth=1,
    )
    assert "Stopped" in out  # failure surfaced to the caller
    assert len(captured) == 1
    assert "Summarize the quarterly report" in captured[0]["goal_text"]
