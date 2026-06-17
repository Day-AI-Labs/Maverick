"""Phase 3 — gate the remaining external surfaces and add per-caller A2A
identity. Covers A2A per-caller bearer -> agent identity + admission + ceiling,
governance gating on federation delegation (DENY + fail-closed REQUIRE_HUMAN),
and channel/marketplace federation gating by registered origin."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick import agent_trust
from maverick.agent_trust import TrustedAgent

# ---- per-caller A2A token resolution --------------------------------------


def test_agent_for_a2a_token_resolves():
    reg = {"vega": TrustedAgent(id="vega", a2a_token="s3cret"),
           "other": TrustedAgent(id="other", a2a_token="zzz")}
    assert agent_trust.agent_for_a2a_token("s3cret", registry=reg).id == "vega"
    assert agent_trust.agent_for_a2a_token("nope", registry=reg) is None
    assert agent_trust.agent_for_a2a_token("", registry=reg) is None
    # An entry with no a2a_token never matches the empty default.
    assert agent_trust.agent_for_a2a_token("", registry={"x": TrustedAgent(id="x")}) is None


def test_a2a_token_parses_from_config():
    reg = agent_trust.load_registry({"agent_trust": {"agents": [
        {"id": "vega", "a2a_token": "tok-123"},
    ]}})
    assert reg["vega"].a2a_token == "tok-123"


# ---- A2A auth + principal + admission + ceiling ---------------------------


def _patch(monkeypatch, registry, *, enforced=True):
    monkeypatch.setattr(agent_trust, "load_trust_state", lambda: (enforced, registry))
    monkeypatch.setattr(agent_trust, "agent_trust_enforced", lambda cfg=None: enforced)
    monkeypatch.setattr(agent_trust, "load_registry", lambda cfg=None: registry)


def test_a2a_auth_accepts_per_caller_token(monkeypatch):
    from maverick.a2a_tasks import TaskEngine
    monkeypatch.delenv("MAVERICK_A2A_TOKEN", raising=False)
    reg = {"vega": TrustedAgent(id="vega", a2a_token="s3cret")}
    _patch(monkeypatch, reg)
    eng = TaskEngine()
    assert eng.auth_error("Bearer s3cret") is None          # valid per-caller token
    assert eng.auth_error("Bearer wrong") is not None       # unknown bearer
    assert eng.principal_for("Bearer s3cret") == "agent:vega"


def test_a2a_trust_block_per_caller(monkeypatch):
    from maverick.a2a_tasks import _a2a_trust_block
    reg = {"vega": TrustedAgent(id="vega", direction="both"),
           "inbound_only": TrustedAgent(id="inbound_only", direction="outbound")}
    _patch(monkeypatch, reg)
    assert _a2a_trust_block("agent:vega") is None            # admitted
    assert _a2a_trust_block("agent:inbound_only") is not None  # outbound-only -> denied
    # An anon/shared caller with no surface-wide "a2a" entry is denied.
    assert _a2a_trust_block("anon") is not None


def test_a2a_capability_uses_caller_ceiling(monkeypatch):
    from maverick.a2a_tasks import _a2a_capability, _caller_agent
    reg = {"vega": TrustedAgent(id="vega", allow_tools=frozenset({"read_file"}))}
    _patch(monkeypatch, reg)
    cv = _caller_agent.set("vega")
    try:
        cap = _a2a_capability()
        assert cap.allow_tools == frozenset({"read_file"})
    finally:
        _caller_agent.reset(cv)


# ---- governance gating on federation delegation ---------------------------


class _Goals:
    def start_goal(self, title, description="", **kw):
        return 1

    def status(self, goal_id):
        return SimpleNamespace(status="done", result="ok")


def _fed(monkeypatch, registry):
    from maverick import federation
    from maverick.federation import FederationService, Peer
    monkeypatch.setattr(agent_trust, "load_trust_state", lambda: (True, registry))
    monkeypatch.setattr(agent_trust, "agent_trust_enforced", lambda cfg=None: True)
    monkeypatch.setattr(agent_trust, "load_registry", lambda cfg=None: registry)
    return federation, FederationService(
        node="b", peers=[Peer("a", "a:1", "tok")], local_grant=None,
        goal_service=_Goals(), record=lambda *a, **k: None,
    )


def _delegate(svc, **over):
    payload = {"auth_token": "tok", "correlation_id": "c1", "goal_title": "x",
               "requested_tools": ["read_file"]}
    payload.update(over)
    return svc.delegate_goal(payload)


def test_federation_governance_deny(monkeypatch):
    import maverick.governance as gov
    reg = {"a": TrustedAgent(id="a", allow_tools=frozenset({"read_file"}))}
    federation, svc = _fed(monkeypatch, reg)
    monkeypatch.setattr(gov, "evaluate", lambda *a, **k: gov.Verdict(
        gov.Decision.DENY, "blocked by policy", "deny_actions"))
    reply = _delegate(svc)
    assert reply["accepted"] is False and "governance" in reply["reason"]


def test_federation_governance_require_human_fail_closed(monkeypatch):
    import maverick.governance as gov
    reg = {"a": TrustedAgent(id="a", allow_tools=frozenset({"read_file"}))}
    federation, svc = _fed(monkeypatch, reg)
    monkeypatch.setattr(gov, "evaluate", lambda *a, **k: gov.Verdict(
        gov.Decision.REQUIRE_HUMAN, "needs sign-off", "require_human_actions"))
    reply = _delegate(svc)
    assert reply["accepted"] is False and "human approval" in reply["reason"].lower()


def test_federation_governance_allow_is_noop(monkeypatch):
    # No policy configured -> evaluate returns ALLOW -> delegation proceeds.
    reg = {"a": TrustedAgent(id="a", allow_tools=frozenset({"read_file"}))}
    _federation, svc = _fed(monkeypatch, reg)
    reply = _delegate(svc)
    assert reply["accepted"] is True


# ---- channel / marketplace gating by registered origin --------------------


def test_channel_federation_gated_by_registry(monkeypatch):
    from maverick import channel_federation as cf
    # Bypass signature crypto; we're testing the trust-origin gate that follows.
    monkeypatch.setattr(cf, "verify_envelope", lambda *a, **k: (True, "ok"))
    _patch(monkeypatch, {})  # engaged, empty registry -> origin not registered
    applier = cf.InboundApplier(handler=lambda m: None, peers={}, local="me")
    env = {"schema": "maverick-channel-fed/1", "origin": "ghost", "to": "me",
           "channel": "slack", "user_id": "u", "text": "hi",
           "pubkey": "x", "key_id": "k", "sig": "s"}
    res = applier.apply(env)
    assert res["applied"] is False and "trust registry" in res["reason"]


def test_marketplace_federation_gated_by_registry(monkeypatch):
    from maverick import marketplace_federation as mf
    monkeypatch.setattr(mf, "verify_envelope", lambda *a, **k: (True, "ok"))
    _patch(monkeypatch, {})
    env = {"schema": "maverick-marketplace-fed/1", "origin": "ghost",
           "listings": [], "pubkey": "x", "key_id": "k", "sig": "s"}
    report = mf.import_listings(env, peers={"ghost": {"origin": "ghost", "pubkey": "x"}})
    assert "trust registry" in (report.get("reason") or "")


# ---- per-surface token isolation ------------------------------------------


def test_token_surface_isolation():
    # A token configured for one surface must not authenticate another.
    reg = {"vega": TrustedAgent(id="vega", grpc_token="g", mcp_token="m",
                                a2a_token="a")}
    assert agent_trust.agent_for_token("g", "grpc", registry=reg).id == "vega"
    assert agent_trust.agent_for_token("g", "mcp", registry=reg) is None
    assert agent_trust.agent_for_token("g", "a2a", registry=reg) is None
    assert agent_trust.agent_for_token("m", "mcp", registry=reg).id == "vega"


# ---- gRPC goal API gating -------------------------------------------------


class _Ctx:
    def abort(self, code, details):
        raise PermissionError(details)


def test_grpc_trust_capability_denies_unregistered(monkeypatch):
    pytest.importorskip("grpc")
    from maverick.grpc_api import server
    _patch(monkeypatch, {})  # engaged, no surface-wide "grpc" entry
    with pytest.raises(PermissionError):
        server._trust_capability(_Ctx(), None)


def test_grpc_trust_capability_allows_registered(monkeypatch):
    pytest.importorskip("grpc")
    from maverick.grpc_api import server
    reg = {"grpc": TrustedAgent(id="grpc", allow_tools=frozenset({"read_file"}))}
    _patch(monkeypatch, reg)
    cap = server._trust_capability(_Ctx(), None)
    assert cap is not None and cap.permits("read_file") and not cap.permits("shell")


def test_grpc_trust_capability_noop_when_disengaged(monkeypatch):
    pytest.importorskip("grpc")
    from maverick.grpc_api import server
    _patch(monkeypatch, {}, enforced=False)
    assert server._trust_capability(_Ctx(), None) is None


# ---- MCP gating -----------------------------------------------------------


def test_mcp_admits_registered_shared_token(monkeypatch):
    from maverick_mcp import http_transport as ht
    monkeypatch.setenv("MAVERICK_MCP_TOKEN", "shared")
    _patch(monkeypatch, {"mcp": TrustedAgent(id="mcp", direction="both")})
    assert ht._check_bearer("Bearer shared") is True


def test_mcp_denies_when_engaged_no_entry(monkeypatch):
    from maverick_mcp import http_transport as ht
    monkeypatch.setenv("MAVERICK_MCP_TOKEN", "shared")
    _patch(monkeypatch, {})  # engaged, no "mcp" surface entry
    assert ht._check_bearer("Bearer shared") is False


def test_mcp_per_caller_token(monkeypatch):
    from maverick_mcp import http_transport as ht
    monkeypatch.delenv("MAVERICK_MCP_TOKEN", raising=False)
    reg = {"vega": TrustedAgent(id="vega", mcp_token="v-tok", direction="both")}
    _patch(monkeypatch, reg)
    assert ht._check_bearer("Bearer v-tok") is True
    assert ht._check_bearer("Bearer nope") is False


def test_mcp_disengaged_auth_only(monkeypatch):
    from maverick_mcp import http_transport as ht
    monkeypatch.setenv("MAVERICK_MCP_TOKEN", "shared")
    _patch(monkeypatch, {}, enforced=False)
    assert ht._check_bearer("Bearer shared") is True
    assert ht._check_bearer("Bearer wrong") is False
