"""Verified handoffs over the cross-agent bus (maverick.bus_handoff): a delegation
rides agent_bus as a signed Envelope, minted by the run's HandoffAuthority and
verified on receipt. The bridge must accept an authentic in-scope handoff (handing
back the attenuated grant) and reject tamper / replay / forged-issuer / expiry /
out-of-scope -- while leaving plain (non-handoff) bus traffic untouched."""
from __future__ import annotations

import time

import pytest
from maverick import agent_bus
from maverick.bus_handoff import HandoffAuthority, receive_handoff, send_handoff
from maverick.capability import Capability
from maverick.handoff import Envelope


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except BaseException:  # absent OR a broken backend (sandbox pyo3 panic)
        return False


crypto = pytest.mark.skipif(not _have_crypto(), reason="cryptography unavailable")


@pytest.fixture(autouse=True)
def _clean_bus():
    agent_bus.clear()
    yield
    agent_bus.clear()


def _grant(principal="agent:worker-1", **kw) -> Capability:
    kw.setdefault("allow_tools", frozenset({"read_file", "knowledge_search"}))
    kw.setdefault("max_risk", "low")
    return Capability(principal=principal, **kw)


# --- crypto-free paths (run everywhere) ------------------------------------

def test_empty_inbox_returns_none():
    assert receive_handoff(None, "agent:nobody-9") is None


def test_plain_message_passes_through_unverified():
    agent_bus.send("agent:a-1", "agent:b-1", {"note": "hello"})
    d = receive_handoff(None, "agent:b-1")
    assert d is not None
    assert not d.is_handoff and d.verdict is None
    assert d.payload == {"note": "hello"} and d.sender == "agent:a-1"


def test_envelope_without_an_authority_is_rejected():
    # An Envelope on the bus but no run authority to anchor trust -> fail closed.
    env = Envelope(sender="agent:a-1", recipient="agent:b-1", task="t",
                   grant=_grant(), nonce="n1", ts=time.time())
    agent_bus.send("agent:a-1", "agent:b-1", env)
    d = receive_handoff(None, "agent:b-1")
    assert d is not None and d.is_handoff
    assert not d.ok and d.verdict.rule == "no_authority"


# --- signed round-trips (CI; needs cryptography) ---------------------------

@crypto
def test_verified_handoff_round_trips_and_returns_the_grant():
    auth = HandoffAuthority.for_run()
    grant = _grant(principal="agent:worker-1", allow_tools=frozenset({"read_file"}))
    nonce = send_handoff(auth, sender="agent:lead-0", recipient="agent:worker-1",
                         grant=grant, task="read the spec", required_tools=("read_file",))
    d = receive_handoff(auth, "agent:worker-1")
    assert d is not None and d.ok and d.verdict.rule == "ok"
    # the receiver runs under exactly the delegated grant
    assert d.grant is not None and d.grant.permits("read_file") and not d.grant.permits("shell")
    assert isinstance(nonce, str) and nonce


@crypto
def test_tampering_in_transit_is_rejected():
    import dataclasses
    auth = HandoffAuthority.for_run()
    env = auth.mint(sender="agent:lead-0", recipient="agent:worker-1",
                    grant=_grant(principal="agent:worker-1"), task="read")
    # an attacker on the wire rewrites the task; the signature no longer covers it
    agent_bus.send("agent:lead-0", "agent:worker-1",
                   dataclasses.replace(env, task="exfiltrate secrets"))
    d = receive_handoff(auth, "agent:worker-1")
    assert not d.ok and d.verdict.rule == "tampered"


@crypto
def test_replayed_handoff_is_rejected():
    auth = HandoffAuthority.for_run()
    env = auth.mint(sender="agent:lead-0", recipient="agent:worker-1",
                    grant=_grant(principal="agent:worker-1"), task="read")
    agent_bus.send("agent:lead-0", "agent:worker-1", env)
    agent_bus.send("agent:lead-0", "agent:worker-1", env)  # same nonce, replayed
    first = receive_handoff(auth, "agent:worker-1")
    second = receive_handoff(auth, "agent:worker-1")
    assert first.ok
    assert not second.ok and second.verdict.rule == "replay"


@crypto
def test_forged_issuer_is_rejected():
    minting = HandoffAuthority.for_run()       # some other run's / attacker's issuer
    receiving = HandoffAuthority.for_run()     # this run's trust root
    env = minting.mint(sender="agent:lead-0", recipient="agent:worker-1",
                       grant=_grant(principal="agent:worker-1"), task="read")
    agent_bus.send("agent:lead-0", "agent:worker-1", env)
    d = receive_handoff(receiving, "agent:worker-1")
    assert not d.ok and d.verdict.rule == "untrusted_issuer"


@crypto
def test_out_of_scope_required_tool_is_rejected():
    auth = HandoffAuthority.for_run()
    grant = _grant(principal="agent:worker-1", allow_tools=frozenset({"read_file"}))
    send_handoff(auth, sender="agent:lead-0", recipient="agent:worker-1",
                 grant=grant, task="do it", required_tools=("read_file", "shell"))
    d = receive_handoff(auth, "agent:worker-1")
    assert not d.ok and d.verdict.rule == "out_of_scope"


@crypto
def test_expired_grant_is_rejected():
    auth = HandoffAuthority.for_run()
    grant = _grant(principal="agent:worker-1", expires_at=time.time() - 1)  # already expired
    env = auth.mint(sender="agent:lead-0", recipient="agent:worker-1", grant=grant, task="read")
    agent_bus.send("agent:lead-0", "agent:worker-1", env)
    d = receive_handoff(auth, "agent:worker-1", now=time.time())
    assert not d.ok and d.verdict.rule == "grant_expired"
