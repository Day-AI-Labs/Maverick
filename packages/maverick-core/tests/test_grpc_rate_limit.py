"""Per-caller request rate limiting on the gRPC API.

Complements maximum_concurrent_rpcs (in-flight cap) with a per-caller
request-rate cap, bucketed by Agent Trust agent id (else hashed peer), applied
at the auth chokepoint. MAVERICK_GRPC_RATE_LIMIT=0 disables it.
"""
from __future__ import annotations

import pytest
from maverick.grpc_api import server as gs


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    gs._GRPC_RATE_HITS.clear()
    monkeypatch.delenv("MAVERICK_GRPC_RATE_LIMIT", raising=False)
    yield
    gs._GRPC_RATE_HITS.clear()


class _Ctx:
    def __init__(self, peer="ipv4:10.0.0.7:5"):
        self._peer = peer

    def peer(self):
        return self._peer


class _Agent:
    id = "vega"


def test_disabled_when_zero(monkeypatch):
    monkeypatch.setenv("MAVERICK_GRPC_RATE_LIMIT", "0")
    for _ in range(1000):
        assert gs._grpc_rate_ok("agent:x") is True


def test_blocks_over_cap(monkeypatch):
    monkeypatch.setenv("MAVERICK_GRPC_RATE_LIMIT", "2")
    assert gs._grpc_rate_ok("agent:a")
    assert gs._grpc_rate_ok("agent:a")
    assert gs._grpc_rate_ok("agent:a") is False


def test_buckets_independent(monkeypatch):
    monkeypatch.setenv("MAVERICK_GRPC_RATE_LIMIT", "1")
    assert gs._grpc_rate_ok("agent:a")
    assert gs._grpc_rate_ok("agent:a") is False
    assert gs._grpc_rate_ok("agent:b") is True


def test_key_prefers_agent_then_peer():
    assert gs._grpc_rate_key(_Ctx(), _Agent()) == "agent:vega"
    key = gs._grpc_rate_key(_Ctx("ipv4:10.0.0.7:5"), None)
    assert key.startswith("peer:")
    # Distinct peers get distinct buckets.
    assert key != gs._grpc_rate_key(_Ctx("ipv4:10.0.0.8:5"), None)
