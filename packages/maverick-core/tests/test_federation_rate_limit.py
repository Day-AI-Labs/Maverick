"""Per-peer request-rate limiting on inbound federation delegations.

The sibling gRPC API pairs maximum_concurrent_rpcs (in-flight cap) with a
per-caller request-rate cap; federation had only the former. Each accepted
DelegateGoal spawns a real goal run, so an authenticated-but-flooding peer
could launch goals unthrottled. _fed_rate_ok caps delegations per peer over a
sliding 60s window. MAVERICK_FEDERATION_RATE_LIMIT=0 disables it.
"""
from __future__ import annotations

import pytest
from maverick import federation as fed
from maverick.federation import FederationService, Peer


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    fed._fed_rate_hits.clear()
    monkeypatch.delenv("MAVERICK_FEDERATION_RATE_LIMIT", raising=False)
    yield
    fed._fed_rate_hits.clear()


class _Goals:
    def __init__(self):
        self.started = 0

    def start_goal(self, *a, **kw):
        self.started += 1
        return self.started


def test_delegate_goal_refuses_over_cap(monkeypatch):
    """End-to-end: a peer flooding DelegateGoal is refused after the cap, and
    no further goal runs are spawned."""
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "2")
    goals = _Goals()
    svc = FederationService(
        node="B", peers=[Peer("A", "a:1", "tok")],
        local_grant=None, goal_service=goals,
    )

    def _call(i):
        return svc.call("DelegateGoal", {
            "goal_title": "t", "goal_description": "d",
            "auth_token": "tok", "correlation_id": f"c{i}",
        })

    assert _call(1)["accepted"] is True
    assert _call(2)["accepted"] is True
    refused = _call(3)
    assert refused["accepted"] is False
    assert "rate limit" in refused["reason"]
    assert goals.started == 2  # the throttled call never reached goal creation


def test_disabled_when_zero(monkeypatch):
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "0")
    for _ in range(1000):
        assert fed._fed_rate_ok("peer:alpha") is True


def test_blocks_over_cap(monkeypatch):
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "2")
    assert fed._fed_rate_ok("peer:alpha")
    assert fed._fed_rate_ok("peer:alpha")
    assert fed._fed_rate_ok("peer:alpha") is False


def test_buckets_independent(monkeypatch):
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "1")
    assert fed._fed_rate_ok("peer:alpha")
    assert fed._fed_rate_ok("peer:alpha") is False
    assert fed._fed_rate_ok("peer:beta") is True


def test_window_slides(monkeypatch):
    """A hit older than the 60s window no longer counts against the cap."""
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "1")
    now = 1_000.0
    assert fed._fed_rate_ok("peer:alpha", now=now) is True
    assert fed._fed_rate_ok("peer:alpha", now=now + 1) is False
    assert fed._fed_rate_ok("peer:alpha", now=now + 61) is True  # first hit aged out


def test_idle_buckets_are_swept(monkeypatch):
    """Idle per-peer buckets are reclaimed when the map exceeds the cap."""
    from collections import deque
    monkeypatch.setenv("MAVERICK_FEDERATION_RATE_LIMIT", "5")
    monkeypatch.setattr(fed, "_FED_RATE_MAX_KEYS", 10)
    old = fed.time.monotonic() - 120.0
    for i in range(50):
        fed._fed_rate_hits[f"peer:stale{i}"] = deque([old])
    assert fed._fed_rate_ok("peer:active") is True
    assert len(fed._fed_rate_hits) < 50
    assert "peer:active" in fed._fed_rate_hits
