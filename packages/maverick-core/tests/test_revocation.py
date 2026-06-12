"""Capability revocation list: registry behavior + the tool-chokepoint gate."""
from __future__ import annotations

import pytest
from maverick.capability import Capability
from maverick.revocation import RevocationRegistry
from maverick.tools import Tool

# ---- registry ----

def test_revoke_and_is_revoked(tmp_path):
    reg = RevocationRegistry(tmp_path / "rev.json")
    assert reg.is_revoked("agent:x") is False
    reg.revoke("agent:x", reason="leaked key")
    assert reg.is_revoked("agent:x") is True
    assert reg.revoked()["agent:x"].reason == "leaked key"


def test_unrevoke(tmp_path):
    reg = RevocationRegistry(tmp_path / "rev.json")
    reg.revoke("agent:x")
    assert reg.unrevoke("agent:x") is True
    assert reg.is_revoked("agent:x") is False
    assert reg.unrevoke("agent:x") is False  # already gone


def test_blank_principal_never_revoked(tmp_path):
    assert RevocationRegistry(tmp_path / "rev.json").is_revoked("") is False


def test_persisted_across_instances(tmp_path):
    p = tmp_path / "rev.json"
    RevocationRegistry(p).revoke("agent:x")
    assert RevocationRegistry(p).is_revoked("agent:x") is True


def test_reread_on_file_change_propagates(tmp_path):
    # The "propagation to running agents" property: one instance picks up
    # another process's revoke because the file mtime changed.
    p = tmp_path / "rev.json"
    running = RevocationRegistry(p)
    other = RevocationRegistry(p)
    assert running.is_revoked("agent:x") is False  # loads (empty)
    other.revoke("agent:x")                         # "another process"
    assert running.is_revoked("agent:x") is True    # re-read on mtime change


def test_corrupt_file_fails_open(tmp_path):
    p = tmp_path / "rev.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert RevocationRegistry(p).is_revoked("agent:x") is False


def test_file_is_0600(tmp_path):
    p = tmp_path / "rev.json"
    RevocationRegistry(p).revoke("agent:x")
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_revoke_subtree_walks_delegation_graph(tmp_path):
    # diamond + a cycle edge back to root: every reachable principal revoked,
    # cycle does not loop forever.
    edges = {"root": ["a", "b"], "a": ["c"], "b": ["c", "root"]}
    reg = RevocationRegistry(tmp_path / "rev.json")
    order = reg.revoke_subtree("root", edges, reason="rogue parent")
    assert set(order) == {"root", "a", "b", "c"}
    for pr in ("root", "a", "b", "c"):
        assert reg.is_revoked(pr)


def test_revoke_subtree_leaf_only(tmp_path):
    reg = RevocationRegistry(tmp_path / "rev.json")
    order = reg.revoke_subtree("leaf", {"root": ["leaf"]})  # leaf has no children
    assert order == ["leaf"]
    assert reg.is_revoked("leaf") and not reg.is_revoked("root")


def test_module_is_revoked_fails_open(monkeypatch):
    import maverick.revocation as R

    def _boom():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(R, "shared", _boom)
    assert R.is_revoked("agent:x") is False


# ---- tool-chokepoint gate (mirrors test_capability_path_enforcement) ----

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
    return Agent(ctx=ctx, role="coder", brief="b")


def _spy_tool(name, calls):
    return Tool(
        name=name, description="spy",
        fn=lambda args: calls.append(args) or "ran",
        input_schema={"type": "object", "properties": {}},
    )


def _point_shared_at(monkeypatch, tmp_path):
    import maverick.revocation as R
    reg = RevocationRegistry(tmp_path / "rev.json")
    monkeypatch.setattr(R, "_shared", reg)
    return reg


@pytest.mark.asyncio
async def test_revoked_principal_tool_call_denied(tmp_path, monkeypatch):
    reg = _point_shared_at(monkeypatch, tmp_path)
    reg.revoke("agent:coder-1", reason="rogue")
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1")  # empty allow == permits all
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "x"})
    assert "DENIED by capability" in out
    assert "revoked" in out and "agent:coder-1" in out
    assert calls == []  # the tool never ran


@pytest.mark.asyncio
async def test_revoked_parent_principal_denies_child_tool_call(tmp_path, monkeypatch):
    reg = _point_shared_at(monkeypatch, tmp_path)
    reg.revoke("user:alice", reason="offboarded")
    agent = _agent(tmp_path)
    agent.capability = Capability(
        principal="agent:coder-1", ancestors=("user:alice",),
    )
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "x"})
    assert "DENIED by capability" in out
    assert "user:alice" in out
    assert calls == []


@pytest.mark.asyncio
async def test_non_revoked_principal_not_denied(tmp_path, monkeypatch):
    _point_shared_at(monkeypatch, tmp_path)  # empty registry
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1")
    calls: list = []
    agent.tools.register(_spy_tool("read_file", calls))

    out = await agent._run_tool("read_file", {"path": "x"})
    assert "DENIED" not in out
    assert calls == [{"path": "x"}]  # ran normally


@pytest.mark.asyncio
async def test_revocation_denial_is_audited(tmp_path, monkeypatch):
    import maverick.audit
    from maverick.audit import EventKind
    reg = _point_shared_at(monkeypatch, tmp_path)
    reg.revoke("agent:coder-1")
    calls: list = []
    monkeypatch.setattr(maverick.audit, "record",
                        lambda kind, **kw: calls.append((kind, kw)))
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1")
    agent.tools.register(_spy_tool("read_file", []))

    await agent._run_tool("read_file", {"path": "x"})
    denied = [kw for k, kw in calls if k == EventKind.CAPABILITY_DENIED]
    assert denied and denied[0]["principal"] == "agent:coder-1"
