"""Postgres-backed world model.

A drop-in alternative to the default SQLite WorldModel for users
running Maverick on a server / cluster who want a shared backend
across processes.

Selected via config:

    [world_model]
    backend = "postgres"
    dsn     = "${MAVERICK_PG_DSN}"   # e.g. postgres://user:pass@host:5432/maverick

Or env:
    MAVERICK_WORLD_BACKEND=postgres
    MAVERICK_PG_DSN=postgres://...

Behind ``maverick-agent[postgres]`` extra (pulls in ``psycopg[binary]``).

Implementation scope: enough to pass the world-model paths the agent
kernel, channels, and CLI use (goals, episodes, events, facts,
questions, conversations, attachments, and idempotency metadata).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)


# Schema mirror. Postgres-flavored types; sequence-based PKs instead of
# AUTOINCREMENT, REAL -> DOUBLE PRECISION, TEXT stays TEXT.
SCHEMA: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS goals (
      id            SERIAL PRIMARY KEY,
      parent_id     INTEGER REFERENCES goals(id),
      title         TEXT NOT NULL,
      description   TEXT,
      status        TEXT NOT NULL DEFAULT 'pending',
      created_at    DOUBLE PRECISION NOT NULL,
      updated_at    DOUBLE PRECISION NOT NULL,
      deadline      DOUBLE PRECISION,
      result        TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_goals_status_updated ON goals(status, updated_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_pg_goals_parent ON goals(parent_id, created_at);",
    """
    CREATE TABLE IF NOT EXISTS episodes (
      id            SERIAL PRIMARY KEY,
      goal_id       INTEGER NOT NULL REFERENCES goals(id),
      started_at    DOUBLE PRECISION NOT NULL,
      ended_at      DOUBLE PRECISION,
      summary       TEXT,
      outcome       TEXT,
      cost_dollars  DOUBLE PRECISION DEFAULT 0,
      input_tokens  INTEGER DEFAULT 0,
      output_tokens INTEGER DEFAULT 0,
      tool_calls    INTEGER DEFAULT 0
    );
    """,
    # Idempotent add for DBs created before `summary` existed.
    "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS summary TEXT;",
    "CREATE INDEX IF NOT EXISTS idx_pg_episodes_goal_started ON episodes(goal_id, started_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS goal_events (
      id        SERIAL PRIMARY KEY,
      goal_id   INTEGER NOT NULL REFERENCES goals(id),
      agent     TEXT NOT NULL,
      kind      TEXT NOT NULL,
      content   TEXT NOT NULL,
      ts        DOUBLE PRECISION NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_goal_events_goal_id_id ON goal_events(goal_id, id);",
    """
    CREATE TABLE IF NOT EXISTS facts (
      id            SERIAL PRIMARY KEY,
      key           TEXT NOT NULL UNIQUE,
      value         TEXT NOT NULL,
      updated_at    DOUBLE PRECISION NOT NULL
    );
    """,
    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_episode_id INTEGER REFERENCES episodes(id);",
    """
    CREATE TABLE IF NOT EXISTS questions (
      id          SERIAL PRIMARY KEY,
      goal_id     INTEGER REFERENCES goals(id),
      question    TEXT NOT NULL,
      asked_at    DOUBLE PRECISION NOT NULL,
      answer      TEXT,
      answered_at DOUBLE PRECISION
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_questions_goal_id ON questions(goal_id, id);",
    """
    CREATE TABLE IF NOT EXISTS messages (
      id      SERIAL PRIMARY KEY,
      goal_id INTEGER REFERENCES goals(id),
      role    TEXT NOT NULL,
      content TEXT NOT NULL,
      ts      DOUBLE PRECISION NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_messages_ts ON messages(ts DESC);",
    """
    CREATE TABLE IF NOT EXISTS conversations (
      id         SERIAL PRIMARY KEY,
      channel    TEXT NOT NULL,
      user_id    TEXT NOT NULL,
      created_at DOUBLE PRECISION NOT NULL,
      last_seen  DOUBLE PRECISION NOT NULL,
      UNIQUE(channel, user_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_conversations_last_seen ON conversations(last_seen);",
    """
    CREATE TABLE IF NOT EXISTS turns (
      id              SERIAL PRIMARY KEY,
      conversation_id INTEGER NOT NULL REFERENCES conversations(id),
      goal_id         INTEGER REFERENCES goals(id),
      role            TEXT NOT NULL,
      content         TEXT NOT NULL,
      ts              DOUBLE PRECISION NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_turns_conv_id ON turns(conversation_id, id);",
    """
    CREATE TABLE IF NOT EXISTS attachments (
      id         SERIAL PRIMARY KEY,
      goal_id    INTEGER NOT NULL REFERENCES goals(id),
      filename   TEXT NOT NULL,
      mime       TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      sha256     TEXT NOT NULL,
      path       TEXT NOT NULL,
      created_at DOUBLE PRECISION NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_attachments_goal_id ON attachments(goal_id);",
    """
    CREATE TABLE IF NOT EXISTS processed_messages (
      id          SERIAL PRIMARY KEY,
      channel     TEXT NOT NULL,
      external_id TEXT NOT NULL,
      goal_id     INTEGER REFERENCES goals(id),
      seen_at     DOUBLE PRECISION NOT NULL,
      UNIQUE(channel, external_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
      id           SERIAL PRIMARY KEY,
      action       TEXT NOT NULL,
      risk         TEXT NOT NULL DEFAULT 'medium',
      scope        TEXT,
      detail       TEXT,
      status       TEXT NOT NULL DEFAULT 'pending',
      requested_at DOUBLE PRECISION NOT NULL,
      decided_at   DOUBLE PRECISION
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_approvals_status_id ON approvals(status, id);",
]


@dataclass
class PGGoal:
    """Mirror of maverick.world_model.Goal — same fields for drop-in compat."""
    id: int
    parent_id: Optional[int]
    title: str
    description: Optional[str]
    status: str
    created_at: float
    updated_at: float
    deadline: Optional[float]
    result: Optional[str]


class PostgresWorldModel:
    """Postgres adapter. Public surface mirrors SQLite WorldModel.

    Constructed lazily: importing psycopg only happens when the user
    actually configures the postgres backend.
    """

    def __init__(self, dsn: Optional[str] = None):
        try:
            import psycopg  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "psycopg not installed. Run: pip install 'maverick-agent[postgres]'"
            ) from e
        import psycopg
        self._dsn = dsn or os.environ.get("MAVERICK_PG_DSN") or ""
        if not self._dsn:
            raise RuntimeError(
                "Postgres world model requires MAVERICK_PG_DSN or "
                "[world_model] dsn in config.toml."
            )
        self.conn = psycopg.connect(self._dsn, autocommit=False)
        # One long-lived connection shared across this object. psycopg
        # connections are NOT safe for concurrent use by multiple threads,
        # and the kernel drives this from FastAPI's threadpool + the
        # background runner. Serialize every transaction the way the SQLite
        # WorldModel does with its RLock; without it, interleaved
        # execute/commit/rollback corrupt results or raise
        # InFailedSqlTransaction. (Reentrant so a method can nest _tx.)
        self._lock = threading.RLock()
        self._migrate()

    def __enter__(self) -> "PostgresWorldModel":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator:
        """Cursor scope that commits on success and ROLLS BACK on error.

        Critical for autocommit=False: a single failed statement aborts
        the transaction, and without a rollback every later statement on
        this (shared, long-lived) connection fails with
        InFailedSqlTransaction until the process restarts. Rolling back
        keeps the connection usable.
        """
        with self._lock:
            cur = self.conn.cursor()
            try:
                yield cur
                self.conn.commit()
            except Exception:
                try:
                    self.conn.rollback()
                except Exception:  # pragma: no cover
                    pass
                raise
            finally:
                cur.close()

    def _migrate(self) -> None:
        with self._tx() as cur:
            for stmt in SCHEMA:
                cur.execute(stmt)

    # ----- goal methods -----

    def create_goal(self, title: str, description: str = "", parent_id: Optional[int] = None) -> int:
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO goals(parent_id, title, description, status, "
                "created_at, updated_at) VALUES(%s, %s, %s, 'pending', %s, %s) "
                "RETURNING id",
                (parent_id, title, description, now, now),
            )
            row = cur.fetchone()
        return int(row[0])

    def get_goal(self, goal_id: int) -> Optional[PGGoal]:
        with self._tx() as cur:
            cur.execute(
                "SELECT id, parent_id, title, description, status, "
                "created_at, updated_at, deadline, result FROM goals WHERE id=%s",
                (goal_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return PGGoal(*row)

    def set_goal_status(self, goal_id: int, status: str, *, result: Optional[str] = None) -> None:
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                # COALESCE so a status-only update (result=None) doesn't wipe
                # an existing result -- matches the SQLite backend.
                "UPDATE goals SET status=%s, result=COALESCE(%s, result), "
                "updated_at=%s WHERE id=%s",
                (status, result, now, goal_id),
            )

    def list_active_goals(self, limit: int = 50) -> list[PGGoal]:
        with self._tx() as cur:
            cur.execute(
                "SELECT id, parent_id, title, description, status, "
                "created_at, updated_at, deadline, result FROM goals "
                "WHERE status IN ('pending', 'in_progress', 'running', 'active') "
                "ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def list_goals(
        self,
        status: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[PGGoal]:
        direction = "DESC" if order.lower() == "desc" else "ASC"
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals"
        )
        params: list[Any] = []
        if status:
            sql += " WHERE status=%s"
            params.append(status)
        sql += f" ORDER BY id {direction}"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend((max(1, int(limit)), max(0, int(offset))))
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def active_goal(self) -> Optional[PGGoal]:
        with self._tx() as cur:
            cur.execute(
                "SELECT id, parent_id, title, description, status, "
                "created_at, updated_at, deadline, result FROM goals "
                "WHERE status IN ('active', 'blocked') "
                "ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        return PGGoal(*row) if row else None

    def reclaim_orphan_goals(self, *, max_age_seconds: float = 60.0) -> int:
        cutoff = time.time() - max_age_seconds
        with self._tx() as cur:
            cur.execute(
                "UPDATE goals SET status='blocked', updated_at=%s, "
                "result=COALESCE(result, 'reclaimed after interrupted run') "
                "WHERE status='active' AND updated_at < %s",
                (time.time(), cutoff),
            )
            return int(cur.rowcount or 0)

    # ----- episodes -----

    def start_episode(self, goal_id: int) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO episodes(goal_id, started_at) VALUES(%s, %s) "
                "RETURNING id",
                (goal_id, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def end_episode(
        self,
        episode_id: int,
        summary: str,
        outcome: str,
        *,
        cost_dollars: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: int = 0,
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE episodes SET ended_at=%s, summary=%s, outcome=%s, "
                "cost_dollars=%s, input_tokens=%s, output_tokens=%s, "
                "tool_calls=%s WHERE id=%s",
                (time.time(), summary, outcome,
                 cost_dollars, input_tokens, output_tokens, tool_calls,
                 episode_id),
            )

    def list_episodes(
        self,
        limit: int = 50,
        goal_id: Optional[int] = None,
    ) -> list:
        from ..world_model import EpisodeSpend

        select = (
            "SELECT id, goal_id, started_at, ended_at, outcome, "
            "COALESCE(cost_dollars, 0), COALESCE(input_tokens, 0), "
            "COALESCE(output_tokens, 0), COALESCE(tool_calls, 0) FROM episodes"
        )
        if goal_id is not None:
            sql = select + " WHERE goal_id=%s ORDER BY started_at DESC LIMIT %s"
            params: tuple[Any, ...] = (goal_id, limit)
        else:
            sql = select + " ORDER BY started_at DESC LIMIT %s"
            params = (limit,)
        with self._tx() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [EpisodeSpend(*r) for r in rows]

    def total_spend(self) -> dict[str, float]:
        with self._tx() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(cost_dollars), 0), "
                "COALESCE(SUM(input_tokens), 0), "
                "COALESCE(SUM(output_tokens), 0), COUNT(*) "
                "FROM episodes WHERE ended_at IS NOT NULL"
            )
            row = cur.fetchone()
        return {
            "dollars": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "runs": row[3],
        }

    # ----- events -----

    def append_event(self, goal_id: int, agent: str, kind: str, content: str) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO goal_events(goal_id, agent, kind, content, ts) "
                "VALUES(%s, %s, %s, %s, %s) RETURNING id",
                (goal_id, agent, kind, content, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def goal_events(self, goal_id: int, since_id: int = 0, limit: int = 200) -> list:
        from ..world_model import GoalEvent
        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, agent, kind, content, ts FROM goal_events "
                "WHERE goal_id=%s AND id > %s ORDER BY id ASC LIMIT %s",
                (goal_id, since_id, limit),
            )
            rows = cur.fetchall()
        return [GoalEvent(*r) for r in rows]

    def prune_goal_events(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        cutoff = time.time() - older_than_seconds
        with self._tx() as cur:
            cur.execute("DELETE FROM goal_events WHERE ts < %s", (cutoff,))
            return int(cur.rowcount or 0)

    # ----- facts -----

    def upsert_fact(self, key: str, value: str, episode_id: Optional[int] = None) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO facts(key, value, source_episode_id, updated_at) "
                "VALUES(%s, %s, %s, %s) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = EXCLUDED.value, "
                "source_episode_id = EXCLUDED.source_episode_id, "
                "updated_at = EXCLUDED.updated_at",
                (key, value, episode_id, time.time()),
            )

    def get_facts(self) -> dict[str, str]:
        with self._tx() as cur:
            cur.execute("SELECT key, value FROM facts ORDER BY updated_at DESC")
            rows = cur.fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    # ----- questions -----

    def ask(self, question: str, goal_id: Optional[int] = None) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO questions(goal_id, question, asked_at) "
                "VALUES(%s, %s, %s) RETURNING id",
                (goal_id, question, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def answer(self, question_id: int, answer: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE questions SET answer=%s, answered_at=%s WHERE id=%s",
                (answer, time.time(), question_id),
            )

    def open_questions(self, goal_id: Optional[int] = None) -> list:
        from ..world_model import Question

        if goal_id is not None:
            sql = (
                "SELECT id, goal_id, question, asked_at, answer, answered_at "
                "FROM questions WHERE answer IS NULL AND goal_id=%s ORDER BY id"
            )
            params: tuple[Any, ...] = (goal_id,)
        else:
            sql = (
                "SELECT id, goal_id, question, asked_at, answer, answered_at "
                "FROM questions WHERE answer IS NULL ORDER BY id"
            )
            params = ()
        with self._tx() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [Question(*r) for r in rows]

    def all_questions(self, goal_id: int) -> list:
        from ..world_model import Question

        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, question, asked_at, answer, answered_at "
                "FROM questions WHERE goal_id=%s ORDER BY id",
                (goal_id,),
            )
            rows = cur.fetchall()
        return [Question(*r) for r in rows]

    # ----- approvals -----

    def create_approval(
        self,
        action: str,
        *,
        risk: str = "medium",
        scope: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO approvals(action, risk, scope, detail, status, requested_at) "
                "VALUES(%s, %s, %s, %s, 'pending', %s) RETURNING id",
                (action, risk, scope, detail, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def get_approval(self, approval_id: int):
        from ..world_model import Approval

        with self._tx() as cur:
            cur.execute(
                "SELECT id, action, risk, scope, detail, status, requested_at, decided_at "
                "FROM approvals WHERE id=%s",
                (approval_id,),
            )
            row = cur.fetchone()
        return Approval(*row) if row else None

    def pending_approvals(self) -> list:
        from ..world_model import Approval

        with self._tx() as cur:
            cur.execute(
                "SELECT id, action, risk, scope, detail, status, requested_at, decided_at "
                "FROM approvals WHERE status='pending' ORDER BY id"
            )
            rows = cur.fetchall()
        return [Approval(*r) for r in rows]

    def decide_approval(self, approval_id: int, status: str) -> bool:
        if status not in ("approved", "denied"):
            raise ValueError("status must be 'approved' or 'denied'")
        with self._tx() as cur:
            cur.execute(
                "UPDATE approvals SET status=%s, decided_at=%s "
                "WHERE id=%s AND status='pending'",
                (status, time.time(), approval_id),
            )
            return bool(cur.rowcount and cur.rowcount > 0)

    # ----- messages -----

    def append_message(self, goal_id: int, role: str, content: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO messages(goal_id, role, content, ts) VALUES(%s, %s, %s, %s)",
                (goal_id, role, content, time.time()),
            )

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, role, content, ts FROM messages "
                "WHERE content ILIKE %s ORDER BY ts DESC LIMIT %s",
                (f"%{query}%", limit),
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "goal_id": r[1], "role": r[2], "content": r[3], "ts": r[4]}
            for r in rows
        ]

    # ----- conversations -----

    def get_or_create_conversation(self, channel: str, user_id: str):
        from ..world_model import Conversation

        now = time.time()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO conversations(channel, user_id, created_at, last_seen) "
                "VALUES(%s, %s, %s, %s) "
                "ON CONFLICT(channel, user_id) DO UPDATE SET last_seen = EXCLUDED.last_seen "
                "RETURNING id, channel, user_id, created_at, last_seen",
                (channel, user_id, now, now),
            )
            row = cur.fetchone()
        return Conversation(*row)

    def append_turn(
        self,
        conversation_id: int,
        role: str,
        content: str,
        goal_id: Optional[int] = None,
    ) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO turns(conversation_id, goal_id, role, content, ts) "
                "VALUES(%s, %s, %s, %s, %s) RETURNING id",
                (conversation_id, goal_id, role, content, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def recent_turns(self, conversation_id: int, limit: int = 20) -> list:
        from ..world_model import Turn

        with self._tx() as cur:
            cur.execute(
                "SELECT id, conversation_id, goal_id, role, content, ts FROM ("
                "SELECT id, conversation_id, goal_id, role, content, ts FROM turns "
                "WHERE conversation_id=%s ORDER BY id DESC LIMIT %s"
                ") recent ORDER BY id ASC",
                (conversation_id, limit),
            )
            rows = cur.fetchall()
        return [Turn(*r) for r in rows]

    def list_conversations(self, channel: Optional[str] = None) -> list:
        from ..world_model import Conversation

        if channel:
            sql = (
                "SELECT id, channel, user_id, created_at, last_seen FROM conversations "
                "WHERE channel=%s ORDER BY last_seen DESC"
            )
            params: tuple[Any, ...] = (channel,)
        else:
            sql = (
                "SELECT id, channel, user_id, created_at, last_seen FROM conversations "
                "ORDER BY last_seen DESC"
            )
            params = ()
        with self._tx() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [Conversation(*r) for r in rows]

    def prune_conversations(self, idle_for_seconds: float = 90 * 24 * 3600) -> int:
        cutoff = time.time() - idle_for_seconds
        with self._tx() as cur:
            cur.execute(
                "DELETE FROM turns WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE last_seen < %s)",
                (cutoff,),
            )
            cur.execute("DELETE FROM conversations WHERE last_seen < %s", (cutoff,))
            return int(cur.rowcount or 0)

    # ----- channel dedup -----

    def mark_message_processed(
        self,
        channel: str,
        external_id: str,
        goal_id: Optional[int] = None,
    ) -> bool:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO processed_messages(channel, external_id, goal_id, seen_at) "
                "VALUES(%s, %s, %s, %s) ON CONFLICT(channel, external_id) DO NOTHING "
                "RETURNING id",
                (channel, external_id, goal_id, time.time()),
            )
            return cur.fetchone() is not None

    def lookup_processed_message(self, channel: str, external_id: str) -> Optional[int]:
        with self._tx() as cur:
            cur.execute(
                "SELECT goal_id FROM processed_messages WHERE channel=%s AND external_id=%s",
                (channel, external_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return int(row[0]) if row[0] is not None else 0

    def is_processed_message(self, channel: str, external_id: str) -> bool:
        with self._tx() as cur:
            cur.execute(
                "SELECT 1 FROM processed_messages "
                "WHERE channel=%s AND external_id=%s LIMIT 1",
                (channel, external_id),
            )
            return cur.fetchone() is not None

    def prune_processed_messages(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        cutoff = time.time() - older_than_seconds
        with self._tx() as cur:
            cur.execute("DELETE FROM processed_messages WHERE seen_at < %s", (cutoff,))
            return int(cur.rowcount or 0)

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
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO attachments(goal_id, filename, mime, size_bytes, sha256, path, created_at) "
                "VALUES(%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (goal_id, filename, mime, size_bytes, sha256, path, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def list_attachments(self, goal_id: int) -> list:
        from ..world_model import Attachment

        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, filename, mime, size_bytes, sha256, path, created_at "
                "FROM attachments WHERE goal_id=%s ORDER BY id",
                (goal_id,),
            )
            rows = cur.fetchall()
        return [Attachment(*r) for r in rows]

    # ----- close -----

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass


def open_postgres_world(dsn: Optional[str] = None) -> PostgresWorldModel:
    """Open a Postgres world model. Convenience wrapper that resolves DSN."""
    return PostgresWorldModel(dsn=dsn)


def is_postgres_configured() -> bool:
    """True if config / env requests the postgres backend."""
    if os.environ.get("MAVERICK_WORLD_BACKEND", "").strip().lower() == "postgres":
        return True
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("world_model") or {}
        return (cfg.get("backend") or "").strip().lower() == "postgres"
    except Exception:
        return False


__all__ = [
    "PostgresWorldModel",
    "PGGoal",
    "open_postgres_world",
    "is_postgres_configured",
    "SCHEMA",
]
