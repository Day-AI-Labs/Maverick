"""Operator-perspective battery: cost, rollback-in-the-prompt, inspect-while-paused.

The prompt-integration battery proves the addendum REACHES the system prompt.
This covers the rest of what an operator actually experiences:

  * COST -- the addendum rides in EVERY prompt, so its footprint must be bounded.
    The recalled block can never exceed the char budget, and the amount a real
    agent's system prompt grows by is bounded no matter how much was "learned".
  * ROLLBACK reaches the live prompt -- forgetting a line removes it from the
    next agent built, so the undo handle has real effect, not just store edits.
  * INSPECT WHILE PAUSED -- list_learned works even when the feature is OFF (so
    an operator can audit/roll back what was learned before re-enabling), while
    recall stays inert.
"""
from __future__ import annotations

import pytest
from maverick import self_harness as sh
from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.sandbox.local import LocalBackend
from maverick.swarm import SwarmContext
from maverick.world_model import WorldModel


@pytest.fixture
def ctx(tmp_path):
    world = WorldModel(tmp_path / "world.db")
    gid = world.create_goal("g", "")
    return SwarmContext(
        llm=None, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=gid, max_depth=1, use_skills=False)


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "addenda.json"
    monkeypatch.setattr(sh, "_store_path", lambda: p)
    return p


def _agent(ctx, model="model-x"):
    return Agent(ctx=ctx, role="orchestrator", brief="do a thing", model_override=model)


# ---- cost / overhead -------------------------------------------------------

def test_recalled_block_is_char_bounded(store, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    # Promote far more, far longer lines than the budget could hold.
    for i in range(40):
        sh._apply_addendum(sh.HarnessProposal(
            model_id="model-x", signature=f"s{i}",
            addendum_line=f"line {i} " + "x" * 250, rationale="r"), path=store)
    block = sh.recall_addendum("model-x", store)
    assert len(block) <= sh._MAX_ADDENDUM_CHARS
    assert len([b for b in block.splitlines() if b.startswith("- ")]) <= sh._MAX_LINES_PER_MODEL


def test_prompt_growth_is_bounded(ctx, store, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    base = _agent(ctx, "model-fresh").system          # nothing learned for this model
    for i in range(40):
        sh._apply_addendum(sh.HarnessProposal(
            model_id="model-x", signature=f"s{i}",
            addendum_line=f"guidance {i} " + "y" * 250, rationale="r"), path=store)
    grown = _agent(ctx, "model-x").system
    # the prompt grows by at most the block budget (+ a small framing margin),
    # however much was learned -- the per-turn token tax is bounded.
    assert len(grown) - len(base) <= sh._MAX_ADDENDUM_CHARS + 64


def test_no_cost_when_nothing_learned(ctx, store, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    # an unlearned model's prompt carries no addendum framing at all
    assert "Operating guidance learned for this model" not in _agent(ctx, "model-x").system


# ---- rollback reaches the live prompt --------------------------------------

def test_forget_removes_guidance_from_the_next_prompt(ctx, store, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    sh._write_addenda({"model-x": "Operating guidance learned for this model:\n"
                       "- verify the export window first\n- check the second thing"}, store)
    assert "verify the export window first" in _agent(ctx, "model-x").system

    # operator forgets one line -> it leaves the prompt, the other stays
    assert sh.forget_addendum("model-x", line="verify the export window first", path=store)
    sysprompt = _agent(ctx, "model-x").system
    assert "verify the export window first" not in sysprompt
    assert "check the second thing" in sysprompt

    # forget the rest -> the addendum is fully gone from the prompt
    assert sh.forget_addendum("model-x", path=store)
    assert "Operating guidance learned for this model" not in _agent(ctx, "model-x").system


# ---- inspect while paused / default-off ------------------------------------

def test_inspection_works_while_feature_is_off(store, monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_HARNESS", raising=False)   # feature OFF
    sh._write_addenda({"model-x": "Operating guidance learned for this model:\n- kept lesson"},
                      store)
    # recall is inert (nothing injected), but the operator can still see + roll back
    assert sh.recall_addendum("model-x", store) == ""
    assert sh.list_learned(store) == {"model-x": ["kept lesson"]}
    assert sh.forget_addendum("model-x", path=store)
    assert sh.list_learned(store) == {}


def test_disabled_install_is_inert_in_the_prompt(ctx, store, monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_HARNESS", raising=False)
    sh._write_addenda({"model-x": "Operating guidance learned for this model:\n- a lesson"},
                      store)
    assert "a lesson" not in _agent(ctx, "model-x").system
