"""Cost split by tag (ROADMAP 2028 H1)."""
from __future__ import annotations

from maverick.cost.by_tag import gather, render, split_by_tag


def test_split_groups_and_sorts_by_cost():
    rows = [
        {"tag": "acme", "cost": 1.0, "in_tok": 100, "out_tok": 50},
        {"tag": "beta", "cost": 3.0, "in_tok": 200, "out_tok": 80},
        {"tag": "acme", "cost": 0.5, "in_tok": 10, "out_tok": 5},
    ]
    out = split_by_tag(rows)
    assert [b["tag"] for b in out] == ["beta", "acme"]  # cost desc
    acme = next(b for b in out if b["tag"] == "acme")
    assert acme["cost"] == 1.5
    assert acme["in_tok"] == 110
    assert acme["runs"] == 2


def test_missing_tag_goes_to_untagged():
    out = split_by_tag([{"cost": 2.0}, {"tag": "  ", "cost": 1.0}])
    assert len(out) == 1
    assert out[0]["tag"] == "(untagged)"
    assert out[0]["cost"] == 3.0


def test_non_numeric_cost_counts_as_zero():
    out = split_by_tag([{"tag": "x", "cost": "oops"}])
    assert out[0]["cost"] == 0.0
    assert out[0]["runs"] == 1


class _Ep:
    def __init__(self, cost, gid=None, tag=None, in_t=0, out_t=0):
        self.cost_dollars = cost
        self.goal_id = gid
        self.in_tokens = in_t
        self.out_tokens = out_t
        if tag is not None:
            self.tag = tag


class _Goal:
    def __init__(self, metadata=None, tags=None):
        self.metadata = metadata or {}
        self.tags = tags or []


class _World:
    def __init__(self, eps, goals):
        self._eps = eps
        self._goals = goals

    def list_episodes(self, limit=500):
        return self._eps

    def get_goal(self, gid):
        return self._goals.get(gid)


def test_gather_reads_tag_from_episode_then_goal():
    eps = [
        _Ep(1.0, tag="direct"),
        _Ep(2.0, gid=7),       # tag from goal metadata
        _Ep(0.0, tag="free"),  # zero cost dropped
    ]
    world = _World(eps, {7: _Goal(metadata={"tag": "from-goal"})})
    rows = gather(world)
    tags = sorted(r["tag"] for r in rows)
    assert tags == ["direct", "from-goal"]
    assert render(split_by_tag(rows)).startswith("tag")
