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

Implementation scope: enough to pass the ``conn``-only paths the agent
kernel uses (goals, episodes, events, attachments). For the small
metadata tables that are write-heavy mostly used by channels, we
defer to a future iteration -- this batch ships the shape + the
hot-path methods.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Reported by the schema_version property for parity with the SQLite backend.
# The PG schema is applied idempotently (CREATE ... IF NOT EXISTS + ALTER ...
# ADD COLUMN IF NOT EXISTS), not version-stepped, so this is a flat constant.
_PG_SCHEMA_VERSION = 9


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
    # Idempotent add to mirror the SQLite facts table's episode attribution.
    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_episode_id INTEGER;",
]


@dataclass
class PGGoal:
    """Mirror of maverick.world_model.Goal — same fields for drop-in compat."""
    id: int
    parent_id: int | None
    title: str
    description: str | None
    status: str
    created_at: float
    updated_at: float
    deadline: float | None
    result: str | None


@dataclass
class PGEpisodeSpend:
    """Mirror of maverick.world_model.EpisodeSpend."""
    id: int
    goal_id: int
    started_at: float
    ended_at: float | None
    outcome: str | None
    cost_dollars: float
    input_tokens: int
    output_tokens: int
    tool_calls: int


class PostgresWorldModel:
    """Postgres adapter. Public surface mirrors SQLite WorldModel.

    Constructed lazily: importing psycopg only happens when the user
    actually configures the postgres backend.
    """

    def __init__(self, dsn: str | None = None):
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

    def __enter__(self) -> PostgresWorldModel:
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

    def create_goal(self, title: str, description: str = "", parent_id: int | None = None) -> int:
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

    def get_goal(self, goal_id: int) -> PGGoal | None:
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

    def set_goal_status(self, goal_id: int, status: str, *, result: str | None = None) -> None:
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
                "WHERE status IN ('pending', 'in_progress', 'running') "
                "ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    _GOAL_COLS = (
        "id, parent_id, title, description, status, "
        "created_at, updated_at, deadline, result"
    )

    def active_goal(self) -> PGGoal | None:
        """The most-recently-touched active/blocked goal (kernel contract:
        matches SQLite WorldModel.active_goal)."""
        with self._tx() as cur:
            cur.execute(
                f"SELECT {self._GOAL_COLS} FROM goals "
                "WHERE status IN ('active', 'blocked') "
                "ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        return PGGoal(*row) if row else None

    def list_goals(
        self,
        status: str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[PGGoal]:
        """List goals, optionally filtered + paginated (mirrors SQLite)."""
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        sql = f"SELECT {self._GOAL_COLS} FROM goals"
        params: list[Any] = []
        if status:
            sql += " WHERE status = %s"
            params.append(status)
        sql += f" ORDER BY id {direction}"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def reclaim_orphan_goals(self, *, max_age_seconds: float = 60.0) -> int:
        """Mark stale active/pending goals as blocked after a crash. Only rows
        whose updated_at is at least ``max_age_seconds`` old qualify, so a goal
        live in a sibling process isn't reclaimed (matches SQLite)."""
        cutoff = time.time() - max_age_seconds
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                "UPDATE goals SET status = 'blocked', "
                "result = COALESCE(result, '') || ' [process restarted mid-run]', "
                "updated_at = %s "
                "WHERE status IN ('active', 'pending') AND updated_at < %s",
                (now, cutoff),
            )
            return cur.rowcount

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

    _EPISODE_COLS = (
        "id, goal_id, started_at, ended_at, outcome, "
        "COALESCE(cost_dollars, 0), COALESCE(input_tokens, 0), "
        "COALESCE(output_tokens, 0), COALESCE(tool_calls, 0)"
    )

    def list_episodes(
        self, limit: int = 50, goal_id: int | None = None,
    ) -> list[PGEpisodeSpend]:
        """Recent episodes with spend (mirrors SQLite WorldModel.list_episodes)."""
        sql = f"SELECT {self._EPISODE_COLS} FROM episodes"
        params: list[Any] = []
        if goal_id is not None:
            sql += " WHERE goal_id = %s"
            params.append(goal_id)
        sql += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [PGEpisodeSpend(*r) for r in rows]

    def total_spend(self) -> dict[str, float]:
        """Lifetime totals across finished episodes (mirrors SQLite)."""
        with self._tx() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(cost_dollars), 0), "
                "COALESCE(SUM(input_tokens), 0), "
                "COALESCE(SUM(output_tokens), 0), "
                "COUNT(*) FROM episodes WHERE ended_at IS NOT NULL"
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

    # ----- facts (global key/value memory) -----

    def upsert_fact(self, key: str, value: str, episode_id: int | None = None) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO facts(key, value, source_episode_id, updated_at) "
                "VALUES(%s, %s, %s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, "
                "source_episode_id = EXCLUDED.source_episode_id, "
                "updated_at = EXCLUDED.updated_at",
                (key, value, episode_id, time.time()),
            )

    def get_facts(self) -> dict[str, str]:
        with self._tx() as cur:
            cur.execute("SELECT key, value FROM facts ORDER BY updated_at DESC")
            rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}

    def facts_matching(self, token: str) -> dict[str, str]:
        """Facts explicitly scoped to ``token`` by ``user:<token>:`` key prefix.

        Mirrors the SQLite backend: only deliberately namespaced keys are
        considered (never values, never arbitrary substrings), so GDPR
        export/erase can't disclose or delete unrelated global facts.
        """
        if not token:
            return {}
        prefix = f"user:{token}:"
        return {k: v for k, v in self.get_facts().items() if k.startswith(prefix)}

    def delete_facts_matching(self, token: str) -> list[str]:
        """Delete user-scoped facts (see :meth:`facts_matching`); return the keys."""
        keys = sorted(self.facts_matching(token).keys())
        if keys:
            ph = ",".join(["%s"] * len(keys))
            with self._tx() as cur:
                cur.execute(f"DELETE FROM facts WHERE key IN ({ph})", keys)
        return keys

    @property
    def schema_version(self) -> int:
        """Schema version, for parity with SQLite WorldModel.schema_version
        (read by health.py / audit events). The PG schema is applied
        idempotently via SCHEMA, not version-stepped, so this is a constant."""
        return _PG_SCHEMA_VERSION

    # ----- close -----

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass


def open_postgres_world(dsn: str | None = None) -> PostgresWorldModel:
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
