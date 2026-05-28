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

import contextlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional


DEFAULT_DB = Path.home() / ".maverick" / "world.db"
SCHEMA_VERSION = 8


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

CREATE INDEX IF NOT EXISTS idx_episodes_ended_at ON episodes(ended_at);

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
CREATE INDEX IF NOT EXISTS idx_goal_events_ts          ON goal_events(ts);

-- v0.2 multi-turn: per-channel-user conversation threads.
-- (channel, user_id) is the natural key so the same iMessage user
-- across separate Maverick goals lands in a single conversation.
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL,
    UNIQUE(channel, user_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_last_seen ON conversations(last_seen);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    goal_id INTEGER REFERENCES goals(id),
    role TEXT NOT NULL,     -- 'user' | 'assistant'
    content TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_conv_id ON turns(conversation_id, id);

-- v0.2 attachments: files/images uploaded with a goal.
-- The actual bytes live on disk under ~/.maverick/attachments/<goal>/<sha>;
-- this row records the metadata and lets the agent enumerate them.
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attachments_goal_id ON attachments(goal_id);

-- v0.2 channel idempotency: Twilio / iMessage / other channels retry
-- webhooks on non-2xx (or slow handlers). Without a dedup key the same
-- inbound message triggers N goal runs and N API spends.
CREATE TABLE IF NOT EXISTS processed_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    external_id TEXT NOT NULL,
    goal_id INTEGER REFERENCES goals(id),
    seen_at REAL NOT NULL,
    UNIQUE(channel, external_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

-- Q1 2026 index audit (schema v8): cover the hot queries identified
-- in docs/performance/world-model-indexes.md. These are duplicated in
-- MIGRATIONS[8] so existing databases pick them up on next open.
CREATE INDEX IF NOT EXISTS idx_episodes_goal_started
    ON episodes(goal_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_started
    ON episodes(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_goals_status_updated
    ON goals(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_goals_parent
    ON goals(parent_id, created_at);
"""


MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE episodes ADD COLUMN cost_dollars REAL DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN output_tokens INTEGER DEFAULT 0",
        "ALTER TABLE episodes ADD COLUMN tool_calls INTEGER DEFAULT 0",
    ],
    3: [],  # goal_events table is in SCHEMA (idempotent CREATE)
    4: [],  # conversations/turns tables are in SCHEMA (idempotent CREATE)
    5: [],  # attachments table is in SCHEMA (idempotent CREATE)
    6: [],  # processed_messages table is in SCHEMA (idempotent CREATE)
    # Wave 12 (council F17): episodes.ended_at + goal_events.ts indexes.
    # list_episodes() does `ORDER BY ended_at DESC LIMIT N` which is a
    # full table scan without the index — visible above ~5k episodes;
    # SWE-bench Pro creates ~7500 episodes per sweep (1865 instances ×
    # best-of-4 attempts) so the dashboard's recent-episodes query
    # was painful. prune_goal_events queries by ts < cutoff.
    7: [
        "CREATE INDEX IF NOT EXISTS idx_episodes_ended_at "
        "ON episodes(ended_at)",
        "CREATE INDEX IF NOT EXISTS idx_goal_events_ts "
        "ON goal_events(ts)",
    ],
    # Q1 2026 index audit: hot queries identified via EXPLAIN QUERY PLAN.
    #
    # - list_episodes(goal_id=...) filters by goal_id then orders by
    #   started_at: needs idx_episodes_goal_started.
    # - list_episodes() (no goal filter) orders by started_at: full
    #   table scan was OK on small DBs, painful at 100k+ episodes.
    # - monitor.snapshot resolves the active goal by status + ORDER BY
    #   updated_at DESC LIMIT 1: covers via idx_goals_status_updated.
    # - cross_goal_memory.recall scans WHERE status IN (succeeded,
    #   done, failed) ORDER BY updated_at DESC LIMIT 500: covered by
    #   idx_goals_status_updated.
    # - parent_id filter for _fetch_subgoals: needs idx_goals_parent.
    8: [
        "CREATE INDEX IF NOT EXISTS idx_episodes_goal_started "
        "ON episodes(goal_id, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_episodes_started "
        "ON episodes(started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_goals_status_updated "
        "ON goals(status, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_goals_parent "
        "ON goals(parent_id, created_at)",
    ],
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


@dataclass
class Conversation:
    id: int
    channel: str
    user_id: str
    created_at: float
    last_seen: float


@dataclass
class Turn:
    id: int
    conversation_id: int
    goal_id: Optional[int]
    role: str
    content: str
    ts: float


@dataclass
class Attachment:
    id: int
    goal_id: int
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    path: str
    created_at: float


class WorldModel:
    def __init__(self, path: Path = DEFAULT_DB):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # world.db holds all conversation content, messages, and facts.
        # The audit dir is locked to 0700/0600 but this DB inherited the
        # default umask (often world-readable 0644) — any local user or
        # backup could read everyone's data. Lock the dir + the file.
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        # check_same_thread=False so FastAPI threadpool can share. Combined
        # with WAL + busy_timeout this is safe for the agent+dashboard
        # concurrency pattern (one writer process + many readers).
        #
        # Council round-2 perf-seat fix: ``check_same_thread=False`` alone
        # is insufficient. Two threadpool workers driving execute()+commit()
        # on the same connection can interleave: thread A opens an implicit
        # transaction with INSERT, thread B's INSERT joins the same
        # transaction, A's commit() flushes both rows, B's commit() is a
        # no-op. If A had raised between execute() and commit() and called
        # rollback(), B's "successful" insert would silently roll back too.
        # The RLock + ``_writing()`` context manager serialises every
        # mutation so each commit() bounds exactly one logical write.
        self._write_lock = threading.RLock()
        self._write_depth = 0
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.conn.row_factory = sqlite3.Row
        # WAL must be set before any other operation that creates pages.
        # synchronous=NORMAL under WAL is safe + much faster than FULL.
        # busy_timeout returns SQLITE_BUSY only after 5s of contention.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        # May 26 council fix (long-tail audit #4): bound WAL file
        # growth. Default autocheckpoint=1000 pages is fine, but with
        # a dashboard reader holding a snapshot lock, autocheckpoint
        # can stall and the WAL file grows monotonically. Explicit
        # pragma surfaces the setting + makes intent clear.
        self.conn.execute("PRAGMA wal_autocheckpoint = 1000")
        # SQLite default is foreign_keys=OFF; without this, every
        # `REFERENCES goals(id)` clause is decorative and a delete can
        # orphan turns/attachments/episodes silently.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._init_schema_version()
        self._apply_migrations()
        self.conn.commit()

    @contextlib.contextmanager
    def _writing(self) -> "Iterator[sqlite3.Connection]":
        """Acquire the write lock, yield the connection, commit on clean exit.

        Use this around every INSERT/UPDATE/DELETE sequence. If the body
        raises, outermost scope rolls back so the next caller sees a
        consistent state. Re-entrant via RLock so methods that compose
        other mutators don't self-deadlock; nested scopes share one
        transaction and only the outermost scope commits/rolls back.
        """
        with self._write_lock:
            is_outermost = self._write_depth == 0
            self._write_depth += 1
            try:
                yield self.conn
                if is_outermost:
                    self.conn.commit()
            except Exception:
                if is_outermost:
                    self.conn.rollback()
                raise
            finally:
                self._write_depth -= 1

    def close(self) -> None:
        """Close the underlying SQLite connection.

        Wave 9 fix (council H1): benchmark runs construct ~1865
        WorldModel instances in one process; without close() the
        FD count climbs and the host eventually OOMs.

        May 26 council fix (long-tail audit #4): checkpoint + truncate
        the WAL on close so the sidecar file doesn't persist into the
        next instance's open. Best-effort; close still runs even if
        checkpoint fails.
        """
        try:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self.conn.close()
        except Exception:  # pragma: no cover
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reclaim_orphan_goals(self, *, max_age_seconds: float = 60.0) -> int:
        """Mark goals stuck in 'active' or 'pending' as 'blocked'.

        Called on startup to recover from SIGKILL / OOM / crash mid-run.
        Without this, a process death between create_goal() and
        set_goal_status('done'/'blocked') leaves the row 'active' forever
        and `active_goal()` returns a ghost.

        Council security/integrity finding: previous default was 0,
        which reclaimed every active row -- including goals running in
        a sibling process (dashboard restarting while `maverick serve`
        is mid-goal would flip the live goal to 'blocked'). Default now
        is 60 seconds: only reclaim goals whose `updated_at` is at
        least a minute stale. Live goals re-touch updated_at via
        set_goal_status('active') and via the runner's status writes,
        so any goal currently being driven won't qualify. Multi-process
        deployments with very slow turns can raise this via
        ``MAVERICK_ORPHAN_RECLAIM_SECONDS``.

        Returns rows reclaimed.
        """
        import os as _os
        env_override = _os.environ.get("MAVERICK_ORPHAN_RECLAIM_SECONDS")
        if env_override is not None:
            try:
                max_age_seconds = max(0.0, float(env_override))
            except ValueError:
                pass
        cutoff = time.time() - max_age_seconds
        with self._writing() as conn:
            cur = conn.execute(
                "UPDATE goals SET status = 'blocked', "
                "result = COALESCE(result, '') || ' [process restarted mid-run]', "
                "updated_at = ? "
                "WHERE status IN ('active', 'pending') AND updated_at < ?",
                (time.time(), cutoff),
            )
            return cur.rowcount

    def _init_schema_version(self) -> None:
        # Council finding: two processes opening a brand-new world.db
        # concurrently both saw 'no row' and both INSERTed with the same
        # PRIMARY KEY, crashing one of them on IntegrityError. We now
        # check-then-insert and swallow the IntegrityError if a
        # concurrent process won the race. (Don't use INSERT OR IGNORE
        # with a hardcoded VALUES(6) on an existing v1 DB -- it would
        # create a second row at version=6 alongside the existing v1.)
        import sqlite3 as _sqlite3
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            try:
                self.conn.execute(
                    "INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,)
                )
            except _sqlite3.IntegrityError:
                # Another process beat us to it; their row is fine.
                pass

    def _apply_migrations(self) -> None:
        current = self.conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()[0]
        # Wave 12 hardening: temporarily bump busy_timeout for the
        # migration. CREATE INDEX on a multi-million-row table
        # (long-lived production DB) can take 30s+ and the 5s default
        # would raise "database is locked" against a running dashboard.
        # Restore after, even on exception.
        prior = None
        try:
            prior = self.conn.execute(
                "PRAGMA busy_timeout"
            ).fetchone()[0]
            self.conn.execute("PRAGMA busy_timeout = 60000")
        except sqlite3.Error:
            prior = None
        try:
            while current < SCHEMA_VERSION:
                next_version = current + 1
                for stmt in MIGRATIONS.get(next_version, []):
                    try:
                        self.conn.execute(stmt)
                    except sqlite3.OperationalError as e:
                        msg = str(e).lower()
                        if "duplicate column" not in msg:
                            raise
                self.conn.execute(
                    "UPDATE schema_version SET version = ?", (next_version,),
                )
                current = next_version
        finally:
            if prior is not None:
                try:
                    self.conn.execute(
                        f"PRAGMA busy_timeout = {int(prior)}",
                    )
                except sqlite3.Error:
                    pass

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0

    # ----- goals -----
    def create_goal(self, title: str, description: str = "", parent_id: Optional[int] = None) -> int:
        now = time.time()
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO goals(parent_id, title, description, status, created_at, updated_at) "
                "VALUES(?, ?, ?, 'pending', ?, ?)",
                (parent_id, title, description, now, now),
            )
            return cur.lastrowid

    def set_goal_status(self, goal_id: int, status: str, result: Optional[str] = None) -> None:
        with self._writing() as conn:
            conn.execute(
                "UPDATE goals SET status = ?, updated_at = ?, result = COALESCE(?, result) WHERE id = ?",
                (status, time.time(), result, goal_id),
            )

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        row = self.conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return Goal(**dict(row)) if row else None

    def list_goals(
        self,
        status: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[Goal]:
        """List goals, optionally filtered + paginated.

        Defaults preserve historical behaviour (``limit=None`` returns
        all rows in ASC id order). Dashboard callers should pass a
        small ``limit`` to avoid loading every goal on every request;
        ``order='desc'`` lets the most-recent slice be fetched cheaply.
        """
        direction = "DESC" if order.lower() == "desc" else "ASC"
        sql = "SELECT * FROM goals"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += f" ORDER BY id {direction}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + (max(1, int(limit)), max(0, int(offset)))
        rows = self.conn.execute(sql, params).fetchall()
        return [Goal(**dict(r)) for r in rows]

    def active_goal(self) -> Optional[Goal]:
        row = self.conn.execute(
            "SELECT * FROM goals WHERE status IN ('active', 'blocked') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return Goal(**dict(row)) if row else None

    # ----- episodes -----
    def start_episode(self, goal_id: int) -> int:
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO episodes(goal_id, started_at) VALUES(?, ?)",
                (goal_id, time.time()),
            )
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
        with self._writing() as conn:
            conn.execute(
                "UPDATE episodes SET ended_at = ?, summary = ?, outcome = ?, "
                "cost_dollars = ?, input_tokens = ?, output_tokens = ?, tool_calls = ? "
                "WHERE id = ?",
                (time.time(), summary, outcome, cost_dollars,
                 input_tokens, output_tokens, tool_calls, episode_id),
            )

    def list_episodes(
        self,
        limit: int = 50,
        goal_id: Optional[int] = None,
    ) -> list[EpisodeSpend]:
        if goal_id is not None:
            rows = self.conn.execute(
                "SELECT id, goal_id, started_at, ended_at, outcome, "
                "COALESCE(cost_dollars, 0) AS cost_dollars, "
                "COALESCE(input_tokens, 0) AS input_tokens, "
                "COALESCE(output_tokens, 0) AS output_tokens, "
                "COALESCE(tool_calls, 0) AS tool_calls "
                "FROM episodes WHERE goal_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (goal_id, limit),
            ).fetchall()
        else:
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
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO goal_events(goal_id, agent, kind, content, ts) VALUES(?, ?, ?, ?, ?)",
                (goal_id, agent, kind, content, time.time()),
            )
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
        with self._writing() as conn:
            cur = conn.execute("DELETE FROM goal_events WHERE ts < ?", (cutoff,))
            return cur.rowcount

    # ----- facts -----
    def upsert_fact(self, key: str, value: str, episode_id: Optional[int] = None) -> None:
        with self._writing() as conn:
            conn.execute(
                "INSERT INTO facts(key, value, source_episode_id, updated_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, episode_id, time.time()),
            )

    def get_facts(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ----- questions -----
    def ask(self, question: str, goal_id: Optional[int] = None) -> int:
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO questions(goal_id, question, asked_at) VALUES(?, ?, ?)",
                (goal_id, question, time.time()),
            )
            return cur.lastrowid

    def answer(self, question_id: int, answer: str) -> None:
        with self._writing() as conn:
            conn.execute(
                "UPDATE questions SET answer = ?, answered_at = ? WHERE id = ?",
                (answer, time.time(), question_id),
            )

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
        with self._writing() as conn:
            conn.execute(
                "INSERT INTO messages(goal_id, role, content, ts) VALUES(?, ?, ?, ?)",
                (goal_id, role, content, time.time()),
            )

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT m.* FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
            "WHERE messages_fts MATCH ? ORDER BY m.ts DESC LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----- conversations (multi-turn per channel user) -----
    def get_or_create_conversation(self, channel: str, user_id: str) -> Conversation:
        """Idempotent: same (channel, user_id) always returns the same row.
        last_seen is bumped on every call so prune_conversations can
        retire ones the user has stopped talking to."""
        now = time.time()
        with self._writing() as conn:
            conn.execute(
                "INSERT INTO conversations(channel, user_id, created_at, last_seen) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(channel, user_id) DO UPDATE SET last_seen = excluded.last_seen",
                (channel, user_id, now, now),
            )
            row = conn.execute(
                "SELECT * FROM conversations WHERE channel = ? AND user_id = ?",
                (channel, user_id),
            ).fetchone()
        return Conversation(**dict(row))

    def append_turn(
        self,
        conversation_id: int,
        role: str,
        content: str,
        goal_id: Optional[int] = None,
    ) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO turns(conversation_id, goal_id, role, content, ts) "
                "VALUES(?, ?, ?, ?, ?)",
                (conversation_id, goal_id, role, content, time.time()),
            )
            return cur.lastrowid

    def recent_turns(self, conversation_id: int, limit: int = 20) -> list[Turn]:
        """Return the most recent N turns in chronological (ascending) order
        so they can be fed straight into a chat-format prompt."""
        rows = self.conn.execute(
            "SELECT id, conversation_id, goal_id, role, content, ts FROM turns "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return list(reversed([Turn(**dict(r)) for r in rows]))

    def list_conversations(self, channel: Optional[str] = None) -> list[Conversation]:
        if channel:
            rows = self.conn.execute(
                "SELECT * FROM conversations WHERE channel = ? ORDER BY last_seen DESC",
                (channel,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM conversations ORDER BY last_seen DESC"
            ).fetchall()
        return [Conversation(**dict(r)) for r in rows]

    # ----- channel dedup -----
    def mark_message_processed(
        self,
        channel: str,
        external_id: str,
        goal_id: Optional[int] = None,
    ) -> bool:
        """Record an inbound message as processed; idempotent.

        Returns True on first-write (the caller should run the goal),
        False on duplicate (the caller should return 200 without
        re-running). Twilio retries within 15s if the webhook is slow
        or non-2xx; the same MessageSid arriving twice was producing
        N goals and N spends before this.
        """
        try:
            with self._writing() as conn:
                conn.execute(
                    "INSERT INTO processed_messages(channel, external_id, goal_id, seen_at) "
                    "VALUES(?, ?, ?, ?)",
                    (channel, external_id, goal_id, time.time()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def lookup_processed_message(
        self,
        channel: str,
        external_id: str,
    ) -> Optional[int]:
        """Return the goal_id for an already-processed message, if any.

        Distinguishes 'no row' (returns None) from 'row exists but goal_id
        is null' (returns 0). Callers that just need "have we seen this?"
        should use ``is_processed_message`` to avoid that ambiguity.
        """
        row = self.conn.execute(
            "SELECT goal_id FROM processed_messages "
            "WHERE channel = ? AND external_id = ?",
            (channel, external_id),
        ).fetchone()
        if row is None:
            return None
        return row[0] if row[0] is not None else 0

    def prune_processed_messages(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        """Delete dedup rows older than N seconds.

        Twilio's retry window is minutes, not days, so 30 days is
        generous. Without this, every webhook hit (and every Twilio
        retry attempt) accumulates a row forever; the table grows
        unboundedly and the UNIQUE-index INSERT on the hot path
        eventually slows linearly with channel age. Returns rows
        removed.
        """
        cutoff = time.time() - older_than_seconds
        with self._writing() as conn:
            cur = conn.execute(
                "DELETE FROM processed_messages WHERE seen_at < ?", (cutoff,),
            )
            return cur.rowcount

    def is_processed_message(self, channel: str, external_id: str) -> bool:
        """Returns True iff a row exists for (channel, external_id),
        regardless of whether goal_id is set."""
        row = self.conn.execute(
            "SELECT 1 FROM processed_messages "
            "WHERE channel = ? AND external_id = ? LIMIT 1",
            (channel, external_id),
        ).fetchone()
        return row is not None

    # ----- attachments -----
    def add_attachment(
        self,
        goal_id: int,
        filename: str,
        mime: str,
        size_bytes: int,
        sha256: str,
        path: str,
    ) -> int:
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO attachments(goal_id, filename, mime, size_bytes, sha256, path, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (goal_id, filename, mime, size_bytes, sha256, path, time.time()),
            )
            return cur.lastrowid

    def list_attachments(self, goal_id: int) -> list[Attachment]:
        rows = self.conn.execute(
            "SELECT id, goal_id, filename, mime, size_bytes, sha256, path, created_at "
            "FROM attachments WHERE goal_id = ? ORDER BY id",
            (goal_id,),
        ).fetchall()
        return [Attachment(**dict(r)) for r in rows]

    def prune_conversations(self, idle_for_seconds: float = 90 * 24 * 3600) -> int:
        """Delete conversations idle for N seconds and their turns. Rows removed."""
        cutoff = time.time() - idle_for_seconds
        with self._writing() as conn:
            # Delete turns first so we don't orphan them (no ON DELETE CASCADE).
            conn.execute(
                "DELETE FROM turns WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE last_seen < ?)",
                (cutoff,),
            )
            cur = conn.execute(
                "DELETE FROM conversations WHERE last_seen < ?", (cutoff,)
            )
            return cur.rowcount
