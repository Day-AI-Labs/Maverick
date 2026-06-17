"""Phase 2 — signed-identity for federation delegation. The pinned Ed25519 key
becomes load-bearing: a leaked shared token alone can no longer impersonate a
peer that has a pinned key. Covers round-trip verify, unsigned/ tampered/
replayed/ stale refusals, require_signed, and the disengaged/migration paths."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick import agent_trust, federation
from maverick.agent_trust import TrustedAgent
from maverick.federation import FederationNode, FederationService, Peer

pytest.importorskip("cryptography")


def _local_pubkey() -> str:
    from maverick.audit import signing as asig
    _, pub, _ = asig._load_or_create_keypair()
    return pub.hex()


class _Goals:
    def __init__(self):
        self.started = []

    def start_goal(self, title, description="", **kw):
        self.started.append({"title": title, **kw})
        return len(self.started)

    def status(self, goal_id):
        return SimpleNamespace(status="done", result="ok")


def _engage(monkeypatch, registry, *, enforced=True):
    monkeypatch.setattr(agent_trust, "load_trust_state", lambda: (enforced, registry))
    monkeypatch.setattr(agent_trust, "agent_trust_enforced", lambda cfg=None: enforced)
    # Fresh replay cache per test.
    federation._seen_sigs.clear()


# Node/peer/registry names must satisfy the lowercase origin/id charset
# (federation_envelope._ORIGIN_RE / agent_trust._ID_RE) for signed identity.
def _service():
    return FederationService(
        node="b", peers=[Peer("a", "a:1", "tok")], local_grant=None,
        goal_service=_Goals(), record=lambda *a, **k: None,
    )


def _node(service):
    return FederationNode(node="a", peers=[Peer("b", "b:1", "tok")],
                          transport_factory=lambda peer: service,
                          record=lambda *a, **k: None)


def _both_sides(pinned: str) -> dict:
    """Registry with the receiver's view of caller 'a' (pinned key, inbound) and
    the caller's view of peer 'b' (outbound), as two real nodes would each hold."""
    return {
        "a": TrustedAgent(id="a", pubkey=pinned, allow_tools=frozenset({"read_file"})),
        "b": TrustedAgent(id="b", allow_tools=frozenset({"read_file"})),
    }


def _signed_payload(**over):
    """A delegation payload signed by the local audit key, as delegate() builds."""
    corr = over.pop("correlation_id", "c1")
    title = over.pop("goal_title", "do it")
    desc = over.pop("goal_description", "")
    tools = over.pop("requested_tools", ["read_file"])
    signed = federation._sign_delegation("a", corr, title, desc, tools, None)
    payload = {
        "auth_token": "tok", "correlation_id": corr, "goal_title": title,
        "goal_description": desc, "requested_tools": tools, "max_risk": "",
        **signed,
    }
    payload.update(over)
    return payload


# ---- round trip -----------------------------------------------------------


def test_signed_delegation_round_trip(monkeypatch):
    _engage(monkeypatch, _both_sides(_local_pubkey()))
    svc = _service()
    out = _node(svc).delegate("b", "do it", requested_tools=["read_file"])
    assert out.accepted is True and out.goal_id == 1


def test_unsigned_refused_when_peer_has_pinned_key(monkeypatch):
    _engage(monkeypatch, _both_sides(_local_pubkey()))
    # Client cannot sign -> sends unsigned -> receiver refuses (pinned key set).
    monkeypatch.setattr(federation, "_sign_delegation", lambda *a, **k: {})
    out = _node(_service()).delegate("b", "do it", requested_tools=["read_file"])
    assert out.accepted is False and "signature" in out.reason.lower()


def test_tampered_signature_refused(monkeypatch):
    # Pin a DIFFERENT key than the one that signs -> signature can't verify.
    reg = {"a": TrustedAgent(id="a", pubkey="ab" * 32,
                             allow_tools=frozenset({"read_file"}))}
    _engage(monkeypatch, reg)
    reply = _service().delegate_goal(_signed_payload())
    assert reply["accepted"] is False
    assert "signature" in reply["reason"].lower()


def test_replayed_signature_refused(monkeypatch):
    _engage(monkeypatch, _both_sides(_local_pubkey()))
    svc = _service()
    payload = _signed_payload()
    first = svc.delegate_goal(payload)
    assert first["accepted"] is True
    # Same signed envelope again -> replay caught.
    second = svc.delegate_goal(dict(payload, correlation_id="c1"))
    assert second["accepted"] is False and "replay" in second["reason"].lower()


def test_stale_signature_refused(monkeypatch):
    _engage(monkeypatch, _both_sides(_local_pubkey()))
    payload = _signed_payload()
    payload["created_at"] = 1.0  # epoch 1970 -> way outside the freshness window
    reply = _service().delegate_goal(payload)
    assert reply["accepted"] is False and (
        "stale" in reply["reason"].lower() or "future" in reply["reason"].lower())


# ---- require_signed + migration -------------------------------------------


def test_require_signed_without_pinned_key_refused(monkeypatch):
    reg = {"a": TrustedAgent(id="a", allow_tools=frozenset({"read_file"}))}  # no pubkey
    _engage(monkeypatch, reg)
    monkeypatch.setattr(federation, "require_signed", lambda: True)
    reply = _service().delegate_goal(_signed_payload())
    assert reply["accepted"] is False and "pinned key" in reply["reason"]


def test_migration_no_pinned_key_allows_on_token(monkeypatch):
    # Engaged but the peer has no pinned key and require_signed is off ->
    # shared-token path still works (migration), even unsigned.
    reg = {"a": TrustedAgent(id="a", allow_tools=frozenset({"read_file"}))}
    _engage(monkeypatch, reg)
    monkeypatch.setattr(federation, "require_signed", lambda: False)
    reply = _service().delegate_goal({
        "auth_token": "tok", "correlation_id": "c9", "goal_title": "x",
        "requested_tools": ["read_file"],
    })
    assert reply["accepted"] is True


def test_disengaged_unsigned_delegation_accepted(monkeypatch):
    _engage(monkeypatch, {}, enforced=False)
    reply = _service().delegate_goal({
        "auth_token": "tok", "correlation_id": "c0", "goal_title": "legacy",
    })
    assert reply["accepted"] is True


# ---- envelope helper ------------------------------------------------------


def test_fresh_window():
    import time
    now = time.time()
    assert federation._fresh(now, now=now)
    assert not federation._fresh(now - 10_000, now=now)
    assert not federation._fresh(now + 10_000, now=now)
    assert not federation._fresh(0)
