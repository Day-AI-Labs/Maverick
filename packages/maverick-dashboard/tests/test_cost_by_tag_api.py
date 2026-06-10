"""The cost-attribution API buckets episode spend by tag."""
from __future__ import annotations

import types

from fastapi.testclient import TestClient
from maverick_dashboard import app as app_mod
from maverick_dashboard.app import app

client = TestClient(app)


class _Ep:
    def __init__(self, goal_id, cost, tag=None, in_tok=10, out_tok=5):
        self.goal_id = goal_id
        self.cost_dollars = cost
        self.in_tokens = in_tok
        self.out_tokens = out_tok
        if tag is not None:
            self.tag = tag


class _FakeWorld:
    def __init__(self):
        self._eps = [
            _Ep(1, 0.50, tag="team-a"),
            _Ep(1, 0.25, tag="team-a"),
            _Ep(2, 0.40, tag="team-b"),
            _Ep(3, 0.10),  # untagged
        ]

    def list_episodes(self, limit=500):
        return self._eps[:limit]

    def get_goal(self, gid):
        return types.SimpleNamespace(metadata=None, tags=None)


def test_cost_by_tag_buckets(monkeypatch):
    monkeypatch.setattr(app_mod, "_world", lambda: _FakeWorld())
    r = client.get("/api/v1/cost/by-tag")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tag_field"] == "tag"
    buckets = {b["tag"]: b for b in data["buckets"]}
    assert buckets["team-a"]["cost"] == 0.75 and buckets["team-a"]["runs"] == 2
    assert buckets["team-b"]["cost"] == 0.40
    assert "(untagged)" in buckets
    # Sorted by spend: team-a first.
    assert data["buckets"][0]["tag"] == "team-a"


def test_cost_by_tag_limit_clamped(monkeypatch):
    seen = {}

    class _W(_FakeWorld):
        def list_episodes(self, limit=500):
            seen["limit"] = limit
            return []

    monkeypatch.setattr(app_mod, "_world", lambda: _W())
    assert client.get("/api/v1/cost/by-tag?limit=999999").status_code == 200
    assert seen["limit"] == 10_000
