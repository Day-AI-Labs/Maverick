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


def test_list_goals_filter_and_order(world):
    g1 = world.create_goal("first")
    g2 = world.create_goal("second")
    world.set_goal_status(g2, "done")

    done = world.list_goals(status="done")
    assert any(x.id == g2 for x in done)
    assert all(x.status == "done" for x in done)  # filter applied

    desc = world.list_goals(order="desc", limit=100)
    ids = [x.id for x in desc]
    assert ids.index(g2) < ids.index(g1)  # later id first in DESC order


def test_active_goal(world):
    gid = world.create_goal("to-activate")
    world.set_goal_status(gid, "active")
    a = world.active_goal()
    assert a is not None
    assert a.status in ("active", "blocked")


def test_list_episodes_and_total_spend(world):
    gid = world.create_goal("spendy")
    eid = world.start_episode(gid)
    world.end_episode(
        eid, "s", "success",
        cost_dollars=1.5, input_tokens=100, output_tokens=50, tool_calls=3,
    )
    eps = world.list_episodes(goal_id=gid)
    assert any(x.id == eid and x.cost_dollars == 1.5 for x in eps)

    totals = world.total_spend()
    assert totals["dollars"] >= 1.5   # this run's ended episode counts
    assert totals["runs"] >= 1


def test_ask_answer_open_questions(world):
    gid = world.create_goal("needs input")
    qid = world.ask("which region?", goal_id=gid)
    assert isinstance(qid, int)

    # open before answering
    opens = world.open_questions(goal_id=gid)
    assert [q.id for q in opens] == [qid]
    assert opens[0].question == "which region?"
    assert opens[0].answer is None

    assert world.answer(qid, "us-east-1") is True
    # answering removes it from the open set
    assert all(q.id != qid for q in world.open_questions(goal_id=gid))

    # all_questions still shows it, now answered
    allq = world.all_questions(gid)
    answered = [q for q in allq if q.id == qid][0]
    assert answered.answer == "us-east-1"
    assert answered.answered_at is not None


def test_answer_unknown_question_id_returns_false(world):
    # #394 parity: a typo'd id is reported, not a false success.
    assert world.answer(987_654_321, "nope") is False


def test_approval_queue_lifecycle(world):
    aid = world.create_approval("rm -rf /tmp/x", risk="high", scope="shell", detail="cleanup")
    assert isinstance(aid, int)

    a = world.get_approval(aid)
    assert a is not None
    assert a.action == "rm -rf /tmp/x"
    assert a.risk == "high"
    assert a.status == "pending"
    assert a.decided_at is None

    assert any(x.id == aid for x in world.pending_approvals())

    assert world.decide_approval(aid, "approved") is True
    decided = world.get_approval(aid)
    assert decided.status == "approved"
    assert decided.decided_at is not None
    assert all(x.id != aid for x in world.pending_approvals())  # left the queue

    # a second decision on an already-decided row is a no-op
    assert world.decide_approval(aid, "denied") is False


def test_decide_approval_rejects_bad_status(world):
    aid = world.create_approval("do thing")
    with pytest.raises(ValueError, match="approved.*denied"):
        world.decide_approval(aid, "maybe")


def test_attachments_round_trip(world):
    gid = world.create_goal("with files")
    a1 = world.add_attachment(gid, "a.txt", "text/plain", 12, "deadbeef", "/tmp/a.txt")
    a2 = world.add_attachment(gid, "b.png", "image/png", 2048, "cafe", "/tmp/b.png")
    assert a1 < a2

    rows = world.list_attachments(gid)
    assert [r.filename for r in rows] == ["a.txt", "b.png"]   # id ASC
    b = [r for r in rows if r.filename == "b.png"][0]
    assert b.mime == "image/png"
    assert b.size_bytes == 2048
    assert b.sha256 == "cafe"
    assert b.path == "/tmp/b.png"

    # scoped to the goal: a different goal sees none of these
    other = world.create_goal("no files")
    assert world.list_attachments(other) == []


