"""spawn-from-profile: a DomainProfile -> a live Agent.

Constructs a real Agent, so it needs the full maverick-core install (run in CI,
not in the lightweight local subset).
"""
from __future__ import annotations

from maverick.capability import Capability
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


def test_agent_from_profile_uses_active_handoff_grant_for_parent(tmp_path):
    ctx = _ctx(tmp_path)
    parent = agent_from_profile(
        DomainProfile(
            name="parent",
            allow_tools=["shell", "spawn_specialist"],
        ),
        ctx,
        "parent task",
    )
    parent._handoff_capability = Capability(
        principal="agent:delegate",
        allow_tools=frozenset({"spawn_specialist"}),
    )
    profile = DomainProfile(
        name="finance",
        compartment="finance",
        allow_tools=["shell", "spawn_specialist"],
    )

    child = agent_from_profile(profile, ctx, "Analyze Q3 revenue", parent=parent, depth=1)

    assert child.capability is not None
    assert child.capability.permits("spawn_specialist") is True
    assert child.capability.permits("shell") is False


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
    tool_names = {tool.name for tool in agent.tools.all()}
    assert agent.role == "intake"
    assert "onboarding specialist" in agent.system  # the intake persona is in the prompt
    assert tool_names == {
        "record_business", "add_goal", "add_document", "finalize_intake",
    }
    assert "shell" not in tool_names
    assert "read_file" not in tool_names
    assert "write_file" not in tool_names


def _one_pack_per_suite():
    # A representative built-in pack from each suite -- enough to exercise the
    # spawn path (persona + discipline + workflow render + capability) for every
    # suite without constructing 1,118 Agents.
    from maverick.domain import builtin_dir, load_domains, suite_for
    packs = load_domains(builtin_dir())
    sample = {}
    for name, p in sorted(packs.items()):
        sample.setdefault(suite_for(name) or "generic", (name, p))
    return [v for v in sample.values()]


def test_every_suite_spawns_with_workflow_and_envelope(tmp_path):
    # Smoke test: a pack from each suite spawns to a live Agent whose system
    # prompt carries its persona and rendered playbook, under an enforced
    # envelope. Catches a pack whose appended [[workflow]] breaks the spawn path.
    ctx = _ctx(tmp_path)
    sample = _one_pack_per_suite()
    assert len(sample) >= 25, f"only {len(sample)} suites sampled"
    for name, profile in sample:
        agent = agent_from_profile(profile, ctx, "Do your job for the period.")
        assert agent.role == name
        if profile.workflow:
            assert "Workflow" in agent.system, f"{name}: playbook not in system prompt"
            assert profile.workflow[0].name in agent.system, f"{name}: step missing"
        # Envelope still enforced regardless of the new content.
        assert agent.capability.permits("read_file") is True, name
        if "shell" not in profile.allow_tools:
            assert agent.capability.permits("shell") is False, name


def test_pack_effort_tier_flows_to_agent(tmp_path, monkeypatch):
    # A pack's authored effort tier reaches the live agent -- but only when the
    # effort feature is enabled (off by default, so no behaviour change).
    from maverick import effort as effort_mod
    ctx = _ctx(tmp_path)
    profile = DomainProfile(
        name="finance_sox", persona="You audit SOX controls. Cite evidence.",
        allow_tools=["read_file"], deny_tools=["shell", "write_file"],
        max_risk="low", effort="high",
        models={"x": "claude-opus-4-8"},
    )
    # Feature OFF -> pack tier ignored.
    monkeypatch.setattr(effort_mod, "_config_effort", dict)
    a_off = agent_from_profile(profile, ctx, "Test the access controls.")
    assert a_off.effort is None
    # Feature ON -> pack tier applied (clamped to the model).
    monkeypatch.setattr(effort_mod, "_config_effort", lambda: {"enabled": True})
    a_on = agent_from_profile(profile, ctx, "Test the access controls.")
    assert a_on.effort == "high"


def test_refusals_reach_the_agent_system_prompt(tmp_path):
    # A spawned HR agent carries its hard refusals (Art-5) in the system prompt,
    # independent of the model following persona prose.
    ctx = _ctx(tmp_path)
    profile = DomainProfile(
        name="hr_screening", persona="You screen resumes against the rubric.",
        allow_tools=["read_file"], deny_tools=["shell", "write_file"], max_risk="low",
        refuse=["never rank candidates by a credit score"],
    )
    agent = agent_from_profile(profile, ctx, "Screen these five resumes.")
    assert "Hard refusals" in agent.system
    assert "emotion" in agent.system           # suite (Art-5) refusal injected
    assert "credit score" in agent.system      # pack-specific refusal injected
