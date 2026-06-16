"""Per-goal ownership (schema v11) -- the foundation for multi-user dashboard
authz. The world model stores + filters by an owner principal; the access
*policy* (owner match / admin / legacy) lives in the dashboard layer.
"""
from __future__ import annotations

import sqlite3

from maverick.world_model import SCHEMA_VERSION, WorldModel


def test_schema_version_is_current(tmp_path):
    assert SCHEMA_VERSION == 16  # bump when adding a migration
    assert WorldModel(tmp_path / "w.db").schema_version == SCHEMA_VERSION


def test_create_goal_stores_owner(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("t", owner="user:alice")
    assert w.get_goal(gid).owner == "user:alice"


def test_goal_domain_roundtrip(tmp_path):
    # v14: department attribution. Unset stays '', set persists, and
    # set_goal_domain records the department a run executed as.
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("t")
    assert w.get_goal(gid).domain == ""
    gid2 = w.create_goal("t2", domain="finance_sox")
    assert w.get_goal(gid2).domain == "finance_sox"
    w.set_goal_domain(gid, "gtm_sales_eng")
    assert w.get_goal(gid).domain == "gtm_sales_eng"


def test_default_owner_is_empty(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    assert w.get_goal(w.create_goal("t")).owner == ""


def test_list_goals_owner_filter(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    a = w.create_goal("a", owner="user:alice")
    b = w.create_goal("b", owner="user:bob")
    u = w.create_goal("u")  # legacy / unowned
    assert {g.id for g in w.list_goals(owner="user:alice")} == {a}
    assert {g.id for g in w.list_goals(owner="")} == {u}        # unowned only
    assert {g.id for g in w.list_goals()} == {a, b, u}          # None = all
    # owner + status compose
    w.set_goal_status(a, "done")
    assert {g.id for g in w.list_goals(status="done", owner="user:alice")} == {a}
    assert w.list_goals(status="done", owner="user:bob") == []


def test_signoff_record_and_read(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("forecast", domain="finance_cash13w")
    assert w.signoff_for(gid) is None                      # unreviewed
    w.record_signoff(gid, "approved", decided_by="user:alice", note="ties out")
    s = w.signoff_for(gid)
    assert s["decision"] == "approved"
    assert s["decided_by"] == "user:alice"
    assert s["note"] == "ties out"                          # note round-trips (encrypted)


def test_signoff_latest_decision_wins(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("forecast", domain="finance_cash13w")
    w.record_signoff(gid, "rejected", decided_by="user:bob", note="rework week 3")
    w.record_signoff(gid, "approved", decided_by="user:alice")  # supersedes
    s = w.signoff_for(gid)
    assert s["decision"] == "approved" and s["decided_by"] == "user:alice"
    assert s["note"] is None                                # the new decision's (empty) note


def test_signoffs_for_goals_batch(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    a = w.create_goal("a", domain="finance_cash13w")
    b = w.create_goal("b", domain="finance_cash13w")
    c = w.create_goal("c", domain="finance_cash13w")  # unreviewed
    w.record_signoff(a, "approved")
    w.record_signoff(b, "rejected")
    assert w.signoffs_for_goals([a, b, c]) == {a: "approved", b: "rejected"}
    assert w.signoffs_for_goals([]) == {}


def test_list_goals_domain_filter(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    f1 = w.create_goal("forecast", domain="finance_cash13w")
    f2 = w.create_goal("forecast 2", domain="finance_cash13w")
    other = w.create_goal("other", domain="bank_cecl_allowance")
    generic = w.create_goal("generic")  # no domain
    assert {g.id for g in w.list_goals(domain="finance_cash13w")} == {f1, f2}
    assert {g.id for g in w.list_goals(domain="bank_cecl_allowance")} == {other}
    assert {g.id for g in w.list_goals(domain="")} == {generic}  # unattributed only
    # domain + owner compose
    w.set_goal_domain(f1, "finance_cash13w")  # idempotent; keep attribution
    assert {g.id for g in w.list_goals(domain="finance_cash13w", limit=1, order="desc")} == {f2}


def test_migration_adds_owner_to_a_v10_db(tmp_path):
    # A real pre-owner (v10) DB: goals table without `owner`, version pinned 10.
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER,
            title TEXT NOT NULL, description TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            deadline REAL, result TEXT);
        CREATE TABLE schema_version(version INTEGER);
        INSERT INTO schema_version(version) VALUES(10);
        INSERT INTO goals(title, status, created_at, updated_at)
            VALUES('legacy', 'done', 0, 0);
        """
    )
    conn.commit()
    conn.close()

    w = WorldModel(db)  # opening runs the v11 (owner) migration and any later
    assert w.schema_version == SCHEMA_VERSION
    legacy = w.get_goal(1)
    assert legacy is not None and legacy.owner == ""   # migrated default
    gid = w.create_goal("new", owner="user:x")
    assert w.get_goal(gid).owner == "user:x"