def test_messages_append_and_search(world):
    gid = world.create_goal("chat goal")
    world.append_message(gid, "user", "deploy the API to staging please")
    world.append_message(gid, "assistant", "deploying now")
    world.append_message(gid, "user", "unrelated note about cats")

    contents = [h["content"] for h in world.search_messages("deploy")]
    assert "deploy the API to staging please" in contents
    assert "deploying now" in contents
    assert "unrelated note about cats" not in contents

    assert world.search_messages("") == []          # empty query: no crash
    assert world.search_messages("   ") == []        # whitespace-only too


def test_search_messages_escapes_like_wildcards(world):
    gid = world.create_goal("g-wild")
    world.append_message(gid, "user", "100% sure")
    world.append_message(gid, "user", "totally different")
    # the '%' must be literal, not a match-all wildcard
    assert [h["content"] for h in world.search_messages("100%")] == ["100% sure"]


def test_get_or_create_conversation_idempotent(world):
    c1 = world.get_or_create_conversation("imessage", "+15551234")
    c2 = world.get_or_create_conversation("imessage", "+15551234")
    assert c1.id == c2.id                 # same (channel,user) -> same row
    assert c2.last_seen >= c1.last_seen    # last_seen bumped


def test_turns_append_and_recent_order(world):
    conv = world.get_or_create_conversation("web", "user-7")
    world.append_turn(conv.id, "user", "hi")
    world.append_turn(conv.id, "assistant", "hello")
    world.append_turn(conv.id, "user", "bye")
    # most-recent 2, returned chronologically (ascending)
    assert [t.content for t in world.recent_turns(conv.id, limit=2)] == ["hello", "bye"]


def test_append_turn_validates_role(world):
    conv = world.get_or_create_conversation("web", "user-role")
    with pytest.raises(ValueError, match="user.*assistant"):
        world.append_turn(conv.id, "system", "nope")


def test_list_conversations_channel_filter(world):
    world.get_or_create_conversation("slack", "u-a")
    world.get_or_create_conversation("discord", "u-b")
    slack = world.list_conversations(channel="slack")
    assert all(c.channel == "slack" for c in slack)
    assert any(c.user_id == "u-a" for c in slack)


def test_channel_dedup(world):
    assert world.mark_message_processed("twilio", "SID-1") is True   # first write
    assert world.mark_message_processed("twilio", "SID-1") is False  # duplicate
    assert world.is_processed_message("twilio", "SID-1") is True
    assert world.is_processed_message("twilio", "SID-unseen") is False


def test_lookup_processed_message_null_vs_missing(world):
    world.mark_message_processed("sms", "M-withgoal", goal_id=42)
    world.mark_message_processed("sms", "M-nogoal", goal_id=None)
    assert world.lookup_processed_message("sms", "M-withgoal") == 42
    assert world.lookup_processed_message("sms", "M-nogoal") == 0     # seen, null goal
    assert world.lookup_processed_message("sms", "M-never") is None   # unseen


def test_prune_methods_remove_and_count(world):
    # Run LAST: a negative horizon prunes everything (cutoff in the future).
    gid = world.create_goal("prunable")
    world.append_event(gid, "a", "k", "old event")
    world.mark_message_processed("ch", "ext-prune")
    conv = world.get_or_create_conversation("ch", "prune-user")
    world.append_turn(conv.id, "user", "x")

    assert world.prune_goal_events(older_than_seconds=-1) >= 1
    assert world.prune_processed_messages(older_than_seconds=-1) >= 1
    assert world.prune_conversations(idle_for_seconds=-1) >= 1


def test_schema_version(world):
    assert world.schema_version() == 1   # seeded by _migrate


def test_reclaim_orphan_goals(world):
    gid = world.create_goal("stuck")
    world.set_goal_status(gid, "active")
    # negative horizon -> cutoff in the future -> reclaims all active/pending
    # (no flaky equality on updated_at == cutoff)
    reclaimed = world.reclaim_orphan_goals(max_age_seconds=-1)
    assert reclaimed >= 1
    g = world.get_goal(gid)
    assert g.status == "blocked"
    assert "process restarted mid-run" in (g.result or "")
