"""Channel federation: pseudonymized, signed, rate-limited message forwarding.

Offline: injected transport (lists), injected clock, isolated audit keys.
"""
from __future__ import annotations

import json
import os
import stat

import pytest
from maverick.channel_federation import (
    MAX_TEXT_CHARS,
    SCHEMA,
    FedMessage,
    InboundApplier,
    OutboundQueue,
    TokenBucket,
    enqueue,
    flush,
    make_envelope,
    pseudonymize,
)
from maverick.federation_envelope import FederationError

SECRET = "per-pair-secret"


def _peers(envelope=None, origin="peer-a", secret=SECRET):
    entry = {"origin": origin, "secret": secret,
             "pubkey": envelope["pubkey"] if envelope else "ab" * 32}
    return {origin: entry}


def _envelope(text="hello", user_id="alice", peer="home", **kw):
    return make_envelope("telegram", user_id, text, peer=peer, secret=SECRET,
                         origin=kw.pop("origin", "peer-a"), **kw)


# ---------------------------------------------------------- pseudonymity ----

def test_pseudonym_is_stable_secret_scoped_and_prefixed():
    p1 = pseudonymize("alice", SECRET)
    assert p1 == pseudonymize("alice", SECRET)
    assert p1.startswith("fed-") and len(p1) == 20
    assert p1 != pseudonymize("bob", SECRET)
    assert p1 != pseudonymize("alice", "other-secret")


def test_pseudonymize_requires_secret():
    with pytest.raises(FederationError):
        pseudonymize("alice", "")


def test_envelope_never_carries_raw_user_id():
    env = _envelope(user_id="alice@example.com")
    assert "alice" not in json.dumps(env)
    assert env["user_id"].startswith("fed-")
    assert env["schema"] == SCHEMA and env["to"] == "home"


def test_envelope_bounds_text():
    env = _envelope(text="x" * (MAX_TEXT_CHARS + 500))
    assert len(env["text"]) == MAX_TEXT_CHARS


# ------------------------------------------------------------- outbound ----

def test_queue_is_bounded_0600_and_counts_drops(tmp_path):
    q = OutboundQueue(path=tmp_path / "outbox.json", max_len=2)
    for i in range(4):
        q.append({"n": i})
    assert len(q) == 2
    assert q.dropped == 2
    assert q._load()["items"][0]["n"] == 2  # oldest dropped first
    assert stat.S_IMODE(os.stat(q.path).st_mode) == 0o600


def test_enqueue_requires_configured_peer_with_secret(tmp_path):
    q = OutboundQueue(path=tmp_path / "outbox.json")
    with pytest.raises(FederationError):
        enqueue(q, "stranger", "telegram", "alice", "hi", peers={})
    no_secret = {"peer-a": {"origin": "peer-a", "pubkey": "ab" * 32}}
    with pytest.raises(FederationError):
        enqueue(q, "peer-a", "telegram", "alice", "hi", peers=no_secret)
    assert len(q) == 0


def test_enqueue_and_flush_through_injected_transport(tmp_path):
    q = OutboundQueue(path=tmp_path / "outbox.json")
    enqueue(q, "peer-a", "telegram", "alice", "one", peers=_peers())
    enqueue(q, "peer-a", "telegram", "alice", "two", peers=_peers())
    sent: list[dict] = []
    assert flush(q, send=sent.append) == 2
    assert [e["text"] for e in sent] == ["one", "two"]
    assert len(q) == 0


def test_flush_keeps_remainder_on_transport_failure(tmp_path):
    q = OutboundQueue(path=tmp_path / "outbox.json")
    enqueue(q, "peer-a", "telegram", "alice", "one", peers=_peers())
    enqueue(q, "peer-a", "telegram", "alice", "two", peers=_peers())

    calls = []

    def flaky(env):
        calls.append(env)
        if len(calls) == 2:
            raise OSError("peer down")

    assert flush(q, send=flaky) == 1
    assert len(q) == 1  # the failed envelope is retained for retry
    assert q._load()["items"][0]["text"] == "two"


# -------------------------------------------------------------- inbound ----

def _applier(handled, env, **kw):
    kw.setdefault("peers", _peers(env))
    kw.setdefault("local", "home")
    kw.setdefault("limiter", TokenBucket(rate_per_min=600, clock=lambda: 0.0))
    return InboundApplier(lambda m: handled.append(m) or "done", **kw)


def test_inbound_round_trip_marks_fed_channel():
    handled: list[FedMessage] = []
    env = _envelope(text="ship it", user_id="alice")
    out = _applier(handled, env).apply(env)
    assert out["applied"] and out["result"] == "done"
    (msg,) = handled
    assert msg.channel == "fed:peer-a"
    assert msg.text == "ship it"
    assert msg.user_id == pseudonymize("alice", SECRET)


def test_inbound_rejects_tamper_unknown_origin_and_missing_sig():
    handled: list = []
    env = _envelope()
    tampered = {**env, "text": "evil"}
    assert not _applier(handled, env).apply(tampered)["applied"]

    unknown = InboundApplier(handled.append, peers={}, local="home",
                             limiter=TokenBucket(clock=lambda: 0.0))
    assert "trust list" in unknown.apply(env)["reason"]

    unsigned = {k: v for k, v in env.items() if k != "sig"}
    assert not _applier(handled, env).apply(unsigned)["applied"]
    assert not _applier(handled, env).apply("garbage")["applied"]
    assert handled == []


def test_inbound_rejects_misdirected_envelope():
    handled: list = []
    env = _envelope(peer="someone-else")
    out = _applier(handled, env).apply(env)
    assert not out["applied"]
    assert "addressed to" in out["reason"]
    assert handled == []


def test_inbound_rejects_without_crypto(monkeypatch):
    handled: list = []
    env = _envelope()
    applier = _applier(handled, env)
    import maverick.audit.signing as audit_signing
    monkeypatch.setattr(audit_signing, "_have_crypto", lambda: False)
    out = applier.apply(env)
    assert not out["applied"] and "cryptography" in out["reason"]


def test_rate_limit_per_peer_with_injected_clock():
    handled: list = []
    now = {"t": 0.0}
    bucket = TokenBucket(rate_per_min=60, burst=2, clock=lambda: now["t"])
    env = _envelope()
    applier = _applier(handled, env, limiter=bucket)
    assert applier.apply(env)["applied"]
    assert applier.apply(env)["applied"]
    out = applier.apply(env)  # burst of 2 exhausted
    assert not out["applied"] and "rate limited" in out["reason"]
    now["t"] += 1.0  # 60/min -> one token per second
    assert applier.apply(env)["applied"]
    assert len(handled) == 3


def test_apply_many_iterates_injected_receive():
    handled: list = []
    env = _envelope()
    results = _applier(handled, env).apply_many(iter([env, "junk", env]))
    assert [r["applied"] for r in results] == [True, False, True]
