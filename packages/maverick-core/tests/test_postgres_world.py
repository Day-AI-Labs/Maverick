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


# ---------- #469: reclaim_orphan_goals + schema_version ----------

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


# ---------- #469: conversations / turns (multi-turn channel memory) ----------

def test_get_or_create_conversation_is_idempotent(world):
    c1 = world.get_or_create_conversation("telegram", "u123")
    c2 = world.get_or_create_conversation("telegram", "u123")
    assert c1.id == c2.id  # same (channel, user_id) -> same row
    assert c1.channel == "telegram" and c1.user_id == "u123"
    # A different user is a distinct conversation.
    c3 = world.get_or_create_conversation("telegram", "other")
    assert c3.id != c1.id


def test_append_and_recent_turns_chronological(world):
    conv = world.get_or_create_conversation("discord", "alice")
    world.append_turn(conv.id, "user", "hello")
    world.append_turn(conv.id, "assistant", "hi there")
    world.append_turn(conv.id, "user", "how are you")
    turns = world.recent_turns(conv.id, limit=20)
    # Ascending (chronological) order, ready for a chat prompt.
    assert [t.content for t in turns] == ["hello", "hi there", "how are you"]
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    # limit returns the most-recent N, still ascending.
    last2 = world.recent_turns(conv.id, limit=2)
    assert [t.content for t in last2] == ["hi there", "how are you"]


def test_append_turn_rejects_bad_role(world):
    conv = world.get_or_create_conversation("slack", "bob")
    with pytest.raises(ValueError):
        world.append_turn(conv.id, "system", "nope")


def test_list_conversations_filter_by_channel(world):
    world.get_or_create_conversation("matrix", "x")
    world.get_or_create_conversation("matrix", "y")
    world.get_or_create_conversation("signal", "z")
    matrix = world.list_conversations(channel="matrix")
    assert {c.user_id for c in matrix} >= {"x", "y"}
    assert all(c.channel == "matrix" for c in matrix)
    # Unfiltered returns at least everything we created.
    assert len(world.list_conversations()) >= 3


def test_prune_conversations_removes_idle_and_their_turns(world):
    conv = world.get_or_create_conversation("email", "prune-me")
    world.append_turn(conv.id, "user", "old message")
    # idle_for_seconds=0 -> the just-touched conversation counts as idle.
    removed = world.prune_conversations(idle_for_seconds=0)
    assert removed >= 1
    # Its turns are gone too (no orphans).
    assert world.recent_turns(conv.id) == []
    assert not any(c.id == conv.id for c in world.list_conversations())


def test_prune_conversations_keeps_fresh(world):
    conv = world.get_or_create_conversation("email", "keep-me")
    world.prune_conversations(idle_for_seconds=3600)  # 1h window
    assert any(c.id == conv.id for c in world.list_conversations())


# ----- messages / dedup / attachments (the #469 parity gap) -----

def test_messages_append_and_search(world):
    gid = world.create_goal("msg-search")
    world.append_message(gid, "user", "find the zphyrx marker please")
    world.append_message(gid, "assistant", "unrelated chatter")
    hits = world.search_messages("zphyrx")
    assert any("zphyrx" in h["content"] for h in hits)
    assert all(set(h) >= {"id", "goal_id", "role", "content", "ts"} for h in hits)
    assert world.search_messages("   ") == []  # blank query -> no rows


def test_processed_message_dedup_roundtrip(world):
    gid = world.create_goal("dedup")
    ext = "sid-roundtrip-1"
    assert world.mark_message_processed("sms", ext, goal_id=gid) is True   # first write
    assert world.mark_message_processed("sms", ext, goal_id=gid) is False  # duplicate
    assert world.is_processed_message("sms", ext) is True
    assert world.lookup_processed_message("sms", ext) == gid
    assert world.is_processed_message("sms", "never-seen") is False
    assert world.lookup_processed_message("sms", "never-seen") is None


def test_processed_message_null_goal_id_is_zero_not_none(world):
    ext = "sid-nullgoal-1"
    world.mark_message_processed("sms", ext)  # no goal_id
    # None means "no row"; 0 means "row exists, null goal_id" (parity w/ SQLite).
    assert world.lookup_processed_message("sms", ext) == 0


def test_prune_processed_messages_removes_old(world):
    world.mark_message_processed("sms", "sid-prune-old")
    removed = world.prune_processed_messages(older_than_seconds=0)
    assert removed >= 1
    assert world.is_processed_message("sms", "sid-prune-old") is False


def test_attachments_round_trip(world):
    gid = world.create_goal("attach")
    aid = world.add_attachment(gid, "report.md", "text/markdown", 123, "deadbeef", "/tmp/report.md")
    assert isinstance(aid, int)
    atts = world.list_attachments(gid)
    assert len(atts) == 1
    a = atts[0]
    assert (a.filename, a.mime, a.size_bytes, a.sha256, a.path) == (
        "report.md", "text/markdown", 123, "deadbeef", "/tmp/report.md",
    )
