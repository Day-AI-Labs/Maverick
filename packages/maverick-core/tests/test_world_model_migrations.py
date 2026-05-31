"""Schema migration tests: forward-only v1 -> v2 -> v3.

Council surfaced that we'd shipped migrations without tests, so a future
breaking change could silently corrupt a user's ~/.maverick/world.db.

These tests build a *legacy* schema on disk (no schema_version row, no
new columns/tables), then open a `WorldModel` against it and assert:
  - existing rows survive
  - new columns exist and default sensibly
  - new tables are created
  - schema_version lands on `SCHEMA_VERSION`

The same database is reopened a second time to assert migrations are
idempotent (no double-applies, no errors).
"""
from __future__ import annotations

import sqlite3
import time

from maverick.world_model import SCHEMA_VERSION, WorldModel

V1_SCHEMA = """
CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
INSERT INTO schema_version(version) VALUES(1);

CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES goals(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deadline REAL,
    result TEXT
);

CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    started_at REAL NOT NULL,
    ended_at REAL,
    summary TEXT,
    outcome TEXT
);

CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_episode_id INTEGER REFERENCES episodes(id),
    updated_at REAL NOT NULL,
    UNIQUE(key)
);

CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    question TEXT NOT NULL,
    asked_at REAL NOT NULL,
    answer TEXT,
    answered_at REAL
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);
"""


def _build_legacy_db(path) -> int:
    """Build a v1 DB with one goal, one episode, one fact. Returns goal id."""
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    now = time.time()
    cur = conn.execute(
        "INSERT INTO goals(title, description, status, created_at, updated_at) "
        "VALUES('legacy goal', 'pre-v2', 'done', ?, ?)",
        (now, now),
    )
    goal_id = cur.lastrowid
    conn.execute(
        "INSERT INTO episodes(goal_id, started_at, ended_at, summary, outcome) "
        "VALUES(?, ?, ?, 'old episode', 'success')",
        (goal_id, now, now),
    )
    conn.execute(
        "INSERT INTO facts(key, value, updated_at) VALUES('user_name', 'alice', ?)",
        (now,),
    )
    conn.commit()
    conn.close()
    return goal_id


def test_migrates_v1_to_current(tmp_path):
    db = tmp_path / "world.db"
    goal_id = _build_legacy_db(db)

    wm = WorldModel(path=db)

    assert wm.schema_version == SCHEMA_VERSION

    # Pre-existing rows survive.
    goal = wm.get_goal(goal_id)
    assert goal is not None
    assert goal.title == "legacy goal"
    assert goal.status == "done"

    # New episodes columns exist with sensible defaults for pre-migration rows.
    spend = wm.total_spend()
    assert spend["dollars"] == 0
    assert spend["input_tokens"] == 0
    assert spend["output_tokens"] == 0
    assert spend["runs"] == 1  # the pre-existing ended episode

    # v3 table goal_events is usable (no rows yet, append works).
    ev_id = wm.append_event(goal_id, "orchestrator", "info", "live event")
    assert ev_id > 0
    events = wm.goal_events(goal_id, since_id=0)
    assert len(events) == 1
    assert events[0].kind == "info"


def test_migrations_are_idempotent(tmp_path):
    db = tmp_path / "world.db"
    _build_legacy_db(db)

    # First open: v1 -> v3
    wm1 = WorldModel(path=db)
    assert wm1.schema_version == SCHEMA_VERSION
    wm1.conn.close()

    # Second open: already at v3, must be a no-op (no duplicate column errors).
    wm2 = WorldModel(path=db)
    assert wm2.schema_version == SCHEMA_VERSION

    # And it must still be writeable end-to-end.
    gid = wm2.create_goal("new", "post-migration")
    assert wm2.get_goal(gid).title == "new"


def test_fresh_db_lands_on_current(tmp_path):
    db = tmp_path / "fresh.db"
    wm = WorldModel(path=db)
    assert wm.schema_version == SCHEMA_VERSION

    # All the surface area works end-to-end.
    gid = wm.create_goal("first", "")
    wm.upsert_fact("k", "v")
    eid = wm.start_episode(gid)
    wm.end_episode(eid, "ok", "success", cost_dollars=0.42, input_tokens=10, output_tokens=20, tool_calls=2)
    wm.append_event(gid, "agent", "step", "running")

    assert wm.get_facts() == {"k": "v"}
    spend = wm.total_spend()
    assert spend["dollars"] == 0.42
    assert spend["runs"] == 1
    assert len(wm.goal_events(gid)) == 1


def test_prune_goal_events(tmp_path):
    db = tmp_path / "prune.db"
    wm = WorldModel(path=db)
    gid = wm.create_goal("g", "")

    # Backdate one event by 60 days; keep another recent.
    wm.append_event(gid, "a", "info", "old")
    wm.conn.execute(
        "UPDATE goal_events SET ts = ? WHERE id = (SELECT MAX(id) FROM goal_events)",
        (time.time() - 60 * 24 * 3600,),
    )
    wm.append_event(gid, "a", "info", "recent")
    wm.conn.commit()

    removed = wm.prune_goal_events(older_than_seconds=30 * 24 * 3600)
    assert removed == 1
    assert len(wm.goal_events(gid)) == 1
    assert wm.goal_events(gid)[0].content == "recent"
