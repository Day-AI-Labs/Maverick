"""P0 identity layer: signed, attenuating capabilities + enforcement.

Capabilities gate the tool surface per-agent. Children inherit an
*attenuated* (never broadened) grant, so a sub-agent cannot escalate past
its parent. Default-open: no capability set == unrestricted, behaviour
unchanged. Opt in via [capabilities] enforce or MAVERICK_ENFORCE_CAPABILITIES.
"""

import pytest
from maverick.capability import (
    Capability,
    capability_enforced,
    capability_from_config,
    sign_capability,
    verify_capability,
)

# --- permits ---------------------------------------------------------------

def test_empty_allow_means_all():
    cap = Capability(principal="p")
    assert cap.permits("read_file") and cap.permits("shell")


def test_deny_beats_allow():
    cap = Capability(principal="p", allow_tools=frozenset({"shell"}),
                     deny_tools=frozenset({"shell"}))
    assert cap.permits("shell") is False


def test_allow_whitelist():
    cap = Capability(principal="p", allow_tools=frozenset({"read_file"}))
    assert cap.permits("read_file") is True
    assert cap.permits("shell") is False


def test_max_risk_ceiling():
    # shell is "high", read_file is "low" (see safety.tool_risk).
    cap = Capability(principal="p", max_risk="low")
    assert cap.permits("read_file") is True
    assert cap.permits("shell") is False


def test_expiry():
    past = Capability(principal="p", expires_at=1000.0)
    assert past.permits("read_file", now=2000.0) is False
    assert past.permits("read_file", now=500.0) is True


# --- attenuation: can only narrow -----------------------------------------

def test_attenuate_rebinds_principal():
    child = Capability(principal="user:a").attenuate(principal="agent:coder-1")
    assert child.principal == "agent:coder-1"


def test_attenuate_deny_grows():
    parent = Capability(principal="p", deny_tools=frozenset({"shell"}))
    child = parent.attenuate(deny={"computer"})
    assert {"shell", "computer"} <= set(child.deny_tools)
    assert not child.permits("shell") and not child.permits("computer")


def test_attenuate_allow_only_shrinks():
    # Parent allows all; child restricted to read_file.
    child = Capability(principal="p").attenuate(allow={"read_file"})
    assert child.allow_tools == frozenset({"read_file"})
    # Parent already restricted; child cannot ADD a tool back.
    parent = Capability(principal="p", allow_tools=frozenset({"read_file"}))
    child2 = parent.attenuate(allow={"read_file", "shell"})
    assert child2.allow_tools == frozenset({"read_file"})  # intersection only
    assert child2.permits("shell") is False


def test_attenuate_max_risk_only_tightens():
    parent = Capability(principal="p", max_risk="high")
    assert parent.attenuate(max_risk="low").max_risk == "low"
    low = Capability(principal="p", max_risk="low")
    assert low.attenuate(max_risk="high").max_risk == "low"  # cannot loosen


def test_attenuation_is_subset_of_parent():
    # Every tool a child permits must also be permitted by the parent.
    parent = Capability(principal="p", deny_tools=frozenset({"computer"}),
                        max_risk="medium")
    child = parent.attenuate(principal="agent:x", deny={"write_file"}, max_risk="low")
    sample = ["read_file", "web_search", "shell", "computer", "write_file",
              "list_dir", "browser"]
    for t in sample:
        if child.permits(t):
            assert parent.permits(t), f"child escalated on {t}"


# --- signing (optional crypto) --------------------------------------------

def test_sign_verify_roundtrip():
    # Guard the whole crypto path: a half-installed cryptography (rust bindings
    # present, _cffi_backend missing) panics on import rather than raising
    # ImportError, so skip on any failure -- CI installs a working build.
    try:
        from maverick.audit.signing import _generate_keypair, _have_crypto
        if not _have_crypto():
            pytest.skip("cryptography not installed")
        priv, pub, _ = _generate_keypair()
    except BaseException:  # noqa: BLE001 -- pyo3 PanicException isn't an Exception
        pytest.skip("cryptography unavailable/broken in this environment")
    cap = Capability(principal="agent:coder-1", deny_tools=frozenset({"shell"}),
                     max_risk="medium")
    sig = sign_capability(cap, priv.hex())
    assert verify_capability(cap, sig, pub.hex()) is True
    # Tamper: a broadened grant must not verify against the original signature.
    tampered = Capability(principal="agent:coder-1", max_risk="high")
    assert verify_capability(tampered, sig, pub.hex()) is False


# --- enable flag -----------------------------------------------------------

def test_enforced_via_env(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    monkeypatch.setenv("MAVERICK_ENFORCE_CAPABILITIES", "1")
    assert capability_enforced() is True


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    monkeypatch.delenv("MAVERICK_ENFORCE_CAPABILITIES", raising=False)
    assert capability_enforced() is False


def test_enforced_via_config(monkeypatch):
    monkeypatch.delenv("MAVERICK_ENFORCE_CAPABILITIES", raising=False)
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"capabilities": {"enforce": True}})
    assert capability_enforced() is True


def test_from_config_reuses_acl(monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"security": {"denied_tools": ["shell"], "max_risk": "medium"}},
    )
    cap = capability_from_config("user:local")
    assert "shell" in cap.deny_tools
    assert cap.max_risk == "medium"
    assert cap.permits("shell") is False


# --- propagation helper ----------------------------------------------------

def test_child_capability_attenuates():
    from maverick.tools.spawn import _child_capability

    class _Parent:
        capability = Capability(principal="user:local", deny_tools=frozenset({"shell"}))
        depth = 0

    child = _child_capability(_Parent(), "coder", 1)
    assert child.principal == "agent:coder-1"
    assert child.permits("shell") is False

    class _Unrestricted:
        capability = None
        depth = 0

    assert _child_capability(_Unrestricted(), "coder", 1) is None


# --- enforcement at the tool chokepoint ------------------------------------

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


@pytest.mark.asyncio
async def test_run_tool_denies_uncapable(tmp_path):
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  deny_tools=frozenset({"shell"}))
    out = await agent._run_tool("shell", {"cmd": "echo hi"})
    assert "DENIED by capability" in out
    assert "agent:coder-1" in out


@pytest.mark.asyncio
async def test_run_tool_noop_when_unrestricted(tmp_path):
    from maverick.tools import Tool
    agent = _agent(tmp_path)
    agent.capability = None  # default: enforcement is a no-op
    agent.tools.register(Tool(
        name="ping", description="ping", fn=lambda args: "pong",
        input_schema={"type": "object", "properties": {}},
    ))
    out = await agent._run_tool("ping", {})
    assert "pong" in out
    assert "DENIED" not in out


@pytest.mark.asyncio
async def test_run_tool_allows_permitted(tmp_path):
    from maverick.tools import Tool
    agent = _agent(tmp_path)
    agent.capability = Capability(principal="agent:coder-1",
                                  allow_tools=frozenset({"ping"}))
    agent.tools.register(Tool(
        name="ping", description="ping", fn=lambda args: "pong",
        input_schema={"type": "object", "properties": {}},
    ))
    assert "pong" in await agent._run_tool("ping", {})
    # A tool outside the whitelist is denied.
    assert "DENIED by capability" in await agent._run_tool("shell", {"cmd": "x"})
