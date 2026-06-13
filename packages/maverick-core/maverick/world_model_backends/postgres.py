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

log = logging.getLogger(__name__)

# Read by the schema_version property (health.py / audit events). Driven from
# the migration ladder below: the highest migration version. PG now carries the
# tenant-isolation migration (v10), which the SQLite backend implements
# structurally instead (one world.db file per tenant under ~/.maverick/tenants/).


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
    """
    CREATE TABLE IF NOT EXISTS approvals (
      id           SERIAL PRIMARY KEY,
      action       TEXT NOT NULL,
      risk         TEXT NOT NULL DEFAULT 'medium',
      scope        TEXT,
      detail       TEXT,
      provenance   TEXT,
      status       TEXT NOT NULL DEFAULT 'pending',
      requested_at DOUBLE PRECISION NOT NULL,
      decided_at   DOUBLE PRECISION
    );
    """,
    "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS provenance TEXT;",
    # Collaborative supervision (claiming + decider attribution) — mirrors
    # the SQLite v13 migration.
    "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS claimed_by TEXT;",
    "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS claimed_at DOUBLE PRECISION;",
    "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS decided_by TEXT;",
    "CREATE INDEX IF NOT EXISTS idx_pg_approvals_status ON approvals(status, id);",
    """
    CREATE TABLE IF NOT EXISTS conversations (
      id          SERIAL PRIMARY KEY,
      channel     TEXT NOT NULL,
      user_id     TEXT NOT NULL,
      created_at  DOUBLE PRECISION NOT NULL,
      last_seen   DOUBLE PRECISION NOT NULL,
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
    CREATE TABLE IF NOT EXISTS messages (
      id        SERIAL PRIMARY KEY,
      goal_id   INTEGER REFERENCES goals(id),
      role      TEXT NOT NULL,
      content   TEXT NOT NULL,
      ts        DOUBLE PRECISION NOT NULL
    );
    """,
    # Full-text search index over message content. Postgres has no FTS5; the
    # native equivalent is a GIN index on to_tsvector(...), queried with
    # plainto_tsquery (which safely parses arbitrary natural-language input,
    # the PG analog to the SQLite quoting fix). IMMUTABLE-safe via 'english'.
    "CREATE INDEX IF NOT EXISTS idx_pg_messages_fts "
    "ON messages USING GIN (to_tsvector('english', content));",
    """
    CREATE TABLE IF NOT EXISTS attachments (
      id          SERIAL PRIMARY KEY,
      goal_id     INTEGER NOT NULL REFERENCES goals(id),
      filename    TEXT NOT NULL,
      mime        TEXT NOT NULL,
      size_bytes  INTEGER NOT NULL,
      sha256      TEXT NOT NULL,
      path        TEXT NOT NULL,
      created_at  DOUBLE PRECISION NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_attachments_goal_id ON attachments(goal_id);",
    """
    CREATE TABLE IF NOT EXISTS processed_messages (
      id           SERIAL PRIMARY KEY,
      channel      TEXT NOT NULL,
      external_id  TEXT NOT NULL,
      goal_id      INTEGER REFERENCES goals(id),
      seen_at      DOUBLE PRECISION NOT NULL,
      UNIQUE(channel, external_id)
    );
    """,
]


# --- Tenancy (migration v10) -------------------------------------------------
# Multi-tenant seam for the shared-Postgres backend. The root tables get a
# nullable ``tenant_id``; child rows (episodes, goal_events, turns, ...) inherit
# their tenant through their goal/conversation FK, so they need no column of
# their own for isolation. ``NULL`` is the legacy single-tenant install
# (``paths.current_tenant()`` returns ``None``), so existing rows and every
# default deployment are unaffected. v10 adds the columns + indexes; writes are
# stamped and reads scoped across all root tables (goals/facts/conversations/
# approvals/processed_messages), with v11 making their global UNIQUE constraints
# tenant-aware so one tenant's upsert can't clobber another's row.
_TENANT_TABLES = ("goals", "facts", "conversations", "approvals", "processed_messages")
_TENANT_MIGRATION: list[str] = [
    f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS tenant_id TEXT;" for t in _TENANT_TABLES
] + [
    f"CREATE INDEX IF NOT EXISTS idx_pg_{t}_tenant ON {t}(tenant_id);"
    for t in _TENANT_TABLES
]


# --- Tenant-aware uniqueness (migration v11) ---------------------------------
# The root tables with a global UNIQUE (facts.key, conversations(channel,
# user_id), processed_messages(channel, external_id)) need that uniqueness made
# per-tenant -- otherwise two tenants reusing the same key/channel collide and
# one's write clobbers the other's row. We replace each global UNIQUE with a
# expression unique index over ``COALESCE(tenant_id, '')`` + the natural key:
# version-independent (no PG15 NULLS-NOT-DISTINCT needed), and NULL (the legacy
# single-tenant install) collapses to '' so existing dedup/upsert is preserved
# byte-for-byte. The upserts below target the same expression so ON CONFLICT
# still fires. Dropping the old constraint by its deterministic default name is
# IF EXISTS, so a re-run or a differently-named constraint is a safe no-op.
_TENANT_UNIQUE_MIGRATION: list[str] = [
    "ALTER TABLE facts DROP CONSTRAINT IF EXISTS facts_key_key;",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_facts_tenant_key "
    "ON facts (COALESCE(tenant_id, ''), key);",
    "ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_channel_user_id_key;",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_conversations_tenant_chan_user "
    "ON conversations (COALESCE(tenant_id, ''), channel, user_id);",
    "ALTER TABLE processed_messages "
    "DROP CONSTRAINT IF EXISTS processed_messages_channel_external_id_key;",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_processed_tenant_chan_ext "
    "ON processed_messages (COALESCE(tenant_id, ''), channel, external_id);",
]


# Ordered schema migrations: ``(version, statements)``. v1 is the consolidated
# base schema (idempotent CREATEs, so a fresh DB and a pre-framework DB both
# converge); higher versions are incremental. The applied set is tracked in the
# ``schema_migrations`` table so a statement runs at most once and the first
# schema change against live customer data has a safe, recorded path.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, SCHEMA),
    (10, _TENANT_MIGRATION),
    (11, _TENANT_UNIQUE_MIGRATION),
]

# Highest migration version = the reported schema version.
_PG_SCHEMA_VERSION = MIGRATIONS[-1][0]

_MIGRATIONS_TABLE = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "  version    INTEGER PRIMARY KEY,"
    "  applied_at DOUBLE PRECISION NOT NULL"
    ");"
)


def pending_migrations(
    current_version: int,
    migrations: list[tuple[int, list[str]]] | None = None,
) -> list[tuple[int, list[str]]]:
    """Migrations with ``version > current_version``, in ascending order.

    Pure planner (no DB) so the upgrade logic is unit-tested directly.
    """
    migs = MIGRATIONS if migrations is None else migrations
    return [(v, stmts) for v, stmts in sorted(migs) if v > current_version]


def _active_tenant() -> str | None:
    """The tenant scoping this call, or ``None`` for the legacy single-tenant
    store. Lazy import keeps this module free of a hard ``paths`` dependency."""
    try:
        from ..paths import current_tenant
        return current_tenant()
    except Exception:  # pragma: no cover -- tenancy never blocks a query
        return None


def _strict_tenant_isolation() -> bool:
    """Strict per-tenant reads (default off). When on, a tenant sees **only** its
    own rows -- legacy ``NULL`` rows are no longer visible. Enable only after the
    legacy rows have been backfilled with a tenant_id. ``MAVERICK_STRICT_TENANT_
    ISOLATION`` env wins over ``[world_model] strict_tenant_isolation``."""
    import os
    env = os.environ.get("MAVERICK_STRICT_TENANT_ISOLATION")
    if env is not None and env.strip() != "":
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from ..config import load_config
        v = (load_config() or {}).get("world_model", {}).get("strict_tenant_isolation")
    except Exception:  # pragma: no cover -- config never blocks a query
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "on"} if isinstance(v, str) else bool(v)


def _rls_enabled() -> bool:
    """DB-native Row-Level Security (default off). When on, the tenant-scoped
    tables get a Postgres RLS policy keyed on the ``maverick.tenant`` session
    GUC, so the database enforces the tenant boundary even if an app-layer
    predicate is ever missed — defense in depth over ``_tenant_scope``. Opt-in
    because it implies the legacy ``NULL`` rows have been backfilled (RLS scopes
    strictly to the active tenant). ``MAVERICK_PG_RLS`` env wins over
    ``[world_model] rls``."""
    env = os.environ.get("MAVERICK_PG_RLS")
    if env is not None and env.strip() != "":
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from ..config import load_config
        v = (load_config() or {}).get("world_model", {}).get("rls")
    except Exception:  # pragma: no cover -- config never blocks construction
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "on"} if isinstance(v, str) else bool(v)


def _pool_size() -> int:
    """Max connections for the optional ``psycopg_pool`` connection pool
    (default 0 = no pool, single shared connection as before). A positive value
    opts into pooled mode for horizontal scale under concurrent load.
    ``MAVERICK_PG_POOL_SIZE`` env wins over ``[world_model] pool_size``."""
    raw = os.environ.get("MAVERICK_PG_POOL_SIZE")
    if raw is None or raw.strip() == "":
        try:
            from ..config import load_config
            raw = (load_config() or {}).get("world_model", {}).get("pool_size")
        except Exception:  # pragma: no cover -- config never blocks construction
            raw = None
    try:
        return max(0, int(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _tenant_scope(column: str = "tenant_id") -> tuple[str, list]:
    """Read predicate scoping rows to the active tenant.

    Returns ``(sql_fragment, params)``. With **no** active tenant the fragment is
    empty -- the default single-tenant install is unchanged. With a tenant set,
    the default (NULL-tolerant) predicate matches that tenant's rows **plus**
    legacy ``NULL`` rows; strict mode (``[world_model] strict_tenant_isolation``)
    matches **only** that tenant's rows, the RLS-equivalent hard boundary.
    """
    t = _active_tenant()
    if t is None:
        return "", []
    if _strict_tenant_isolation():
        return f"{column} = %s", [t]
    return f"({column} = %s OR {column} IS NULL)", [t]


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
        self._rls = _rls_enabled()
        # Optional connection pool (opt-in via [world_model] pool_size). Pooled
        # mode hands each transaction its own connection from the pool, so the
        # backend scales across concurrent callers instead of serialising on one
        # shared connection. Default (pool_size 0) keeps the original
        # single-connection + RLock model byte-for-byte.
        self._pool = None
        size = _pool_size()
        if size > 0:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as e:
                raise ImportError(
                    "[world_model] pool_size set but psycopg_pool is not "
                    "installed. Run: pip install 'maverick-agent[postgres]'"
                ) from e
            self._pool = ConnectionPool(
                self._dsn, min_size=1, max_size=size, open=True,
                kwargs={"autocommit": False},
            )
            self.conn = None
        else:
            self.conn = psycopg.connect(self._dsn, autocommit=False)
        # One long-lived connection shared across this object (non-pooled mode).
        # psycopg connections are NOT safe for concurrent use by multiple
        # threads, and the kernel drives this from FastAPI's threadpool + the
        # background runner. Serialize every transaction the way the SQLite
        # WorldModel does with its RLock; without it, interleaved
        # execute/commit/rollback corrupt results or raise
        # InFailedSqlTransaction. (Reentrant so a method can nest _tx.) The pool
        # gives each tx its own connection, so the lock is a no-op contention
        # point there but harmless.
        self._lock = threading.RLock()
        self._migrate()
        if self._rls:
            self._apply_rls()

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
        if self._pool is not None:
            # Pooled: each tx gets its own connection; the pool's context
            # commits on success and rolls back on error, so no shared lock.
            with self._pool.connection() as conn:
                cur = conn.cursor()
                try:
                    self._set_tenant_guc(cur)
                    yield cur
                finally:
                    cur.close()
            return
        with self._lock:
            cur = self.conn.cursor()
            try:
                self._set_tenant_guc(cur)
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

    def _set_tenant_guc(self, cur) -> None:
        """Under RLS, bind this transaction to the active tenant.

        RLS is fail-closed: when no tenant is active, set an impossible sentinel
        instead of leaving the GUC unset. Queries that bypass ``_tx`` also fail
        closed because the policy does not grant access for unset/empty GUCs.
        """
        if not self._rls:
            return
        tenant = _active_tenant()
        value = str(tenant) if tenant is not None else "__maverick_no_tenant__"
        # set_config(name, value, is_local=true) is the parameterizable form of
        # SET LOCAL — transaction-scoped, cleared at commit/rollback.
        cur.execute("SELECT set_config('maverick.tenant', %s, true)", (value,))

    def _apply_rls(self) -> None:
        """Enable Postgres Row-Level Security on the tenant-scoped tables.

        Policy: a row is visible/writable only when its ``tenant_id`` equals the
        transaction-local ``maverick.tenant`` GUC set by ``_tx``. Unset, empty,
        or no-active-tenant GUC values match no rows. Idempotent
        (drop-then-create the policy; ENABLE/FORCE are no-ops if already set).

        Only a table's **owner** may ALTER it. A non-owner connection may start
        only if the owner/migration has already installed and forced the exact
        fail-closed policy; otherwise RLS startup raises instead of silently
        running without database-enforced tenant isolation.
        """
        for table in _TENANT_TABLES:
            try:
                with self._tx() as cur:
                    cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                    cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                    cur.execute(f"DROP POLICY IF EXISTS mvk_tenant_isolation ON {table}")
                    cur.execute(self._rls_policy_sql(table))
            except Exception as e:  # non-owner / insufficient privilege
                if self._rls_policy_is_active(table):
                    log.info(
                        "RLS already active on %s; continuing after setup error: %s",
                        table, e,
                    )
                    continue
                raise RuntimeError(
                    f"MAVERICK_PG_RLS is enabled but fail-closed RLS could not "
                    f"be installed or verified on {table}: {e}"
                ) from e

    @staticmethod
    def _rls_policy_sql(table: str) -> str:
        return (
            f"CREATE POLICY mvk_tenant_isolation ON {table} "
            "USING ("
            "  tenant_id = nullif(current_setting('maverick.tenant', true), '')"
            ") WITH CHECK ("
            "  tenant_id = nullif(current_setting('maverick.tenant', true), '')"
            ")"
        )

    def _rls_policy_is_active(self, table: str) -> bool:
        """Verify the fail-closed RLS policy is already installed and forced."""
        try:
            with self._tx() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid = %s::regclass",
                    (table,),
                )
                row = cur.fetchone()
                if not row or not (row[0] and row[1]):
                    return False
                cur.execute(
                    "SELECT qual, with_check FROM pg_policies "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = %s AND policyname = 'mvk_tenant_isolation'",
                    (table,),
                )
                policy = cur.fetchone()
        except Exception:
            return False
        if not policy:
            return False
        def fail_closed(expr: object) -> bool:
            text = " ".join(str(expr).lower().split())
            return (
                "tenant_id" in text
                and "current_setting" in text
                and "maverick.tenant" in text
                and "nullif" in text
                and " or " not in text
                and "is null" not in text
            )

        return fail_closed(policy[0]) and fail_closed(policy[1])

    def _migrate(self) -> None:
        """Apply pending migrations atomically, recording each in
        ``schema_migrations`` so a statement runs at most once."""
        with self._tx() as cur:
            cur.execute(_MIGRATIONS_TABLE)
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            current = int((cur.fetchone() or [0])[0])
            for version, statements in pending_migrations(current):
                for stmt in statements:
                    cur.execute(stmt)
                cur.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES(%s, %s) ON CONFLICT (version) DO NOTHING",
                    (version, time.time()),
                )

    # ----- goal methods -----

    def create_goal(self, title: str, description: str = "", parent_id: int | None = None) -> int:
        now = time.time()
        tenant = _active_tenant()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO goals(parent_id, title, description, status, "
                "created_at, updated_at, tenant_id) "
                "VALUES(%s, %s, %s, 'pending', %s, %s, %s) RETURNING id",
                (parent_id, title, description, now, now, tenant),
            )
            row = cur.fetchone()
        return int(row[0])

    def get_goal(self, goal_id: int) -> PGGoal | None:
        frag, params = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals WHERE id=%s"
        )
        p: list = [goal_id]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            row = cur.fetchone()
        if row is None:
            return None
        return PGGoal(*row)

    def set_goal_status(self, goal_id: int, status: str, *, result: str | None = None) -> None:
        now = time.time()
        frag, fparams = _tenant_scope()
        sql = (
            # COALESCE so a status-only update (result=None) doesn't wipe
            # an existing result -- matches the SQLite backend.
            "UPDATE goals SET status=%s, result=COALESCE(%s, result), "
            "updated_at=%s WHERE id=%s"
        )
        params: list = [status, result, now, goal_id]
        if frag:
            sql += " AND " + frag
            params += fparams
        with self._tx() as cur:
            cur.execute(sql, tuple(params))

    def list_active_goals(self, limit: int = 50) -> list[PGGoal]:
        frag, params = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals "
            "WHERE status IN ('pending', 'in_progress', 'running')"
        )
        p: list = []
        if frag:
            sql += " AND " + frag
            p += params
        sql += " ORDER BY updated_at DESC LIMIT %s"
        p.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def list_goals(
        self,
        status: str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[PGGoal]:
        """List goals, optionally filtered by status + paginated (mirrors SQLite)."""
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals"
        )
        params: list = []
        conds: list[str] = []
        if status:
            conds.append("status = %s")
            params.append(status)
        frag, fparams = _tenant_scope()
        if frag:
            conds.append(frag)
            params += fparams
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += f" ORDER BY id {direction}"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params += [max(1, int(limit)), max(0, int(offset))]
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def most_recent_goal(self) -> PGGoal | None:
        """Most-recently-updated goal regardless of status; mirrors SQLite."""
        frag, params = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals"
        )
        if frag:
            sql += " WHERE " + frag
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        return PGGoal(*row) if row else None

    def active_goal(self) -> PGGoal | None:
        frag, fparams = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals "
            "WHERE status IN ('active', 'blocked')"
        )
        params: list = []
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        return PGGoal(*row) if row else None

    def inflight_goal(self) -> PGGoal | None:
        """Most-recently-updated in-flight goal (active/pending); mirrors SQLite."""
        frag, fparams = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, "
            "created_at, updated_at, deadline, result FROM goals "
            "WHERE status IN ('active', 'pending')"
        )
        params: list = []
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        return PGGoal(*row) if row else None

    def candidate_goals(self, include_running: bool, limit: int = 500) -> list[PGGoal]:
        """Goals with comparable text for recall (mirrors SQLite). Finished set
        is the written vocabulary done/blocked/cancelled, not the never-written
        succeeded/failed the old query used."""
        conds = ["(COALESCE(title, '') != '' OR COALESCE(description, '') != '')"]
        params: list = []
        if not include_running:
            conds.insert(0, "status IN ('done', 'blocked', 'cancelled')")
        frag, fparams = _tenant_scope()
        if frag:
            conds.append(frag)
            params += fparams
        params.append(limit)
        with self._tx() as cur:
            cur.execute(
                "SELECT id, parent_id, title, description, status, created_at, "
                "updated_at, deadline, result FROM goals WHERE "
                + " AND ".join(conds)
                + " ORDER BY updated_at DESC LIMIT %s",
                tuple(params),
            )
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def subgoals(self, parent_id: int, limit: int = 50) -> list[PGGoal]:
        frag, fparams = _tenant_scope()
        sql = (
            "SELECT id, parent_id, title, description, status, created_at, "
            "updated_at, deadline, result FROM goals WHERE parent_id = %s"
        )
        params: list = [parent_id]
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY created_at ASC LIMIT %s"
        params.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [PGGoal(*r) for r in rows]

    def reclaim_orphan_goals(self, *, max_age_seconds: float = 60.0) -> int:
        """Mark stale active/pending goals as 'blocked' after a crash.

        Called on startup to recover from SIGKILL/OOM mid-run. Only rows whose
        ``updated_at`` is at least ``max_age_seconds`` old qualify, so a goal
        being driven live in a sibling process isn't reclaimed. Mirrors the
        SQLite WorldModel (kernel calls this on dashboard/serve startup).
        Returns the number of rows reclaimed.
        """
        cutoff = time.time() - max_age_seconds
        now = time.time()
        frag, fparams = _tenant_scope()
        sql = (
            "UPDATE goals SET status = 'blocked', "
            "result = COALESCE(result, '') || ' [process restarted mid-run]', "
            "updated_at = %s "
            "WHERE status IN ('active', 'pending') AND updated_at < %s"
        )
        params: list = [now, cutoff]
        if frag:
            sql += " AND " + frag
            params += fparams
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
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

    def update_episode_spend(
        self,
        episode_id: int,
        cost_dollars: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: int = 0,
    ) -> None:
        """Mirror in-flight spend onto a live (not-yet-ended) episode row.

        Observability mirror only (see the SQLite backend's docstring): the
        `ended_at IS NULL` guard keeps it from clobbering `end_episode`.
        """
        with self._tx() as cur:
            cur.execute(
                "UPDATE episodes SET cost_dollars=%s, input_tokens=%s, "
                "output_tokens=%s, tool_calls=%s "
                "WHERE id=%s AND ended_at IS NULL",
                (cost_dollars, input_tokens, output_tokens, tool_calls,
                 episode_id),
            )

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

    def list_episodes(self, limit: int = 50, goal_id: int | None = None) -> list:
        from ..world_model import EpisodeSpend
        cols = (
            "e.id, e.goal_id, e.started_at, e.ended_at, e.outcome, "
            "COALESCE(e.cost_dollars, 0), COALESCE(e.input_tokens, 0), "
            "COALESCE(e.output_tokens, 0), COALESCE(e.tool_calls, 0)"
        )
        frag, fparams = _tenant_scope("g.tenant_id")
        conds: list[str] = []
        params: list = []
        table = "episodes e"
        if frag:
            table += " JOIN goals g ON g.id = e.goal_id"
        if goal_id is not None:
            conds.append("e.goal_id = %s")
            params.append(goal_id)
        if frag:
            conds.append(frag)
            params += fparams
        sql = f"SELECT {cols} FROM {table}"
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY e.started_at DESC LIMIT %s"
        params.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [EpisodeSpend(*r) for r in rows]

    def total_spend(self) -> dict[str, float]:
        frag, params = _tenant_scope("g.tenant_id")
        table = "episodes e"
        if frag:
            table += " JOIN goals g ON g.id = e.goal_id"
        sql = (
            "SELECT COALESCE(SUM(e.cost_dollars), 0), COALESCE(SUM(e.input_tokens), 0), "
            "COALESCE(SUM(e.output_tokens), 0), COUNT(*) "
            f"FROM {table} WHERE e.ended_at IS NOT NULL"
        )
        if frag:
            sql += " AND " + frag
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
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
        frag, fparams = _tenant_scope("g.tenant_id")
        table = "goal_events ge"
        if frag:
            table += " JOIN goals g ON g.id = ge.goal_id"
        sql = (
            "SELECT ge.id, ge.goal_id, ge.agent, ge.kind, ge.content, ge.ts "
            f"FROM {table} WHERE ge.goal_id=%s AND ge.id > %s"
        )
        params: list = [goal_id, since_id]
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY ge.id ASC LIMIT %s"
        params.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [GoalEvent(*r) for r in rows]

    def recent_goal_events(self, goal_id: int, limit: int = 200) -> list:
        from ..world_model import GoalEvent
        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, agent, kind, content, ts FROM ("
                "SELECT id, goal_id, agent, kind, content, ts FROM goal_events "
                "WHERE goal_id=%s ORDER BY id DESC LIMIT %s"
                ") recent ORDER BY id ASC",
                (goal_id, limit),
            )
            rows = cur.fetchall()
        return [GoalEvent(*r) for r in rows]

    # ----- facts (global key/value memory) -----

    def upsert_fact(self, key: str, value: str, episode_id: int | None = None) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO facts(key, value, source_episode_id, updated_at, tenant_id) "
                "VALUES(%s, %s, %s, %s, %s) "
                "ON CONFLICT ((COALESCE(tenant_id, '')), key) DO UPDATE SET "
                "value = EXCLUDED.value, "
                "source_episode_id = EXCLUDED.source_episode_id, "
                "updated_at = EXCLUDED.updated_at",
                (key, value, episode_id, time.time(), _active_tenant()),
            )

    def get_facts(self) -> dict[str, str]:
        frag, params = _tenant_scope()
        sql = "SELECT key, value FROM facts"
        if frag:
            sql += " WHERE " + frag
        sql += " ORDER BY updated_at DESC"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
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

    @staticmethod
    def _like_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def get_fact(self, key: str) -> str | None:
        frag, params = _tenant_scope()
        sql = "SELECT value FROM facts WHERE key = %s"
        p: list = [key]
        if frag:
            sql += " AND " + frag
            p += params
        sql += " LIMIT 1"
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            row = cur.fetchone()
        return row[0] if row else None

    def delete_fact(self, key: str) -> int:
        frag, params = _tenant_scope()
        sql = "DELETE FROM facts WHERE key = %s"
        p: list = [key]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            return cur.rowcount

    def list_facts(self, key_prefix: str, limit: int = 50) -> list[tuple[str, int]]:
        like = self._like_escape(key_prefix) + "%"
        frag, params = _tenant_scope()
        sql = "SELECT key, length(value) AS sz FROM facts WHERE key LIKE %s ESCAPE '\\'"
        p: list = [like]
        if frag:
            sql += " AND " + frag
            p += params
        sql += " ORDER BY updated_at DESC LIMIT %s"
        p.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            rows = cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    def search_facts(
        self, key_prefix: str, query: str, limit: int = 50,
    ) -> list[tuple[str, str]]:
        pfx = self._like_escape(key_prefix) + "%"
        q = "%" + self._like_escape(query) + "%"
        frag, params = _tenant_scope()
        sql = (
            "SELECT key, value FROM facts WHERE key LIKE %s ESCAPE '\\' "
            "AND (key LIKE %s ESCAPE '\\' OR value LIKE %s ESCAPE '\\')"
        )
        p: list = [pfx, q, q]
        if frag:
            sql += " AND " + frag
            p += params
        sql += " ORDER BY updated_at DESC LIMIT %s"
        p.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            rows = cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    # ----- questions (ask_user / human-in-the-loop) -----

    def ask(self, question: str, goal_id: int | None = None) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO questions(goal_id, question, asked_at) "
                "VALUES(%s, %s, %s) RETURNING id",
                (goal_id, question, time.time()),
            )
            row = cur.fetchone()
        return int(row[0])

    def answer(self, question_id: int, answer: str) -> bool:
        """Record an answer. Returns False if no question has that id, so a
        typo'd id is flagged instead of reported as a false success."""
        with self._tx() as cur:
            cur.execute(
                "UPDATE questions SET answer = %s, answered_at = %s WHERE id = %s",
                (answer, time.time(), question_id),
            )
            affected = cur.rowcount
        return affected > 0

    def open_questions(self, goal_id: int | None = None) -> list:
        from ..world_model import Question
        cols = "id, goal_id, question, asked_at, answer, answered_at"
        with self._tx() as cur:
            if goal_id is not None:
                cur.execute(
                    f"SELECT {cols} FROM questions "
                    "WHERE answer IS NULL AND goal_id = %s ORDER BY id",
                    (goal_id,),
                )
            else:
                cur.execute(
                    f"SELECT {cols} FROM questions WHERE answer IS NULL ORDER BY id"
                )
            rows = cur.fetchall()
        return [Question(*r) for r in rows]

    def all_questions(self, goal_id: int) -> list:
        from ..world_model import Question
        with self._tx() as cur:
            cur.execute(
                "SELECT id, goal_id, question, asked_at, answer, answered_at "
                "FROM questions WHERE goal_id = %s ORDER BY id",
                (goal_id,),
            )
            rows = cur.fetchall()
        return [Question(*r) for r in rows]

    # ----- approvals (high-risk action consent queue) -----

    def create_approval(
        self,
        action: str,
        *,
        risk: str = "medium",
        scope: str | None = None,
        detail: str | None = None,
        provenance: str | None = None,
    ) -> int:
        """Park a high-risk action for out-of-band (dashboard) approval.

        ``provenance`` is trusted caller-supplied metadata for operator UIs; it
        is not inferred from ``detail`` (which may carry untrusted text)."""
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO approvals(action, risk, scope, detail, provenance, status, "
                "requested_at, tenant_id) VALUES(%s, %s, %s, %s, %s, 'pending', %s, %s) "
                "RETURNING id",
                (action, risk, scope, detail, provenance, time.time(), _active_tenant()),
            )
            row = cur.fetchone()
        return int(row[0])

    def get_approval(self, approval_id: int):
        from ..world_model import Approval
        frag, params = _tenant_scope()
        sql = (
            "SELECT id, action, risk, scope, detail, provenance, status, "
            "requested_at, decided_at, claimed_by, claimed_at, decided_by "
            "FROM approvals WHERE id = %s"
        )
        p: list = [approval_id]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            row = cur.fetchone()
        return Approval(*row) if row else None

    def pending_approvals(self) -> list:
        from ..world_model import Approval
        frag, params = _tenant_scope()
        sql = (
            "SELECT id, action, risk, scope, detail, provenance, status, "
            "requested_at, decided_at, claimed_by, claimed_at, decided_by "
            "FROM approvals WHERE status = 'pending'"
        )
        if frag:
            sql += " AND " + frag
        sql += " ORDER BY id"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [Approval(*r) for r in rows]

    def decide_approval(self, approval_id: int, status: str,
                        decided_by: str | None = None) -> bool:
        """Flip a pending approval to 'approved'/'denied'. Returns True only if a
        pending row transitioned (unknown id or already-decided -> False, so a
        double-click is a no-op). ``decided_by`` records which supervisor
        decided (collaborative supervision); None = legacy unattributed."""
        if status not in ("approved", "denied"):
            raise ValueError("status must be 'approved' or 'denied'")
        # Tenant-scope the write like get_approval/pending_approvals: the
        # dashboard approve/deny endpoints pass a raw URL id with no ownership
        # gate, so without this a tenant could decide another tenant's parked
        # high-risk action by enumerating ids it can't even see.
        frag, params = _tenant_scope()
        sql = (
            "UPDATE approvals SET status = %s, decided_at = %s, decided_by = %s "
            "WHERE id = %s AND status = 'pending'"
        )
        p: list = [status, time.time(), decided_by, approval_id]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            affected = cur.rowcount
        return affected > 0

    def claim_approval(self, approval_id: int, principal: str) -> bool:
        """Atomically claim a pending approval (collaborative supervision).
        Mirrors SQLite: pending + unclaimed-or-mine; tenant-scoped."""
        principal = (principal or "").strip()
        if not principal:
            raise ValueError("principal is required to claim an approval")
        frag, params = _tenant_scope()
        sql = (
            "UPDATE approvals SET claimed_by = %s, claimed_at = %s "
            "WHERE id = %s AND status = 'pending' "
            "AND (claimed_by IS NULL OR claimed_by = %s)"
        )
        p: list = [principal, time.time(), approval_id, principal]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            affected = cur.rowcount
        return affected > 0

    def release_approval(self, approval_id: int, principal: str) -> bool:
        """Release a claim you hold (pending rows only); tenant-scoped."""
        principal = (principal or "").strip()
        if not principal:
            raise ValueError("principal is required to release an approval")
        frag, params = _tenant_scope()
        sql = (
            "UPDATE approvals SET claimed_by = NULL, claimed_at = NULL "
            "WHERE id = %s AND status = 'pending' AND claimed_by = %s"
        )
        p: list = [approval_id, principal]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            affected = cur.rowcount
        return affected > 0

    # ----- conversations / turns (multi-turn channel memory) -----

    def get_or_create_conversation(self, channel: str, user_id: str):
        """Idempotent per (channel, user_id); bumps last_seen each call so
        prune_conversations can retire idle ones. Mirrors SQLite."""
        from ..world_model import Conversation
        now = time.time()
        tenant = _active_tenant()
        frag, params = _tenant_scope()
        sel = (
            "SELECT id, channel, user_id, created_at, last_seen "
            "FROM conversations WHERE channel = %s AND user_id = %s"
        )
        sp: list = [channel, user_id]
        if frag:
            sel += " AND " + frag
            sp += params
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO conversations(channel, user_id, created_at, last_seen, tenant_id) "
                "VALUES(%s, %s, %s, %s, %s) "
                "ON CONFLICT ((COALESCE(tenant_id, '')), channel, user_id) "
                "DO UPDATE SET last_seen = EXCLUDED.last_seen",
                (channel, user_id, now, now, tenant),
            )
            cur.execute(sel, tuple(sp))
            row = cur.fetchone()
        return Conversation(*row)

    def append_turn(
        self, conversation_id: int, role: str, content: str,
        goal_id: int | None = None,
    ) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO turns(conversation_id, goal_id, role, content, ts) "
                "VALUES(%s, %s, %s, %s, %s) RETURNING id",
                (conversation_id, goal_id, role, content, time.time()),
            )
            return int(cur.fetchone()[0])

    def recent_turns(self, conversation_id: int, limit: int = 20) -> list:
        """Most recent N turns in chronological (ascending) order, ready to feed
        into a chat-format prompt. Mirrors SQLite."""
        from ..world_model import Turn
        with self._tx() as cur:
            cur.execute(
                "SELECT id, conversation_id, goal_id, role, content, ts FROM turns "
                "WHERE conversation_id = %s ORDER BY id DESC LIMIT %s",
                (conversation_id, limit),
            )
            rows = cur.fetchall()
        return list(reversed([Turn(*r) for r in rows]))

    def list_conversations(self, channel: str | None = None) -> list:
        from ..world_model import Conversation
        frag, params = _tenant_scope()
        sql = "SELECT id, channel, user_id, created_at, last_seen FROM conversations"
        conds: list[str] = []
        p: list = []
        if channel:
            conds.append("channel = %s")
            p.append(channel)
        if frag:
            conds.append(frag)
            p += params
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY last_seen DESC"
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            rows = cur.fetchall()
        return [Conversation(*r) for r in rows]

    def prune_conversations(self, idle_for_seconds: float = 90 * 24 * 3600) -> int:
        """Delete conversations idle for N seconds and their turns. Turns first
        (no ON DELETE CASCADE). Returns conversations removed. Mirrors SQLite."""
        cutoff = time.time() - idle_for_seconds
        with self._tx() as cur:
            cur.execute(
                "DELETE FROM turns WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE last_seen < %s)",
                (cutoff,),
            )
            cur.execute("DELETE FROM conversations WHERE last_seen < %s", (cutoff,))
            return cur.rowcount

    def erase_conversations(self, conversation_ids: list[int]) -> tuple[set[int], list[str], int]:
        """Erase conversations and goal-scoped rows for GDPR deletion.

        This is the Postgres equivalent of the CLI's SQLite cascade: gather all
        goals referenced by the selected conversations' turns, expand through
        subgoals, collect attachment paths for post-commit unlinking, then
        delete the database rows in one transaction using psycopg/Postgres SQL.
        Returns ``(goal_ids, attachment_paths, removed_turns)``.
        """
        if not conversation_ids:
            return set(), [], 0

        conv_ids = [int(cid) for cid in conversation_ids]
        with self._tx() as cur:
            cur.execute(
                "SELECT DISTINCT goal_id FROM turns "
                "WHERE conversation_id = ANY(%s) AND goal_id IS NOT NULL",
                (conv_ids,),
            )
            root_goal_ids = [int(row[0]) for row in cur.fetchall()]

            goal_ids: set[int] = set()
            if root_goal_ids:
                cur.execute(
                    """
                    WITH RECURSIVE goal_tree(id) AS (
                        SELECT id FROM goals WHERE id = ANY(%s)
                        UNION
                        SELECT g.id FROM goals g
                        JOIN goal_tree gt ON g.parent_id = gt.id
                    )
                    SELECT id FROM goal_tree
                    """,
                    (root_goal_ids,),
                )
                goal_ids = {int(row[0]) for row in cur.fetchall()}

            attachment_paths: list[str] = []
            gids = sorted(goal_ids)
            if gids:
                cur.execute("SELECT path FROM attachments WHERE goal_id = ANY(%s)", (gids,))
                attachment_paths = [str(row[0]) for row in cur.fetchall()]

            cur.execute("DELETE FROM turns WHERE conversation_id = ANY(%s)", (conv_ids,))
            removed_turns = cur.rowcount

            if gids:
                cur.execute("DELETE FROM goal_events WHERE goal_id = ANY(%s)", (gids,))
                cur.execute("DELETE FROM messages WHERE goal_id = ANY(%s)", (gids,))
                cur.execute("DELETE FROM questions WHERE goal_id = ANY(%s)", (gids,))
                cur.execute("DELETE FROM attachments WHERE goal_id = ANY(%s)", (gids,))
                cur.execute(
                    "DELETE FROM facts WHERE source_episode_id IN "
                    "(SELECT id FROM episodes WHERE goal_id = ANY(%s))",
                    (gids,),
                )
                cur.execute("DELETE FROM episodes WHERE goal_id = ANY(%s)", (gids,))
                cur.execute("DELETE FROM processed_messages WHERE goal_id = ANY(%s)", (gids,))
                # Postgres self-referential FKs are checked per statement by
                # default, unlike the SQLite path that defers FK checks for the
                # transaction. Break edges inside the soon-to-be-deleted tree so
                # a single goal DELETE cannot fail on parent_id references.
                cur.execute("UPDATE goals SET parent_id = NULL WHERE parent_id = ANY(%s)", (gids,))
                cur.execute("DELETE FROM goals WHERE id = ANY(%s)", (gids,))

            cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (conv_ids,))

        return goal_ids, attachment_paths, removed_turns

    # ----- messages (goal-scoped log + full-text search) -----

    def append_message(self, goal_id: int, role: str, content: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO messages(goal_id, role, content, ts) "
                "VALUES(%s, %s, %s, %s)",
                (goal_id, role, content, time.time()),
            )

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over message content, most-recent first.

        Uses Postgres FTS (plainto_tsquery) rather than SQLite's FTS5.
        plainto_tsquery parses arbitrary natural-language input safely — it
        ignores operators, so an unbalanced quote / leading `*` / `-` can't
        raise a syntax error (the PG analog to the SQLite quoting fix)."""
        if not query or not query.strip():
            return []
        cols = ["id", "goal_id", "role", "content", "ts"]
        select_cols = [f"m.{c}" for c in cols]
        frag, fparams = _tenant_scope("g.tenant_id")
        table = "messages m"
        if frag:
            table += " JOIN goals g ON g.id = m.goal_id"
        sql = (
            f"SELECT {', '.join(select_cols)} FROM {table} "
            "WHERE to_tsvector('english', m.content) @@ plainto_tsquery('english', %s)"
        )
        params: list = [query]
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY m.ts DESC LIMIT %s"
        params.append(limit)
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [dict(zip(cols, r, strict=False)) for r in rows]

    # ----- attachments -----

    def add_attachment(
        self, goal_id: int, filename: str, mime: str, size_bytes: int,
        sha256: str, path: str,
    ) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO attachments"
                "(goal_id, filename, mime, size_bytes, sha256, path, created_at) "
                "VALUES(%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (goal_id, filename, mime, size_bytes, sha256, path, time.time()),
            )
            return int(cur.fetchone()[0])

    def list_attachments(self, goal_id: int) -> list:
        from ..world_model import Attachment
        frag, fparams = _tenant_scope("g.tenant_id")
        table = "attachments a"
        if frag:
            table += " JOIN goals g ON g.id = a.goal_id"
        sql = (
            "SELECT a.id, a.goal_id, a.filename, a.mime, a.size_bytes, a.sha256, "
            f"a.path, a.created_at FROM {table} WHERE a.goal_id = %s"
        )
        params: list = [goal_id]
        if frag:
            sql += " AND " + frag
            params += fparams
        sql += " ORDER BY a.id"
        with self._tx() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [Attachment(*r) for r in rows]

    # ----- channel dedup (inbound-message idempotency) -----

    def mark_message_processed(
        self, channel: str, external_id: str, goal_id: int | None = None,
    ) -> bool:
        """Record an inbound message as processed; idempotent. Returns True on
        first-write (caller should run the goal), False on duplicate (caller
        returns 200 without re-running). Mirrors SQLite — protects against
        Twilio/iMessage webhook retries producing N goals + N spends."""
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO processed_messages(channel, external_id, goal_id, seen_at, tenant_id) "
                "VALUES(%s, %s, %s, %s, %s) "
                "ON CONFLICT ((COALESCE(tenant_id, '')), channel, external_id) DO NOTHING",
                (channel, external_id, goal_id, time.time(), _active_tenant()),
            )
            # rowcount is 1 on insert, 0 when the conflict skipped it.
            return cur.rowcount == 1

    def is_processed_message(self, channel: str, external_id: str) -> bool:
        frag, params = _tenant_scope()
        sql = "SELECT 1 FROM processed_messages WHERE channel = %s AND external_id = %s"
        p: list = [channel, external_id]
        if frag:
            sql += " AND " + frag
            p += params
        sql += " LIMIT 1"
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            return cur.fetchone() is not None

    def lookup_processed_message(self, channel: str, external_id: str) -> int | None:
        """goal_id for an already-processed message, or None if unseen.
        Distinguishes 'no row' (None) from 'row exists but goal_id null' (0),
        mirroring SQLite."""
        frag, params = _tenant_scope()
        sql = "SELECT goal_id FROM processed_messages WHERE channel = %s AND external_id = %s"
        p: list = [channel, external_id]
        if frag:
            sql += " AND " + frag
            p += params
        with self._tx() as cur:
            cur.execute(sql, tuple(p))
            row = cur.fetchone()
        if row is None:
            return None
        return row[0] if row[0] is not None else 0

    # ----- pruning -----

    def prune_goal_events(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        cutoff = time.time() - older_than_seconds
        with self._tx() as cur:
            cur.execute("DELETE FROM goal_events WHERE ts < %s", (cutoff,))
            return cur.rowcount

    def prune_processed_messages(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        cutoff = time.time() - older_than_seconds
        with self._tx() as cur:
            cur.execute("DELETE FROM processed_messages WHERE seen_at < %s", (cutoff,))
            return cur.rowcount

    @property
    def schema_version(self) -> int:
        """Schema version, for parity with SQLite WorldModel.schema_version
        (read as a property by health.py + audit events). Constant because the
        PG schema is applied idempotently rather than version-stepped."""
        return _PG_SCHEMA_VERSION

    # ----- close -----

    def close(self) -> None:
        try:
            if self._pool is not None:
                self._pool.close()
            elif self.conn is not None:
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
