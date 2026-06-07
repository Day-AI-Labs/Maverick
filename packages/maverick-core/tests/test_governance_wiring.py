"""The governance control plane wired into the agent tool chokepoint.

Exercises `_run_tool` directly (no live LLM): an org policy can DENY a tool or
REQUIRE_HUMAN sign-off, and -- crucially -- a silent auto-approve does NOT
satisfy the Art 14 human-oversight requirement. Default-open: no [governance]
policy => unchanged behaviour.
"""
from __future__ import annotations

import pytest
from maverick.tools import Tool


def _agent(tmp_path):
    from maverick.agent import Agent
    from maverick.blackboard import Blackboard
    from maverick.budget import Budget
    from maverick.sandbox import LocalBackend
    from maverick.swarm import SwarmContext
    from maverick.world_model import WorldModel

    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("g", "")
    ctx = SwarmContext(
        llm=None, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id, use_skills=False,
    )
    agent = Agent(ctx=ctx, role="coder", brief="b")
    agent.capability = None  # isolate the governance layer from capability
    agent.tools.register(Tool(
        name="ping", description="ping", fn=lambda args: "pong",
        input_schema={"type": "object", "properties": {}},
    ))
    return agent


def _gov(monkeypatch, policy: dict):
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {"governance": policy})


@pytest.mark.asyncio
async def test_default_open_allows(monkeypatch, tmp_path):
    _gov(monkeypatch, {})  # no policy -> ALLOW, tool runs
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "pong" in out


@pytest.mark.asyncio
async def test_deny_action_blocks(monkeypatch, tmp_path):
    _gov(monkeypatch, {"deny_actions": ["ping"]})
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "DENIED by org policy" in out
    assert "pong" not in out


@pytest.mark.asyncio
async def test_require_human_blocks_without_a_human(monkeypatch, tmp_path):
    # auto-approve mode must NOT silently satisfy Art 14: the tool is blocked.
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    _gov(monkeypatch, {"require_human_actions": ["ping"]})
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "requires human approval" in out
    assert "pong" not in out


@pytest.mark.asyncio
async def test_require_human_runs_with_grant(monkeypatch, tmp_path):
    # A real human approval (here, a granted consent decision) lets the
    # require-human action proceed.
    import maverick.safety.consent as consent
    from maverick.safety.consent import ConsentDecision
    monkeypatch.setattr(
        consent, "require_consent",
        lambda *a, **k: ConsentDecision(True, "test", "high", 0.0),
    )
    _gov(monkeypatch, {"require_human_actions": ["ping"]})
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "pong" in out


@pytest.mark.asyncio
async def test_deny_is_audited(monkeypatch, tmp_path):
    _gov(monkeypatch, {"deny_actions": ["ping"]})
    seen = []
    import maverick.audit as audit
    monkeypatch.setattr(audit, "record",
                        lambda kind, **kw: seen.append((kind, kw)))
    await _agent(tmp_path)._run_tool("ping", {})
    kinds = [k for k, _ in seen]
    assert audit.EventKind.GOVERNANCE_DENIED in kinds


@pytest.mark.asyncio
async def test_eval_error_fails_closed_when_policy_configured(monkeypatch, tmp_path):
    # Hardening: a CONFIGURED policy + an evaluation bug must FAIL CLOSED (deny
    # this action), never silently bypass the oversight gate.
    import maverick.governance as gov
    _gov(monkeypatch, {"deny_actions": ["other"]})  # non-empty policy

    def _boom(*a, **k):
        raise RuntimeError("classifier blew up")

    monkeypatch.setattr(gov, "evaluate", _boom)
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "governance evaluation error" in out
    assert "pong" not in out


@pytest.mark.asyncio
async def test_eval_error_open_when_no_policy(monkeypatch, tmp_path):
    # No policy configured -> evaluate is never consulted, so an (irrelevant)
    # eval bug can't block: the tool still runs (non-enterprise unaffected).
    import maverick.governance as gov
    _gov(monkeypatch, {})  # empty policy

    def _boom(*a, **k):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(gov, "evaluate", _boom)
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "pong" in out
