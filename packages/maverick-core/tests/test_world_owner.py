"""Per-goal ownership (schema v11) -- the foundation for multi-user dashboard
authz. The world model stores + filters by an owner principal; the access
*policy* (owner match / admin / legacy) lives in the dashboard layer.
"""
from __future__ import annotations

import sqlite3

from maverick.world_model import SCHEMA_VERSION, WorldModel


def test_schema_version_is_current(tmp_path):
    assert SCHEMA_VERSION == 14  # bump when adding a migration
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
