"""PostgresWorldModel round-trip — runs only when MAVERICK_PG_DSN is set.

Skipped locally and in the normal test matrix (no Postgres available); the
dedicated CI ``postgres`` job stands up a Postgres service + DSN and runs this.
It's the first DB-backed test for the Postgres backend and the harness future
method-parity work can extend (so parity is testable, not shipped blind).
"""
from __future__ import annotations

import os

import pytest

_DSN = os.environ.get("MAVERICK_PG_DSN")
pytestmark = pytest.mark.skipif(
    not _DSN, reason="MAVERICK_PG_DSN not set (no Postgres service)"
)


@pytest.fixture
def world():
    from maverick.world_model_backends.postgres import PostgresWorldModel
    w = PostgresWorldModel(dsn=_DSN)
    try:
        yield w
    finally:
        w.close()


def test_goal_lifecycle(world):
    gid = world.create_goal("build the thing", description="desc")
    assert isinstance(gid, int)

    g = world.get_goal(gid)
    assert g is not None
    assert g.title == "build the thing"
    assert g.description == "desc"
    assert g.status == "pending"

    # A pending goal is "open" -> appears in the active list; resolving it drops it.
    assert any(x.id == gid for x in world.list_active_goals())
    world.set_goal_status(gid, "done", result="shipped")
    g2 = world.get_goal(gid)
    assert g2.status == "done"
    assert g2.result == "shipped"
    assert not any(x.id == gid for x in world.list_active_goals())


def test_status_only_update_preserves_result(world):
    # COALESCE(%s, result): a later status-only update (result=None) must not
    # wipe an existing result.
    gid = world.create_goal("g")
    world.set_goal_status(gid, "running", result="partial")
    world.set_goal_status(gid, "done")
    assert world.get_goal(gid).result == "partial"


def test_get_missing_goal_returns_none(world):
    assert world.get_goal(999_999_999) is None


def test_episode_round_trip(world):
    # No episode-read method on the PG backend yet; the assertion is that the
    # insert + update commit without raising (and return a real id).
    gid = world.create_goal("episodic")
    eid = world.start_episode(gid)
    assert isinstance(eid, int)
    world.end_episode(
        eid, "did the thing", "success",
        cost_dollars=0.02, input_tokens=10, output_tokens=5, tool_calls=2,
    )


def test_events_round_trip(world):
    gid = world.create_goal("eventful")
    e1 = world.append_event(gid, "orch", "note", "hello")
    e2 = world.append_event(gid, "coder", "tool", "ran ls")
    assert e1 < e2

    events = world.goal_events(gid)
    assert [e.content for e in events] == ["hello", "ran ls"]  # id ASC

    # since_id filter excludes events at/below the cursor.
    after = world.goal_events(gid, since_id=e1)
    assert [e.content for e in after] == ["ran ls"]


def test_facts_upsert_overwrites(world):
    world.upsert_fact("pg:color", "blue")
    world.upsert_fact("pg:color", "green")  # ON CONFLICT(key) -> update
    assert world.get_facts().get("pg:color") == "green"


def test_facts_matching_is_prefix_scoped(world):
    world.upsert_fact("user:alice:email", "a@x.com")
    world.upsert_fact("user:alice:phone", "555")
    world.upsert_fact("user:bob:email", "b@x.com")
    world.upsert_fact("global:tz", "UTC")  # not user-scoped

    assert set(world.facts_matching("alice")) == {"user:alice:email", "user:alice:phone"}
    assert world.facts_matching("") == {}  # empty token matches nothing


def test_delete_facts_matching_scoped(world):
    world.upsert_fact("user:carol:email", "c@x.com")
    world.upsert_fact("user:carol:ssn", "secret")
    world.upsert_fact("user:dave:email", "d@x.com")

    deleted = world.delete_facts_matching("carol")
    assert deleted == ["user:carol:email", "user:carol:ssn"]  # sorted keys
    remaining = world.get_facts()
    assert "user:carol:email" not in remaining
    assert remaining.get("user:dave:email") == "d@x.com"  # other users untouched


# ---------- #469: method-parity batch 1 (goal/episode/spend accessors) ----------

def test_active_goal_returns_latest_active(world):
    a = world.create_goal("first")
    b = world.create_goal("second")
    # Neither is active yet (both 'pending') -> active_goal sees status active/blocked.
    world.set_goal_status(a, "active")
    world.set_goal_status(b, "active")
    got = world.active_goal()
    assert got is not None and got.id == b  # most-recently-touched
    world.set_goal_status(b, "done")
    assert world.active_goal().id == a  # b resolved -> a is the active one


def test_active_goal_none_when_no_active(world):
    g = world.create_goal("solo")
    world.set_goal_status(g, "done")
    # Only a done goal exists for this id; active_goal scans the whole table,
    # so just assert it never returns a 'done' goal as active.
    got = world.active_goal()
    assert got is None or got.status in ("active", "blocked")


def test_list_goals_filter_and_order(world):
    world.create_goal("g1")
    g2 = world.create_goal("g2")
    world.set_goal_status(g2, "done")
    done = world.list_goals(status="done")
    assert any(x.id == g2 for x in done)
    assert all(x.status == "done" for x in done)
    # desc order returns higher ids first.
    desc = world.list_goals(order="desc", limit=2)
    assert [x.id for x in desc] == sorted([x.id for x in desc], reverse=True)
    # limit/offset are honored (no crash, bounded length).
    assert len(world.list_goals(limit=1)) == 1


def test_list_episodes_and_total_spend(world):
    g = world.create_goal("spendy")
    e1 = world.start_episode(g)
    world.end_episode(e1, "s1", "success", cost_dollars=0.10,
                      input_tokens=100, output_tokens=50, tool_calls=2)
    e2 = world.start_episode(g)
    world.end_episode(e2, "s2", "success", cost_dollars=0.25,
                      input_tokens=200, output_tokens=80, tool_calls=3)

    eps = world.list_episodes(goal_id=g)
    assert {e.id for e in eps} >= {e1, e2}
    # DESC by started_at -> most recent first.
    assert eps[0].id == e2

    spend = world.total_spend()
    # At least our two episodes are summed (other tests may add more).
    assert spend["dollars"] >= 0.35 - 1e-9
    assert spend["runs"] >= 2


def test_reclaim_orphan_goals(world):
    g = world.create_goal("orphan")
    world.set_goal_status(g, "active")
    # max_age_seconds=0 -> the just-touched active goal qualifies as stale.
    n = world.reclaim_orphan_goals(max_age_seconds=0)
    assert n >= 1
    assert world.get_goal(g).status == "blocked"


def test_reclaim_skips_fresh_goals(world):
    g = world.create_goal("fresh")
    world.set_goal_status(g, "active")
    # A 1-hour staleness window must NOT reclaim a goal touched just now.
    world.reclaim_orphan_goals(max_age_seconds=3600)
    assert world.get_goal(g).status == "active"


def test_schema_version_is_int(world):
    assert isinstance(world.schema_version, int)
    assert world.schema_version >= 1
