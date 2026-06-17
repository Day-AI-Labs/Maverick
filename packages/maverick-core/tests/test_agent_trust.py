"""Agent Trust Plane: the single registry + decision point for external
agents. Covers registry parsing (fail-closed on junk), the engaged/disengaged
posture, inbound/outbound/direction/capability/budget decisions, pinned-key
identity verification, data-scope gating, and the federation + A2A wiring."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick import agent_trust
from maverick.agent_trust import (
    TrustedAgent,
    clamp_budget,
    decide_inbound,
    decide_outbound,
    load_registry,
)

# ---- registry parsing -----------------------------------------------------


def test_load_registry_parses_entries():
    cfg = {"agent_trust": {"agents": [
        {"id": "vega", "pubkey": "ab" * 32, "direction": "both",
         "allow_tools": ["read_file", "http_fetch"], "max_risk": "medium",
         "max_dollars": 2.0, "max_wall_seconds": 600, "data_scopes": ["support"]},
        {"id": "copilot", "direction": "inbound", "allow_tools": ["research"]},
    ]}}
    reg = load_registry(cfg)
    assert set(reg) == {"vega", "copilot"}
    vega = reg["vega"]
    assert vega.pubkey == "ab" * 32
    assert vega.allow_tools == frozenset({"read_file", "http_fetch"})
    assert vega.max_dollars == 2.0
    assert vega.data_scopes == frozenset({"support"})
    assert reg["copilot"].pubkey == ""  # no pinned key is allowed (migration)


def test_load_registry_is_fail_closed_on_junk():
    cfg = {"agent_trust": {"agents": [
        "not-a-table",
        {"id": "BAD ID"},                      # invalid charset -> skipped
        {"id": "x", "pubkey": "nothex"},       # bad pubkey -> kept, key dropped
        {"id": "y", "direction": "sideways"},  # bad direction -> defaults to both
        {"id": "dup", "max_risk": "low"},
        {"id": "dup", "max_risk": "high"},     # duplicate -> first wins
    ]}}
    reg = load_registry(cfg)
    assert set(reg) == {"x", "y", "dup"}
    assert reg["x"].pubkey == ""
    assert reg["y"].direction == "both"
    assert reg["dup"].max_risk == "low"


def test_load_registry_empty_when_absent_or_malformed():
    assert load_registry({}) == {}
    assert load_registry({"agent_trust": {"agents": "oops"}}) == {}


# ---- posture (engaged / disengaged) --------------------------------------


def test_enforced_env_overrides(monkeypatch):
    monkeypatch.setenv("MAVERICK_AGENT_TRUST", "1")
    assert agent_trust.agent_trust_enforced() is True
    monkeypatch.setenv("MAVERICK_AGENT_TRUST", "0")
    assert agent_trust.agent_trust_enforced() is False


def test_enforced_follows_enterprise_mode(monkeypatch):
    monkeypatch.delenv("MAVERICK_AGENT_TRUST", raising=False)
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    assert agent_trust.agent_trust_enforced() is True


def test_disengaged_is_a_noop_allow():
    # No registry, no ceiling, always allowed -> existing deployments unchanged.
    d = decide_inbound("anybody", requested_tools=["shell"], enforced=False)
    assert d.allowed and d.rule == "disabled" and d.capability is None
    assert decide_outbound("anybody", enforced=False).allowed


# ---- inbound decisions ----------------------------------------------------


def _reg(*agents: TrustedAgent) -> dict[str, TrustedAgent]:
    return {a.id: a for a in agents}


def test_inbound_unknown_agent_denied_when_engaged():
    d = decide_inbound("ghost", registry={}, enforced=True)
    assert d.denied and d.rule == "not_in_registry"


def test_inbound_direction_enforced():
    reg = _reg(TrustedAgent(id="out", direction="outbound"))
    d = decide_inbound("out", registry=reg, enforced=True)
    assert d.denied and d.rule == "direction"


def test_inbound_capability_ceiling_blocks_unpermitted_tool():
    reg = _reg(TrustedAgent(id="vega", allow_tools=frozenset({"read_file"})))
    d = decide_inbound("vega", requested_tools=["shell"], registry=reg, enforced=True)
    assert d.denied and d.rule == "capability"


def test_inbound_allows_within_ceiling_and_returns_capability():
    reg = _reg(TrustedAgent(id="vega", allow_tools=frozenset({"read_file"}),
                            max_risk="medium"))
    d = decide_inbound("vega", requested_tools=["read_file"], registry=reg,
                       enforced=True)
    assert d.allowed and d.rule == "allow"
    assert d.capability is not None
    assert d.capability.permits("read_file")
    assert not d.capability.permits("shell")


def test_inbound_risk_above_ceiling_denied():
    reg = _reg(TrustedAgent(id="vega", max_risk="low"))
    d = decide_inbound("vega", max_risk="high", registry=reg, enforced=True)
    assert d.denied and d.rule == "capability"


# ---- outbound decisions ---------------------------------------------------


def test_outbound_unknown_denied_known_allowed():
    assert decide_outbound("ghost", registry={}, enforced=True).denied
    reg = _reg(TrustedAgent(id="vega", direction="both"))
    assert decide_outbound("vega", registry=reg, enforced=True).allowed
    reg2 = _reg(TrustedAgent(id="inb", direction="inbound"))
    assert decide_outbound("inb", registry=reg2, enforced=True).denied


# ---- budget clamp + scopes ------------------------------------------------


def test_clamp_budget_takes_the_tighter_bound():
    a = TrustedAgent(id="v", max_dollars=2.0, max_wall_seconds=600)
    assert clamp_budget(a, max_dollars=5.0, max_wall_seconds=300) == (2.0, 300)
    assert clamp_budget(a, max_dollars=1.0) == (1.0, 600)
    assert clamp_budget(None, max_dollars=5.0) == (5.0, None)


def test_permits_scope():
    a = TrustedAgent(id="v", data_scopes=frozenset({"support"}))
    assert a.permits_scope(None)        # unscoped query carries no department
    assert a.permits_scope("support")
    assert not a.permits_scope("finance")
    assert not TrustedAgent(id="w").permits_scope("support")  # empty == none


# ---- pinned-key identity --------------------------------------------------


def test_verify_identity_against_pinned_key():
    pytest.importorskip("cryptography")
    from maverick import federation_envelope as fe

    env = fe.sign_envelope({"schema": "maverick-test/1", "origin": "vega",
                            "created_at": 1.0, "payload": "hi"})
    pinned = env["pubkey"]
    reg = _reg(TrustedAgent(id="vega", pubkey=pinned))

    ok, _ = agent_trust.verify_identity(
        "vega", env, expected_schema="maverick-test/1", registry=reg)
    assert ok

    # Unknown agent and an agent without a pinned key both fail closed.
    ok2, reason2 = agent_trust.verify_identity(
        "ghost", env, expected_schema="maverick-test/1", registry={})
    assert not ok2 and "registry" in reason2
    ok3, reason3 = agent_trust.verify_identity(
        "nopub", env, expected_schema="maverick-test/1",
        registry=_reg(TrustedAgent(id="nopub")))
    assert not ok3 and "pinned" in reason3

    # Tampering with a signed field is rejected.
    tampered = dict(env, payload="changed")
    ok4, _ = agent_trust.verify_identity(
        "vega", tampered, expected_schema="maverick-test/1", registry=reg)
    assert not ok4


# ---- federation wiring ----------------------------------------------------


class _Goals:
    def __init__(self):
        self.started = []

    def start_goal(self, title, description="", **kw):
        self.started.append({"title": title, **kw})
        return len(self.started)

    def status(self, goal_id):
        return SimpleNamespace(status="done", result="ok")


def _fed_service(monkeypatch, *, registry, enforced=True):
    from maverick import federation
    from maverick.federation import FederationService, Peer

    monkeypatch.setattr(agent_trust, "agent_trust_enforced", lambda: enforced)
    monkeypatch.setattr(agent_trust, "load_registry", lambda cfg=None: registry)
    rows: list[dict] = []
    svc = FederationService(
        node="B", peers=[Peer("A", "a:1", "tok")], local_grant=None,
        goal_service=_Goals(), record=lambda k, **kw: rows.append({"kind": k, **kw}),
    )
    return svc, rows, federation


def test_federation_inbound_denied_for_unregistered_peer(monkeypatch):
    # Authenticated by shared token, but absent from the trust registry ->
    # refused once the plane is engaged (the shared token is no longer enough).
    svc, rows, _ = _fed_service(monkeypatch, registry={})
    reply = svc.delegate_goal({"auth_token": "tok", "correlation_id": "c1",
                               "goal_title": "x"})
    assert reply["accepted"] is False
    assert "trust registry" in reply["reason"]
    # The federation seam records its "received" refusal half with the reason.
    assert any("trust registry" in str(r.get("reason", "")) for r in rows)


def test_federation_inbound_allowed_for_registered_peer(monkeypatch):
    reg = _reg(TrustedAgent(id="A", direction="both",
                            allow_tools=frozenset({"read_file"})))
    svc, _rows, _ = _fed_service(monkeypatch, registry=reg)
    reply = svc.delegate_goal({"auth_token": "tok", "correlation_id": "c2",
                               "goal_title": "do it",
                               "requested_tools": ["read_file"]})
    assert reply["accepted"] is True
    assert reply["goal_id"] >= 1


def test_federation_inbound_tool_outside_ceiling_refused(monkeypatch):
    reg = _reg(TrustedAgent(id="A", allow_tools=frozenset({"read_file"})))
    svc, _rows, _ = _fed_service(monkeypatch, registry=reg)
    reply = svc.delegate_goal({"auth_token": "tok", "correlation_id": "c3",
                               "goal_title": "do it", "requested_tools": ["shell"]})
    assert reply["accepted"] is False


def test_federation_outbound_blocked_for_unregistered_peer(monkeypatch):
    from maverick.federation import FederationNode, Peer

    monkeypatch.setattr(agent_trust, "agent_trust_enforced", lambda: True)
    monkeypatch.setattr(agent_trust, "load_registry", lambda cfg=None: {})

    class _Boom:
        def call(self, *a, **k):  # must never be reached
            raise AssertionError("dialed a peer the trust plane forbade")

    node = FederationNode(node="A", peers=[Peer("B", "b:1", "tok")],
                          transport_factory=lambda peer: _Boom(),
                          record=lambda *a, **k: None)
    out = node.delegate("B", "title")
    assert out.accepted is False and "trust registry" in out.reason


def test_federation_disengaged_unchanged(monkeypatch):
    # The default posture: plane disengaged -> shared-token auth alone admits a
    # peer with no registry entry, exactly as before this feature.
    reg: dict = {}
    svc, _rows, _ = _fed_service(monkeypatch, registry=reg, enforced=False)
    reply = svc.delegate_goal({"auth_token": "tok", "correlation_id": "c4",
                               "goal_title": "legacy"})
    assert reply["accepted"] is True
