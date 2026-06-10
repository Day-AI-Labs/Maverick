"""Tests for the 2027-H1 safety tools: collusion_detector, coordinated_disclosure,
capability_delegation_graph, agent_identity. Deterministic and offline."""
from __future__ import annotations

from maverick.tools.agent_identity import agent_identity
from maverick.tools.collusion_detector import collusion_detector
from maverick.tools.coordinated_disclosure import coordinated_disclosure

# ---- collusion_detector ----

def test_collusion_echoed_reasoning():
    t = collusion_detector()
    out = t.fn({"messages": [
        {"agent": "proposer", "text": "the migration is safe because the lock is held"},
        {"agent": "verifier", "text": "the migration is safe because the lock is held"},
    ]})
    assert "COLLUSION SIGNALS" in out
    assert "echoed reasoning" in out


def test_collusion_rubber_stamp():
    t = collusion_detector()
    out = t.fn({"messages": [
        {"agent": "verifier", "text": "looks fine a", "verdict": "approve"},
        {"agent": "verifier", "text": "looks fine b", "verdict": "approved"},
        {"agent": "verifier", "text": "looks fine c", "verdict": "lgtm"},
    ]})
    assert "rubber-stamp" in out and "approved all 3" in out


def test_collusion_clean():
    t = collusion_detector()
    out = t.fn({"messages": [
        {"agent": "proposer", "text": "use a hash join here for the big table"},
        {"agent": "verifier", "text": "I disagree, a nested loop wins on this cardinality", "verdict": "reject"},
    ]})
    assert "CLEAN" in out


def test_collusion_validation():
    t = collusion_detector()
    assert t.fn({"messages": []}).startswith("ERROR")
    assert t.fn({"messages": [{"agent": "x"}]}).startswith("ERROR")
    assert t.fn({"messages": [{"agent": "x", "text": "y"}], "threshold": 2}).startswith("ERROR")


# ---- coordinated_disclosure ----

def test_cvd_status_open_and_expired():
    t = coordinated_disclosure()
    open_out = t.fn({"op": "status", "reported": "2027-01-01", "embargo_days": 90, "today": "2027-02-01"})
    assert "embargo: OPEN" in open_out and "disclose-on: 2027-04-01" in open_out
    assert "days-remaining: 59" in open_out
    exp = t.fn({"op": "status", "reported": "2027-01-01", "embargo_days": 90, "today": "2027-05-01"})
    assert "embargo: EXPIRED" in exp


def test_cvd_advisory():
    t = coordinated_disclosure()
    out = t.fn({
        "op": "advisory", "id": "MAV-2027-001", "severity": "high",
        "summary": "sandbox escape via crafted args", "reported": "2027-03-01",
        "embargo_days": 30, "today": "2027-03-10", "cve": "CVE-2027-1234",
    })
    assert "# Advisory MAV-2027-001  [HIGH]" in out
    assert "Coordinated-disclosure date: 2027-03-31 (embargo OPEN)" in out
    assert "CVE: CVE-2027-1234" in out


def test_cvd_validation():
    t = coordinated_disclosure()
    assert t.fn({"op": "status", "reported": "nope", "embargo_days": 30}).startswith("ERROR")
    assert t.fn({"op": "status", "reported": "2027-01-01", "embargo_days": -1}).startswith("ERROR")
    assert t.fn({"op": "advisory", "reported": "2027-01-01", "embargo_days": 1, "severity": "bogus", "id": "x", "summary": "y"}).startswith("ERROR")


# ---- agent_identity ----

def test_identity_stable_id():
    t = agent_identity()
    a = t.fn({"op": "id", "name": "verifier"})
    b = t.fn({"op": "id", "name": "verifier"})
    assert a == b and a.startswith("agent:")
    assert t.fn({"op": "id", "name": "coder"}) != a


def test_identity_sign_verify_roundtrip():
    t = agent_identity()
    signed = t.fn({"op": "sign", "name": "coder", "key": "s3cret", "payload": {"diff": "abc", "n": 1}})
    sig = [ln for ln in signed.splitlines() if ln.startswith("signature: ")][0].split(": ", 1)[1]
    ok = t.fn({"op": "verify", "name": "coder", "key": "s3cret", "payload": {"n": 1, "diff": "abc"}, "signature": sig})
    assert ok == "VALID"
    bad = t.fn({"op": "verify", "name": "coder", "key": "wrong", "payload": {"diff": "abc", "n": 1}, "signature": sig})
    assert bad == "INVALID"


def test_identity_validation():
    t = agent_identity()
    assert t.fn({"op": "sign", "name": "x"}).startswith("ERROR")
    assert t.fn({"op": "bogus"}).startswith("ERROR")


def test_all_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    for name in ("collusion_detector", "coordinated_disclosure",
                 "agent_identity"):
        assert name in names
