"""collusion_detector: multi-agent collusion signatures."""
from __future__ import annotations

from maverick.tools.collusion_detector import collusion_detector


def _scan(messages, **kw):
    return collusion_detector().fn({"op": "scan", "messages": messages, **kw})


def test_clean_balanced_traffic():
    msgs = [
        {"from": "a", "to": "b", "content": "x"},
        {"from": "b", "to": "c", "content": "y"},
        {"from": "c", "to": "a", "content": "z"},
        {"from": "a", "to": "c", "content": "w"},
    ]
    assert _scan(msgs).startswith("CLEAN")


def test_backchannel_detected():
    msgs = [{"from": "a", "to": "b", "content": str(i)} for i in range(8)]
    msgs.append({"from": "c", "to": "d", "content": "lone"})
    out = _scan(msgs)
    assert out.startswith("SUSPECT") and "back-channel" in out


def test_scripted_identical_payload():
    msgs = [{"from": "a", "to": "b", "content": "RUN PLAN 7"} for _ in range(3)]
    msgs += [{"from": "x", "to": "y", "content": str(i)} for i in range(3)]
    out = _scan(msgs, threshold=0.99)
    assert "scripted" in out


def test_reciprocal_approval_loop():
    msgs = [
        {"from": "a", "to": "b", "content": "ok", "approves": True},
        {"from": "b", "to": "a", "content": "ok", "approves": True},
        {"from": "c", "to": "d", "content": "n"},
        {"from": "d", "to": "c", "content": "n"},
    ]
    out = _scan(msgs, threshold=0.99)
    assert "reciprocal-approval" in out


def test_missing_messages_errors():
    assert collusion_detector().fn({"op": "scan"}).startswith("ERROR")
