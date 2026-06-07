"""spawn-from-profile: a DomainProfile -> a live Agent.

Constructs a real Agent, so it needs the full maverick-core install (run in CI,
not in the lightweight local subset).
"""
from __future__ import annotations

from maverick.domain import DomainProfile, agent_from_profile


def _ctx(tmp_path):
    from maverick.blackboard import Blackboard
    from maverick.budget import Budget
    from maverick.sandbox import LocalBackend
    from maverick.swarm import SwarmContext
    from maverick.world_model import WorldModel

    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("g", "")
    return SwarmContext(
        llm=None, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id, use_skills=False,
    )


def test_agent_from_profile_sets_domain_persona_and_capability(tmp_path):
    ctx = _ctx(tmp_path)
    profile = DomainProfile(
        name="finance", compartment="finance",
        persona="You are a finance specialist. Cite every figure.",
        allow_tools=["read_file"], deny_tools=["shell"], max_risk="medium",
    )
    agent = agent_from_profile(profile, ctx, "Analyze Q3 revenue")

    assert agent.role == "finance"
    assert agent.domain == "finance"                 # sector tag for Rung 2
    assert "finance specialist" in agent.system      # persona injected
    assert agent.capability is not None
    assert agent.capability.permits("read_file") is True
    assert agent.capability.permits("shell") is False  # envelope enforced


def test_children_inherit_parent_domain(tmp_path):
    from maverick.agent import Agent

    ctx = _ctx(tmp_path)
    profile = DomainProfile(name="finance", compartment="finance",
                            allow_tools=["read_file"])
    parent = agent_from_profile(profile, ctx, "parent task")

    child = Agent(ctx=ctx, role="researcher", brief="sub", depth=1, parent=parent)
    assert child.domain == "finance"  # inherited -> a sector seal catches the sub-tree
    assert child.knowledge_sources == parent.knowledge_sources  # inherited too


def test_agent_from_profile_sets_knowledge_sources(tmp_path):
    ctx = _ctx(tmp_path)
    profile = DomainProfile(name="finance", knowledge_sources=["finance"],
                            allow_tools=["read_file"])
    agent = agent_from_profile(profile, ctx, "task")
    assert agent.knowledge_sources == ["finance"]


def test_build_intake_agent_assembles_interviewer(tmp_path):
    from maverick.intake import build_intake_agent
    ctx = _ctx(tmp_path)
    agent, session = build_intake_agent(ctx)
    assert agent.role == "intake"
    assert "onboarding specialist" in agent.system  # the intake persona is in the prompt
