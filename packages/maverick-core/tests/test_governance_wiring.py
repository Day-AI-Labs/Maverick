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


@pytest.mark.asyncio
async def test_require_fresh_human_approval_bypasses_ledger(monkeypatch, tmp_path):
    # Opt-in per-action oversight: a prior persistent ledger grant must NOT
    # satisfy the Art-14 gate -- a fresh decision is required, so an
    # auto-approve env (no human) is a denial.
    import maverick.safety.consent as consent
    monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
    consent.grant_persistent("ping")  # a standing grant exists
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    _gov(monkeypatch, {"require_human_actions": ["ping"],
                       "require_fresh_human_approval": True})
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "requires human approval" in out and "pong" not in out


@pytest.mark.asyncio
async def test_ledger_grant_satisfies_gate_by_default(monkeypatch, tmp_path):
    # Default (flag off): a persistent ledger grant satisfies the gate, the
    # documented backwards-compatible behavior.
    import maverick.safety.consent as consent
    monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
    consent.grant_persistent("ping")
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    _gov(monkeypatch, {"require_human_actions": ["ping"]})  # flag defaults False
    out = await _agent(tmp_path)._run_tool("ping", {})
    assert "pong" in out


def test_consult_ledger_false_ignores_prior_grant(monkeypatch, tmp_path):
    # Unit: require_consent(consult_ledger=False) does not honor the ledger.
    import maverick.safety.consent as consent
    monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    consent.grant_persistent("rm-rf", scope="/tmp")
    # Ledger honored by default...
    assert consent.require_consent("rm-rf", scope="/tmp").granted is True
    # ...but bypassed when a fresh decision is demanded.
    d = consent.require_consent("rm-rf", scope="/tmp",
                                allow_auto_approve=False, consult_ledger=False)
    assert d.granted is False and d.source != "ledger"


def test_scopeless_persistent_grant_is_honored(monkeypatch, tmp_path):
    # Regression: a scope-less grant_persistent(action) must be matched by the
    # ledger (a trailing-tab strip used to drop it, re-prompting forever).
    import maverick.safety.consent as consent
    monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")  # only a real grant can pass
    consent.grant_persistent("mass-dm")
    assert consent._check_ledger("mass-dm", None) is True
    assert consent.require_consent("mass-dm").granted is True


def test_scopeless_persistent_grant_can_be_revoked(monkeypatch, tmp_path):
    # Regression: revoke() must compare ledger records verbatim too. Scope-less
    # grants keep a significant trailing tab (``grant\taction\t``), so stripping
    # the record made those grants impossible to remove.
    import maverick.safety.consent as consent
    monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
    consent.grant_persistent("mass-dm")

    assert consent.revoke("mass-dm") is True
    assert consent._check_ledger("mass-dm", None) is False
    decision = consent.require_consent("mass-dm", allow_auto_approve=False)
    assert decision.granted is False and decision.source == "auto"


@pytest.mark.asyncio
async def test_require_human_above_amount_gates_through_chokepoint(monkeypatch, tmp_path):
    # The finance dollar-tier gate must fire through the agent chokepoint: a
    # tool call carrying an `amount` over the policy threshold needs human
    # approval, not a silent auto-approve.
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
    _gov(monkeypatch, {"require_human_above": {"ping": 5000}})
    over = await _agent(tmp_path)._run_tool("ping", {"amount": 6000})
    assert "requires human approval" in over and "pong" not in over
    # Under the threshold -> the tool runs.
    under = await _agent(tmp_path)._run_tool("ping", {"amount": 4000})
    assert "pong" in under


@pytest.mark.asyncio
async def test_deny_above_amount_blocks_through_chokepoint(monkeypatch, tmp_path):
    _gov(monkeypatch, {"deny_above": {"ping": 50000}})
    out = await _agent(tmp_path)._run_tool("ping", {"amount": 60000})
    assert "DENIED by org policy" in out and "pong" not in out
    # A numeric string amount is honored too.
    out2 = await _agent(tmp_path)._run_tool("ping", {"amount": "60000"})
    assert "DENIED by org policy" in out2
