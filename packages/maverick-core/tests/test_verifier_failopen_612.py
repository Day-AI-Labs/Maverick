"""Verifier fail-open integrity (#612): a budget-starved orchestrator must not
report high verifier confidence for an answer it never verified, or donation
keys off it and ships an "unverified high-confidence" trajectory.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget, BudgetExceeded
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
from maverick.world_model import WorldModel


@pytest.fixture
def ctx(tmp_path: Path, fake_llm):
    world = WorldModel(tmp_path / "w.db")
    gid = world.create_goal("g", "")
    return SwarmContext(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=gid, max_depth=1, use_skills=False,
    )


@pytest.mark.asyncio
async def test_orchestrator_unverified_on_budget_reports_zero(
    ctx, fake_llm, make_llm_response, monkeypatch,
):
    async def _boom(*a, **k):
        raise BudgetExceeded("verifier out of budget")

    monkeypatch.setattr("maverick.verifier.verify_final", _boom)
    fake_llm.scripted = [make_llm_response(text="FINAL: the answer")]
    orch = Agent(ctx=ctx, role="orchestrator", brief="do it", depth=0)
    result = await orch.run()
    assert "the answer" in (result.final or "")
    # Verifier was attempted but hit budget -> NOT high confidence.
    assert result.verifier_confidence == 0.0
    assert result.verifier_confidence < 0.75  # below the donation reward gate


@pytest.mark.asyncio
async def test_non_verifying_role_keeps_default_confidence(
    ctx, fake_llm, make_llm_response,
):
    # A non-orchestrator never verifies; the 1.0 default is unchanged (it isn't
    # donated as the run's verdict, so this is correct).
    fake_llm.scripted = [make_llm_response(text="FINAL: child result")]
    worker = Agent(ctx=ctx, role="researcher", brief="sub", depth=0)
    result = await worker.run()
    assert "child result" in (result.final or "")
    assert result.verifier_confidence == 1.0


# --- #612 finding 4: cross-family verifier contract vs behavior ---

def test_cross_family_fallback_requires_explicit_env(monkeypatch):
    import maverick.verifier as v
    monkeypatch.delenv("MAVERICK_CROSS_FAMILY_VERIFIER", raising=False)
    # No implicit provider swap: returns None unless explicitly configured.
    assert v._cross_family_fallback("anthropic:claude-x") is None
    monkeypatch.setenv("MAVERICK_CROSS_FAMILY_VERIFIER", "openai:gpt-x")
    assert v._cross_family_fallback("anthropic:claude-x") == "openai:gpt-x"


def test_same_family_verifier_warns_once(monkeypatch, caplog):
    import maverick.verifier as v
    monkeypatch.setattr(v, "_warned_same_family", False)
    with caplog.at_level("WARNING"):
        v._warn_same_family_verifier("anthropic:claude-x")
        v._warn_same_family_verifier("anthropic:claude-x")
    lockstep = [r for r in caplog.records if "lockstep" in r.getMessage()]
    assert len(lockstep) == 1  # warned exactly once, not per call
