"""Persistent world model. SQLite with FTS5 + per-connection WAL.

v0.1.6 reliability hardening:
  - PRAGMA journal_mode=WAL so the agent process (writer) and dashboard
    process (reader) don't deadlock on each other.
  - PRAGMA busy_timeout=5000 so concurrent commits retry briefly
    instead of raising OperationalError.
  - check_same_thread=False so FastAPI's threadpool can share the connection.
  - Indexes on goals(status) and goals(updated_at) for the dashboard's
    `list goals by status` and `active_goal()` queries.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_DB = Path.home() / ".maverick" / "world.db"
SCHEMA_VERSION = 3


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS goals (
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

CREATE INDEX IF NOT EXISTS idx_goals_status     ON goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_updated_at ON goals(updated_at);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    started_at REAL NOT NULL,
    ended_at REAL,
    summary TEXT,
    outcome TEXT,
    cost_dollars REAL DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_episode_id INTEGER REFERENCES episodes(id),
    updated_at REAL NOT NULL,
    UNIQUE(key)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    question TEXT NOT NULL,
    asked_at REAL NOT NULL,
    answer TEXT,
    answered_at REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goal_events_goal_id_id ON goal_events(goal_id, id);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE episodes ADD COLUMN cost_dollars REAL DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN output_tokens INTEGER DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN tool_calls INTEGER DEFAULT 0",
    ],
    3: [],  # goal_events table is in SCHEMA (idempotent CREATE)
}


@dataclass
class Goal:
    id: int
    parent_id: Optional[int]
    title: str
    description: Optional[str]
    status: str
    created_at: float
    updated_at: float
    deadline: Optional[float]
    result: Optional[str]


@dataclass
class Question:
    id: int
    goal_id: Optional[int]
    question: str
    asked_at: float
    answer: Optional[str]
    answered_at: Optional[float]


@dataclass
class EpisodeSpend:
    id: int
    goal_id: int
    started_at: float
    ended_at: Optional[float]
    outcome: Optional[str]
    cost_dollars: float
    input_tokens: int
    output_tokens: int
    tool_calls: int


@dataclass
class GoalEvent:
    id: int
    goal_id: int
    agent: str
    kind: str
    content: str
    ts: float


class WorldModel:
    def __init__(self, path: Path = DEFAULT_DB):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so FastAPI threadpool can share. Combined
        # with WAL + busy_timeout this is safe for the agent+dashboard
        # concurrency pattern (one writer process + many readers).
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        # WAL must be set before any other operation that creates pages.
        # synchronous=NORMAL under WAL is safe + much faster than FULL.
        # busy_timeout returns SQLITE_BUSY only after 5s of contention.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(SCHEMA)
        self._init_schema_version()
        self._apply_migrations()
        self.conn.commit()

    def _init_schema_version(self) -> None:
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,)
            )

    def _apply_migrations(self) -> None:
        current = self.conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()[0]
        while current < SCHEMA_VERSION:
            next_version = current + 1
            for stmt in MIGRATIONS.get(next_version, []):
                try:
                    self.conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            self.conn.execute("UPDATE schema_version SET version = ?", (next_version,))
            current = next_version

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0

    # ----- goals -----
    def create_goal(self, title: str, description: str = "", parent_id: Optional[int] = None) -> int:
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO goals(parent_id, title, description, status, created_at, updated_at) "
            "VALUES(?, ?, ?, 'pending', ?, ?)",
            (parent_id, title, description, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_goal_status(self, goal_id: int, status: str, result: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE goals SET status = ?, updated_at = ?, result = COALESCE(?, result) WHERE id = ?",
            (status, time.time(), result, goal_id),
        )
        self.conn.commit()

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        row = self.conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return Goal(**dict(row)) if row else None

    def list_goals(self, status: Optional[str] = None) -> list[Goal]:
        if status:
            rows = self.conn.execute("SELECT * FROM goals WHERE status = ? ORDER BY id", (status,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
        return [Goal(**dict(r)) for r in rows]

    def active_goal(self) -> Optional[Goal]:
        row = self.conn.execute(
            "SELECT * FROM goals WHERE status IN ('active', 'blocked') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return Goal(**dict(row)) if row else None

    # ----- episodes -----
    def start_episode(self, goal_id: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO episodes(goal_id, started_at) VALUES(?, ?)", (goal_id, time.time())
        )
        self.conn.commit()
        return cur.lastrowid

    def end_episode(
        self,
        episode_id: int,
        summary: str,
        outcome: str,
        cost_dollars: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: int = 0,
    ) -> None:
        self.conn.execute(
            "UPDATE episodes SET ended_at = ?, summary = ?, outcome = ?, "
            "cost_dollars = ?, input_tokens = ?, output_tokens = ?, tool_calls = ? "
            "WHERE id = ?",
            (time.time(), summary, outcome, cost_dollars,
             input_tokens, output_tokens, tool_calls, episode_id),
        )
        self.conn.commit()

    def list_episodes(self, limit: int = 50) -> list[EpisodeSpend]:
        rows = self.conn.execute(
            "SELECT id, goal_id, started_at, ended_at, outcome, "
            "COALESCE(cost_dollars, 0) AS cost_dollars, "
            "COALESCE(input_tokens, 0) AS input_tokens, "
            "COALESCE(output_tokens, 0) AS output_tokens, "
            "COALESCE(tool_calls, 0) AS tool_calls "
            "FROM episodes ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [EpisodeSpend(**dict(r)) for r in rows]

    def total_spend(self) -> dict[str, float]:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_dollars), 0) AS dollars, "
            "COALESCE(SUM(input_tokens), 0) AS in_tok, "
            "COALESCE(SUM(output_tokens), 0) AS out_tok, "
            "COUNT(*) AS runs FROM episodes WHERE ended_at IS NOT NULL"
        ).fetchone()
        return {
            "dollars": row["dollars"],
            "input_tokens": row["in_tok"],
            "output_tokens": row["out_tok"],
            "runs": row["runs"],
        }

    # ----- goal events -----
    def append_event(self, goal_id: int, agent: str, kind: str, content: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO goal_events(goal_id, agent, kind, content, ts) VALUES(?, ?, ?, ?, ?)",
            (goal_id, agent, kind, content, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def goal_events(self, goal_id: int, since_id: int = 0, limit: int = 200) -> list[GoalEvent]:
        rows = self.conn.execute(
            "SELECT id, goal_id, agent, kind, content, ts FROM goal_events "
            "WHERE goal_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (goal_id, since_id, limit),
        ).fetchall()
        return [GoalEvent(**dict(r)) for r in rows]

    def prune_goal_events(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        """Delete goal_events rows older than N seconds. Returns rows removed."""
        cutoff = time.time() - older_than_seconds
        cur = self.conn.execute("DELETE FROM goal_events WHERE ts < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    # ----- facts -----
    def upsert_fact(self, key: str, value: str, episode_id: Optional[int] = None) -> None:
        self.conn.execute(
            "INSERT INTO facts(key, value, source_episode_id, updated_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, episode_id, time.time()),
        )
        self.conn.commit()

    def get_facts(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ----- questions -----
    def ask(self, question: str, goal_id: Optional[int] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO questions(goal_id, question, asked_at) VALUES(?, ?, ?)",
            (goal_id, question, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def answer(self, question_id: int, answer: str) -> None:
        self.conn.execute(
            "UPDATE questions SET answer = ?, answered_at = ? WHERE id = ?",
            (answer, time.time(), question_id),
        )
        self.conn.commit()

    def open_questions(self, goal_id: Optional[int] = None) -> list[Question]:
        if goal_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM questions WHERE answer IS NULL AND goal_id = ? ORDER BY id", (goal_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM questions WHERE answer IS NULL ORDER BY id"
            ).fetchall()
        return [Question(**dict(r)) for r in rows]

    def all_questions(self, goal_id: int) -> list[Question]:
        rows = self.conn.execute(
            "SELECT * FROM questions WHERE goal_id = ? ORDER BY id", (goal_id,)
        ).fetchall()
        return [Question(**dict(r)) for r in rows]

    # ----- messages -----
    def append_message(self, goal_id: int, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages(goal_id, role, content, ts) VALUES(?, ?, ?, ?)",
            (goal_id, role, content, time.time()),
        )
        self.conn.commit()

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT m.* FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
            "WHERE messages_fts MATCH ? ORDER BY m.ts DESC LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
