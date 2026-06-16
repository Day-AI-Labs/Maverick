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
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".maverick" / "world.db"
SCHEMA_VERSION = 18
DEFAULT_BUSY_TIMEOUT_MS = 5000
WAL_SWITCH_BUSY_TIMEOUT_MS = 50
WAL_SWITCH_RETRY_SECONDS = 5.0


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
    result TEXT,
    owner TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_goals_status     ON goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_updated_at ON goals(updated_at);

CREATE TABLE IF NOT EXISTS goal_origins (
    goal_id INTEGER PRIMARY KEY REFERENCES goals(id),
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goal_origins_ref ON goal_origins(kind, ref);

-- v16 deliverable sign-off: a human's certify/reject decision on a finished,
-- gated deliverable (the review a pack's output-contract gate calls for). One
-- authoritative current decision per goal; the note is encrypted at rest like
-- other free-text. This is the governed hand-off: agents draft, humans certify.
CREATE TABLE IF NOT EXISTS signoffs (
    goal_id INTEGER PRIMARY KEY REFERENCES goals(id),
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL DEFAULT '',
    note TEXT,
    created_at REAL NOT NULL
);

-- v18 artifacts: versioned, kind-tagged deliverable artifacts a goal produces
-- (markdown / code / table / text), distinct from the single goal.result blob.
-- Re-emitting the same (goal_id, title) appends a new version; title + content
-- are encrypted at rest like other agent output. The render kind drives how the
-- dashboard presents it.
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    kind TEXT NOT NULL DEFAULT 'text',
    title TEXT,
    content TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_goal ON artifacts(goal_id);

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
    -- v17 Memory Guard provenance (plaintext metadata; the value stays sealed).
    -- source = who authored this fact; trust_tier = maverick.memory_guard.TrustTier
    -- (3=first-party/operator default ... 0=external/untrusted); sensitivity label.
    source TEXT NOT NULL DEFAULT '',
    trust_tier INTEGER NOT NULL DEFAULT 3,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    UNIQUE(key)
);

-- v17 temporal memory: a bitemporal history of every fact value. `facts` keeps
-- the single CURRENT value (UNIQUE(key)); this table records each value's
-- validity window so "what did we believe on date X, and why" is answerable --
-- non-destructive evolution instead of overwrite. `value` is sealed at rest like
-- facts.value; the window/provenance columns are plaintext so they stay queryable
-- under encryption. Only written when [memory] temporal is enabled.
CREATE TABLE IF NOT EXISTS fact_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_episode_id INTEGER REFERENCES episodes(id),
    valid_from REAL NOT NULL,
    valid_to REAL,
    source TEXT NOT NULL DEFAULT '',
    trust_tier INTEGER NOT NULL DEFAULT 3,
    sensitivity TEXT NOT NULL DEFAULT 'internal'
);

CREATE INDEX IF NOT EXISTS idx_fact_history_key ON fact_history(key, valid_from);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    question TEXT NOT NULL,
    asked_at REAL NOT NULL,
    answer TEXT,
    answered_at REAL
);

-- v9 approval queue: high-risk actions parked by safety.consent in
-- 'dashboard' mode. The consent path inserts a 'pending' row and polls
-- status; the dashboard /approvals page flips it to approved/denied.
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    risk TEXT NOT NULL DEFAULT 'medium',
    scope TEXT,
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at REAL NOT NULL,
    decided_at REAL,
    claimed_by TEXT,
    claimed_at REAL,
    decided_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, id);

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

-- External-content FTS5 requires the delete/update triggers too, or the
-- shadow index drifts out of sync with `messages` on any DELETE/UPDATE
-- (purge already deletes messages), leaving search matching stale/missing rows.
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES('delete', old.id, old.content);
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
    # v11: per-goal owner principal for multi-user dashboard authz (owner-scoped
    # reads/mutations). Legacy goals get '' (treated as unowned -> admin-only).
    11: ["ALTER TABLE goals ADD COLUMN owner TEXT NOT NULL DEFAULT ''"],
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
    # v9 approval queue: the approvals table + its status index are in
    # SCHEMA (idempotent CREATE). Listed here so existing DBs bump the
    # version and pick them up on next open, matching the goal_events /
    # conversations / attachments migration pattern above.
    9: [],
    # v10: backfill the messages_fts index. The FTS table + its triggers only
    # index FUTURE writes, so a DB whose messages predate the index (created
    # before messages_fts shipped) carried unindexed history that
    # search_messages() silently missed. Rebuild once on upgrade -- a cheap
    # no-op on a DB that's already fully indexed.
    10: ["INSERT INTO messages_fts(messages_fts) VALUES('rebuild')"],
    # v12: trusted approval provenance. Do not infer operator-visible source
    # labels from the free-form detail text, which can contain model-, user-,
    # or remote-server-controlled content.
    12: ["ALTER TABLE approvals ADD COLUMN provenance TEXT"],
    # v13 collaborative supervision: approval claiming (so two supervisors
    # don't double-handle the same pending approval) + decided_by attribution.
    13: [
        "ALTER TABLE approvals ADD COLUMN claimed_by TEXT",
        "ALTER TABLE approvals ADD COLUMN claimed_at REAL",
        "ALTER TABLE approvals ADD COLUMN decided_by TEXT",
    ],
    # v14 department attribution: the domain pack a goal ran as ('' = generic
    # orchestrator). Exact success-side attribution for the learning loops
    # (dreaming, role stats, budget priors) instead of lexical matching.
    14: ["ALTER TABLE goals ADD COLUMN domain TEXT NOT NULL DEFAULT ''"],
    # v15 automation provenance: the goal_origins table (which schedule/trigger
    # spawned a goal) is in SCHEMA (idempotent CREATE). Listed here so existing
    # DBs bump the version and pick it up on next open, matching the v9 pattern.
    15: [],
    # v16 deliverable sign-off: the signoffs table is in SCHEMA (idempotent
    # CREATE); listed here so existing DBs bump the version on next open.
    16: [],
    # v17 governed/temporal memory: provenance + trust tier on the live fact row
    # (Memory Guard), and the bitemporal fact_history table + its index (in SCHEMA
    # as idempotent CREATE) for non-destructive fact evolution. The ALTERs add the
    # provenance columns to existing DBs; legacy facts backfill to trust_tier=3
    # (first-party) so the guard never retroactively hides already-trusted memory.
    17: [
        "ALTER TABLE facts ADD COLUMN source TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE facts ADD COLUMN trust_tier INTEGER NOT NULL DEFAULT 3",
        "ALTER TABLE facts ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'internal'",
    ],
    # v18 artifacts: the artifacts table + its index are in SCHEMA (idempotent
    # CREATE); listed here so existing DBs bump the version on next open.
    18: [],
}


@dataclass
class Goal:
    id: int
    parent_id: int | None
    title: str
    description: str | None
    status: str
    created_at: float
    updated_at: float
    deadline: float | None
    result: str | None
    owner: str = ""
    domain: str = ""


@dataclass
class Question:
    id: int
    goal_id: int | None
    question: str
    asked_at: float
    answer: str | None
    answered_at: float | None


@dataclass
class Approval:
    id: int
    action: str
    risk: str
    scope: str | None
    detail: str | None
    provenance: str | None
    status: str
    requested_at: float
    decided_at: float | None
    claimed_by: str | None = None
    claimed_at: float | None = None
    decided_by: str | None = None


@dataclass
class EpisodeSpend:
    id: int
    goal_id: int
    started_at: float
    ended_at: float | None
    outcome: str | None
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
    goal_id: int | None
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


@dataclass
class FactVersion:
    """One historical value of a fact (see :meth:`WorldModel.fact_history`).

    ``valid_to is None`` marks the value that is still current. The window is
    transaction time: ``valid_from`` is when the value became current and
    ``valid_to`` is when it was superseded or deleted."""
    value: str | None
    valid_from: float
    valid_to: float | None
    source: str = ""
    trust_tier: int = 3
    sensitivity: str = "internal"


def _temporal_memory_enabled() -> bool:
    """Whether to keep a bitemporal ``fact_history`` (validity windows) on every
    fact change. OFF by default -- the live-value path is byte-identical when off
    (upsert overwrites, no history rows). Turn on with ``MAVERICK_TEMPORAL_MEMORY=1``
    or ``[memory] temporal = true`` for non-destructive fact evolution and
    ``get_fact(..., as_of=...)`` / ``fact_history(...)`` queries."""
    if (os.environ.get("MAVERICK_TEMPORAL_MEMORY") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        return bool(load_config().get("memory", {}).get("temporal", False))
    except Exception:  # pragma: no cover -- config never blocks a write
        return False


def _enc_field(text: str | None) -> str | None:
    """Seal a sensitive text field for storage when at-rest encryption is on.

    Fail-closed: if encryption is enabled but the crypto backend is missing,
    this raises (via ``seal_to_str``) rather than silently storing plaintext.
    Returns the value unchanged when encryption is off (and for ``None``)."""
    if text is None:
        return text
    from .crypto_at_rest import at_rest_enabled, seal_to_str
    return seal_to_str(text) if at_rest_enabled() else text


# Returned in strict mode when a sealed column holds an unsealed value (legacy
# plaintext that wasn't migrated, or tampering) -- never the real plaintext.
_UNSEALED_WITHHELD = "‹withheld: unsealed value in an encrypted store›"


def _dec_field(text: str | None) -> str | None:
    """Unseal a stored field from a sealed column when at-rest encryption is on.

    When encryption is disabled, fields are raw plaintext (which may legitimately
    begin with the public seal marker), so they pass through untouched.

    When encryption is on but the stored value is NOT sealed, it is either
    pre-migration legacy plaintext or tampering. By default it is passed through
    (so a not-yet-migrated store stays readable) with a warning; under
    :func:`strict_at_rest` it is withheld and logged as an integrity failure --
    closing the read-side plaintext-passthrough hole.
    """
    if text is None:
        return text
    from .crypto_at_rest import (
        at_rest_enabled,
        is_sealed_str,
        strict_at_rest,
        unseal_from_str,
    )
    if not at_rest_enabled():
        return text
    if is_sealed_str(text):
        return unseal_from_str(text)
    if strict_at_rest():
        log.error("at-rest strict: withholding an unsealed value in a sealed column "
                  "(run 'maverick encryption migrate'; tampering if already migrated)")
        return _UNSEALED_WITHHELD
    log.warning("at-rest: unsealed value in a sealed column (pre-migration legacy or "
                "tampering); run 'maverick encryption migrate'")
    return text


def _row_for(cls, d: dict) -> dict:
    """Keep only the keys that ``cls`` (a dataclass) declares.

    A live ``world.db`` can carry columns written by a different schema
    version -- e.g. a build that added a ``domain`` column to ``goals``.
    ``cls(**dict(row))`` would then raise ``TypeError`` on that unknown column
    and 500 every page that lists the table. Dropping unmodelled columns keeps
    reads tolerant of schema skew in both directions.
    """
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in allowed}


def _question_from_row(row) -> Question:
    """Build a Question from a row, decrypting the sealed question/answer fields."""
    d = dict(row)
    d["question"] = _dec_field(d.get("question"))
    d["answer"] = _dec_field(d.get("answer"))
    return Question(**_row_for(Question, d))


def _goal_from_row(row) -> Goal:
    """Build a Goal from a row, decrypting the sealed content fields."""
    d = dict(row)
    d["title"] = _dec_field(d.get("title"))
    d["description"] = _dec_field(d.get("description"))
    if "result" in d:
        d["result"] = _dec_field(d.get("result"))
    return Goal(**_row_for(Goal, d))


def _goal_event_from_row(row) -> GoalEvent:
    """Build a GoalEvent from a row, decrypting the sealed content field."""
    d = dict(row)
    d["content"] = _dec_field(d.get("content"))
    return GoalEvent(**_row_for(GoalEvent, d))


def _episode_spend_from_row(row) -> EpisodeSpend:
    """Build an EpisodeSpend from a row, decrypting the sealed outcome field."""
    d = dict(row)
    if "outcome" in d:
        d["outcome"] = _dec_field(d.get("outcome"))
    return EpisodeSpend(**_row_for(EpisodeSpend, d))


def _approval_from_row(row) -> Approval:
    """Build an Approval from a row, decrypting the sealed action/scope/detail."""
    d = dict(row)
    d["action"] = _dec_field(d.get("action"))
    d["scope"] = _dec_field(d.get("scope"))
    d["detail"] = _dec_field(d.get("detail"))
    return Approval(**_row_for(Approval, d))


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
        # Create the DB file 0o600 BEFORE sqlite opens it: connect() would
        # otherwise create it at the umask (often 0644) for a window before the
        # chmod below, briefly exposing all conversation content to co-tenants.
        if str(path) != ":memory:" and not path.exists():
            try:
                _fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(_fd)
            except OSError:
                pass
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.conn.row_factory = sqlite3.Row
        # Arm a short busy handler BEFORE switching journal mode: switching to
        # WAL needs a brief exclusive lock, and when a second connection opens
        # the same DB concurrently (the dashboard and the agent each open one)
        # the switch can surface "database is locked" instead of waiting unless
        # busy_timeout is already set. Keep this timeout small because it is
        # paid on every retry below; restore the normal write timeout after WAL
        # is enabled.
        self.conn.execute(f"PRAGMA busy_timeout = {WAL_SWITCH_BUSY_TIMEOUT_MS}")
        # WAL must be set before any other operation that creates pages. The
        # switch can still race a same-process connection -- SQLITE_LOCKED
        # bypasses the busy handler -- so retry briefly (<=5s) on a locked DB.
        deadline = time.monotonic() + WAL_SWITCH_RETRY_SECONDS
        while True:
            try:
                self.conn.execute("PRAGMA journal_mode = WAL")
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower():
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(0.05, remaining))
        self.conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
        # WAL/SHM sidecars hold uncommitted conversation content; lock them to
        # 0o600 too (best-effort -- they may not exist until the first write,
        # so this is re-attempted; the 0o700 parent dir covers the gap).
        if str(path) != ":memory:":
            for _suffix in ("-wal", "-shm"):
                try:
                    os.chmod(path.parent / (path.name + _suffix), 0o600)
                except OSError:
                    pass
        # synchronous=NORMAL under WAL is safe + much faster than FULL.
        self.conn.execute("PRAGMA synchronous = NORMAL")
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
        # The schema-setup writes (executescript + version row + migrations) can
        # surface SQLITE_LOCKED -- not SQLITE_BUSY -- when many connections in
        # the SAME process first-open a fresh DB simultaneously; the
        # busy_timeout handler doesn't cover SQLITE_LOCKED (same reason the WAL
        # switch above needs its own retry). The version-row insert is already
        # race-safe (atomic insert-if-empty in _init_schema_version), but
        # executescript/migrations can still lose the lock race -- observed in
        # CI as an intermittent "database is locked" on concurrent first-open.
        # The whole block is idempotent (CREATE TABLE IF NOT EXISTS, the
        # empty-table version insert, re-runnable migrations), so retry it
        # briefly on a transient lock.
        deadline = time.monotonic() + WAL_SWITCH_RETRY_SECONDS
        while True:
            try:
                self.conn.executescript(SCHEMA)
                self._init_schema_version()
                self._apply_migrations()
                self.conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower():
                    raise
                try:
                    self.conn.rollback()
                except sqlite3.Error:
                    pass
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(0.05, remaining))

    @contextlib.contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
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

    def _read_all(self, sql: str, params: tuple[Any, ...] = ()) -> list:
        """Run a read under the connection lock and eagerly fetch all rows.

        The single sqlite3 connection is shared across threads
        (``check_same_thread=False``), so under ``serve`` several goal
        threads read it concurrently with the writer. Without holding the
        same RLock ``_writing()`` uses, a read can run while another thread
        is mid-transaction on that connection and observe half-applied (or
        rolled-back) writes -- e.g. a goal could read a torn conversation
        context. Fetch INSIDE the lock and return the rows so the caller
        never touches the connection lock-free. The RLock is reentrant, so a
        read nested inside a write (or another read) on the same thread does
        not deadlock; WAL's concurrent-reader benefit is only across
        separate connections, so on one connection access must be
        serialised regardless.
        """
        with self._write_lock:
            return self.conn.execute(sql, params).fetchall()

    def _read_one(self, sql: str, params: tuple[Any, ...] = ()):
        """Single-row counterpart to :meth:`_read_all` (see its note)."""
        with self._write_lock:
            return self.conn.execute(sql, params).fetchone()

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
        now = time.time()
        marker = " [process restarted mid-run]"
        from .crypto_at_rest import at_rest_enabled
        with self._writing() as conn:
            if not at_rest_enabled():
                cur = conn.execute(
                    "UPDATE goals SET status = 'blocked', "
                    "result = COALESCE(result, '') || ?, "
                    "updated_at = ? "
                    "WHERE status IN ('active', 'pending') AND updated_at < ?",
                    (marker, now, cutoff),
                )
                return cur.rowcount
            # At-rest encryption on: `result` is sealed ciphertext. Appending the
            # marker in SQL would corrupt the ciphertext (unrecoverable on
            # decrypt) or write bare plaintext into a sealed column (tripped as
            # tampering). Append through the seal layer per row instead. The
            # set of stale orphans on startup is tiny, so the row-by-row cost
            # is negligible.
            rows = conn.execute(
                "SELECT id, result FROM goals "
                "WHERE status IN ('active', 'pending') AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                prior = _dec_field(row["result"]) or ""
                conn.execute(
                    "UPDATE goals SET status = 'blocked', result = ?, "
                    "updated_at = ? WHERE id = ?",
                    (_enc_field(prior + marker), now, row["id"]),
                )
            return len(rows)

    def _init_schema_version(self) -> None:
        # Fast path: an already-initialized DB only needs a read. WAL readers
        # never block a concurrent writer, so don't take a write lock on every
        # open -- a second connection opening mid-write would otherwise hit
        # "database is locked".
        row = self.conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        if row is not None:
            return
        # Fresh DB: seed the single row. Concurrent first-opens raced -- the
        # old check-then-insert keyed on version=1, but a *losing* connection
        # ran its INSERT only AFTER the winner had migrated its row up to
        # SCHEMA_VERSION, so version=1 was free again and it inserted a SECOND
        # row (the try/except only caught a PK collision). Two rows then made
        # the no-WHERE `UPDATE schema_version SET version=?` in
        # _apply_migrations collide on the PK -- the intermittent fresh-open CI
        # flake. Guard on table-emptiness in one atomic statement: the WHERE
        # NOT EXISTS is re-checked under SQLite's single-writer lock, so a
        # loser that saw an empty table above still inserts nothing once the
        # winner's row is committed. At most one row, ever.
        self.conn.execute(
            "INSERT INTO schema_version(version) "
            "SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version)"
        )

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
    def create_goal(self, title: str, description: str = "", parent_id: int | None = None,
                    *, owner: str = "", domain: str = "") -> int:
        now = time.time()
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO goals(parent_id, title, description, status, "
                "created_at, updated_at, owner, domain) "
                "VALUES(?, ?, ?, 'pending', ?, ?, ?, ?)",
                (parent_id, _enc_field(title), _enc_field(description), now, now,
                 owner, domain or ""),
            )
            return cur.lastrowid

    def record_goal_origin(self, goal_id: int, kind: str, ref: str) -> None:
        """Record which automation spawned a goal, so the Automations page can
        show each automation's run history. ``kind`` is 'schedule' or 'trigger';
        ``ref`` is the stable schedule_id or trigger name. One row per goal."""
        with self._writing() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO goal_origins(goal_id, kind, ref, created_at) "
                "VALUES(?, ?, ?, ?)",
                (int(goal_id), str(kind), str(ref), time.time()),
            )

    def goals_for_origin(self, kind: str, ref: str, *, limit: int = 20) -> list[Goal]:
        """Goals an automation spawned, most-recent first. ``SELECT g.*`` (not
        ``*``) so goal_origins.created_at doesn't shadow goals.created_at."""
        rows = self._read_all(
            "SELECT g.* FROM goals g JOIN goal_origins o ON o.goal_id = g.id "
            "WHERE o.kind = ? AND o.ref = ? ORDER BY g.id DESC LIMIT ?",
            (str(kind), str(ref), max(1, int(limit))),
        )
        return [_goal_from_row(r) for r in rows]

    def origin_status_counts(self, kind: str, ref: str) -> dict[str, int]:
        """An automation's spawned-goal counts keyed by status (run summary)."""
        rows = self._read_all(
            "SELECT g.status AS status, COUNT(*) AS n FROM goals g "
            "JOIN goal_origins o ON o.goal_id = g.id "
            "WHERE o.kind = ? AND o.ref = ? GROUP BY g.status",
            (str(kind), str(ref)),
        )
        return {r["status"]: int(r["n"]) for r in rows}

    def record_signoff(self, goal_id: int, decision: str, *,
                       decided_by: str = "", note: str | None = None) -> None:
        """Record a human's certify/reject decision on a finished deliverable --
        the sign-off a pack's output gate calls for. One authoritative row per
        goal (a later decision replaces an earlier one); the note is encrypted
        at rest. ``decision`` is 'approved' or 'rejected'."""
        with self._writing() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO signoffs(goal_id, decision, decided_by, "
                "note, created_at) VALUES(?, ?, ?, ?, ?)",
                (int(goal_id), str(decision), str(decided_by or ""),
                 _enc_field(note), time.time()),
            )

    def signoff_for(self, goal_id: int) -> dict | None:
        """The current sign-off on a goal's deliverable, or ``None`` if it
        hasn't been reviewed yet."""
        row = self._read_one("SELECT * FROM signoffs WHERE goal_id = ?", (int(goal_id),))
        if not row:
            return None
        return {
            "goal_id": row["goal_id"], "decision": row["decision"],
            "decided_by": row["decided_by"], "note": _dec_field(row["note"]),
            "created_at": row["created_at"],
        }

    def signoffs_for_goals(self, goal_ids) -> dict[int, str]:
        """Map ``goal_id -> decision`` for a batch of goals (the persona inbox,
        so a signed-off deliverable drops out of the awaiting queue). Goals with
        no sign-off are simply absent."""
        ids = [int(g) for g in goal_ids]
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self._read_all(
            f"SELECT goal_id, decision FROM signoffs WHERE goal_id IN ({placeholders})",
            tuple(ids),
        )
        return {r["goal_id"]: r["decision"] for r in rows}

    def add_artifact(self, goal_id: int, kind: str, title: str, content: str) -> int:
        """Record an artifact a goal produced (markdown / code / table / text).
        Re-using the same ``(goal_id, title)`` appends the next version, so the
        UI can show history. ``title`` is a plaintext label (versioning keys on
        it); ``content`` is encrypted at rest like other agent output."""
        now = time.time()
        with self._writing() as conn:
            cur = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM artifacts WHERE goal_id = ? AND title = ?",
                (int(goal_id), title or ""),
            )
            version = int(cur.fetchone()[0]) + 1
            cur = conn.execute(
                "INSERT INTO artifacts(goal_id, kind, title, content, version, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (int(goal_id), str(kind or "text"), title or "",
                 _enc_field(content), version, now),
            )
            return int(cur.lastrowid)

    def artifacts_for_goal(self, goal_id: int) -> list[dict]:
        """Every artifact version for a goal, ordered by title then version."""
        rows = self._read_all(
            "SELECT id, goal_id, kind, title, content, version, created_at "
            "FROM artifacts WHERE goal_id = ? ORDER BY title, version",
            (int(goal_id),),
        )
        return [{"id": r["id"], "goal_id": r["goal_id"], "kind": r["kind"],
                 "title": r["title"] or "", "content": _dec_field(r["content"]) or "",
                 "version": r["version"], "created_at": r["created_at"]} for r in rows]

    def latest_artifacts(self, goal_id: int) -> list[dict]:
        """The latest version of each titled artifact, with a ``versions`` count
        (what the goal page shows; older versions are still in the table)."""
        by_title: dict[str, dict] = {}
        counts: dict[str, int] = {}
        for a in self.artifacts_for_goal(goal_id):  # title, version ascending
            by_title[a["title"]] = a
            counts[a["title"]] = counts.get(a["title"], 0) + 1
        return [{**a, "versions": counts[t]} for t, a in by_title.items()]

    def set_goal_domain(self, goal_id: int, domain: str) -> None:
        """Record the department (domain pack) a goal is running as.

        Plain-text column (pack names are operator-defined identifiers, not
        user content) so learning loops can filter without decrypting."""
        with self._writing() as conn:
            conn.execute(
                "UPDATE goals SET domain = ? WHERE id = ?",
                (domain or "", goal_id),
            )

    def set_goal_status(self, goal_id: int, status: str, result: str | None = None) -> None:
        with self._writing() as conn:
            conn.execute(
                "UPDATE goals SET status = ?, updated_at = ?, result = COALESCE(?, result) WHERE id = ?",
                (status, time.time(), _enc_field(result), goal_id),
            )

    def get_goal(self, goal_id: int) -> Goal | None:
        row = self._read_one("SELECT * FROM goals WHERE id = ?", (goal_id,))
        return _goal_from_row(row) if row else None

    def list_goals(
        self,
        status: str | None = None,
        *,
        owner: str | None = None,
        domain: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[Goal]:
        """List goals, optionally filtered + paginated.

        Defaults preserve historical behaviour (``limit=None`` returns
        all rows in ASC id order). Dashboard callers should pass a
        small ``limit`` to avoid loading every goal on every request;
        ``order='desc'`` lets the most-recent slice be fetched cheaply.
        ``domain`` scopes to one department (the pack a goal ran as) -- the
        ``domain`` column is plaintext, so it filters in SQL.
        """
        direction = "DESC" if order.lower() == "desc" else "ASC"
        sql = "SELECT * FROM goals"
        clauses: list[str] = []
        params: tuple[Any, ...] = ()
        if status:
            clauses.append("status = ?")
            params = params + (status,)
        if owner is not None:
            clauses.append("owner = ?")
            params = params + (owner,)
        if domain is not None:
            clauses.append("domain = ?")
            params = params + (domain,)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY id {direction}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + (max(1, int(limit)), max(0, int(offset)))
        rows = self._read_all(sql, params)
        return [_goal_from_row(r) for r in rows]

    def search_goals(
        self,
        query: str,
        *,
        owner: str | None = None,
        limit: int = 50,
        scan: int = 1000,
    ) -> list[Goal]:
        """Search across goals (runs) by text in title / description / result.

        Title and description are encrypted at rest, so a SQL ``LIKE`` can't
        match plaintext. We fetch a bounded window of the most-recent goals
        (``scan``), decrypt them via ``_goal_from_row``, and filter in Python on
        a case-insensitive substring match -- the same scan-then-decrypt shape
        as ``candidate_goals``. Owner-scoped like :meth:`list_goals`; returns up
        to ``limit`` matches, newest first.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        sql = (
            "SELECT id, parent_id, title, description, status, created_at, "
            "updated_at, deadline, result, owner FROM goals"
        )
        params: tuple[Any, ...] = ()
        if owner is not None:
            sql += " WHERE owner = ?"
            params = (owner,)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params = params + (max(1, int(scan)),)
        rows = self._read_all(sql, params)
        out: list[Goal] = []
        cap = max(1, int(limit))
        for r in rows:
            g = _goal_from_row(r)
            hay = " ".join(p for p in (g.title, g.description, g.result) if p).lower()
            if q in hay:
                out.append(g)
                if len(out) >= cap:
                    break
        return out

    def most_recent_goal(self) -> Goal | None:
        """Most-recently-updated goal regardless of status. Locked read."""
        row = self._read_one("SELECT * FROM goals ORDER BY updated_at DESC LIMIT 1")
        return _goal_from_row(row) if row else None

    def active_goal(self) -> Goal | None:
        row = self._read_one(
            "SELECT * FROM goals WHERE status IN ('active', 'blocked') ORDER BY updated_at DESC LIMIT 1"
        )
        return _goal_from_row(row) if row else None

    def inflight_goal(self) -> Goal | None:
        """Most-recently-updated goal still in flight (``active``/``pending``).

        Distinct from :meth:`active_goal` (which includes ``blocked``): the
        monitor wants the currently-running goal, not a stopped one. Locked.
        """
        row = self._read_one(
            "SELECT * FROM goals WHERE status IN ('active', 'pending') "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        return _goal_from_row(row) if row else None

    def candidate_goals(self, include_running: bool, limit: int = 500) -> list[Goal]:
        """Goals with comparable text, for cross-run recall. Locked read.

        ``include_running`` widens to in-flight goals too; otherwise only
        FINISHED ones. The terminal set is the vocabulary the orchestrator
        actually writes (``done``/``blocked``/``cancelled``) -- the old query
        filtered on ``succeeded``/``failed``, statuses that are never written,
        so it silently missed every failed (``blocked``) past goal.
        """
        text_clause = "(COALESCE(title, '') != '' OR COALESCE(description, '') != '')"
        if include_running:
            where = f"WHERE {text_clause}"
        else:
            where = f"WHERE status IN ('done', 'blocked', 'cancelled') AND {text_clause}"
        rows = self._read_all(
            "SELECT id, parent_id, title, description, status, created_at, "
            f"updated_at, deadline, result FROM goals {where} "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [_goal_from_row(r) for r in rows]

    def subgoals(self, parent_id: int, limit: int = 50) -> list[Goal]:
        """Immediate children of a goal, oldest first. Locked read."""
        rows = self._read_all(
            "SELECT id, parent_id, title, description, status, created_at, "
            "updated_at, deadline, result FROM goals WHERE parent_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (parent_id, limit),
        )
        return [_goal_from_row(r) for r in rows]

    # ----- episodes -----
    def start_episode(self, goal_id: int) -> int:
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO episodes(goal_id, started_at) VALUES(?, ?)",
                (goal_id, time.time()),
            )
            return cur.lastrowid

    def update_episode_spend(
        self,
        episode_id: int,
        cost_dollars: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: int = 0,
    ) -> None:
        """Mirror in-flight spend onto a LIVE (not-yet-ended) episode row.

        Read-side observability only: `maverick runs` / `maverick budget`
        read the episode row, which `end_episode` only writes when the run
        finishes -- so a long run showed `$0.00 / 0 tools` for minutes. The
        orchestrator calls this periodically (throttled) so those commands
        reflect accruing spend. Leaves `ended_at`/`outcome`/`summary`
        untouched, so the row still reads as 'running' and `total_spend`
        (which sums only ended episodes) is unaffected -- this is not a new
        billing path. The `ended_at IS NULL` guard means a late mirror write
        can never clobber the authoritative `end_episode` totals.
        """
        with self._writing() as conn:
            conn.execute(
                "UPDATE episodes SET cost_dollars = ?, input_tokens = ?, "
                "output_tokens = ?, tool_calls = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (cost_dollars, input_tokens, output_tokens, tool_calls,
                 episode_id),
            )

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
                (time.time(), _enc_field(summary), _enc_field(outcome), cost_dollars,
                 input_tokens, output_tokens, tool_calls, episode_id),
            )

    def list_episodes(
        self,
        limit: int = 50,
        goal_id: int | None = None,
    ) -> list[EpisodeSpend]:
        if goal_id is not None:
            rows = self._read_all(
                "SELECT id, goal_id, started_at, ended_at, outcome, "
                "COALESCE(cost_dollars, 0) AS cost_dollars, "
                "COALESCE(input_tokens, 0) AS input_tokens, "
                "COALESCE(output_tokens, 0) AS output_tokens, "
                "COALESCE(tool_calls, 0) AS tool_calls "
                "FROM episodes WHERE goal_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (goal_id, limit),
            )
        else:
            rows = self._read_all(
                "SELECT id, goal_id, started_at, ended_at, outcome, "
                "COALESCE(cost_dollars, 0) AS cost_dollars, "
                "COALESCE(input_tokens, 0) AS input_tokens, "
                "COALESCE(output_tokens, 0) AS output_tokens, "
                "COALESCE(tool_calls, 0) AS tool_calls "
                "FROM episodes ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
        return [_episode_spend_from_row(r) for r in rows]

    def total_spend(self) -> dict[str, float]:
        row = self._read_one(
            "SELECT COALESCE(SUM(cost_dollars), 0) AS dollars, "
            "COALESCE(SUM(input_tokens), 0) AS in_tok, "
            "COALESCE(SUM(output_tokens), 0) AS out_tok, "
            "COUNT(*) AS runs FROM episodes WHERE ended_at IS NOT NULL"
        )
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
                (goal_id, agent, kind, _enc_field(content), time.time()),
            )
            return cur.lastrowid

    def goal_events(self, goal_id: int, since_id: int = 0, limit: int = 200) -> list[GoalEvent]:
        rows = self._read_all(
            "SELECT id, goal_id, agent, kind, content, ts FROM goal_events "
            "WHERE goal_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (goal_id, since_id, limit),
        )
        return [_goal_event_from_row(r) for r in rows]

    def recent_goal_events(self, goal_id: int, limit: int = 200) -> list[GoalEvent]:
        """Return the latest goal events, preserving chronological order."""
        rows = self._read_all(
            "SELECT id, goal_id, agent, kind, content, ts FROM ("
            "SELECT id, goal_id, agent, kind, content, ts FROM goal_events "
            "WHERE goal_id = ? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (goal_id, limit),
        )
        return [_goal_event_from_row(r) for r in rows]

    def recent_event_contents(self, limit: int = 5000) -> list[str]:
        """Coordination-message bodies across all goals (newest first), the corpus
        the emergent-protocol codebook learns from. Read-only."""
        rows = self._read_all(
            "SELECT content FROM goal_events ORDER BY id DESC LIMIT ?", (int(limit),))
        return [r[0] for r in rows if r and r[0]]

    def prune_goal_events(self, older_than_seconds: float = 30 * 24 * 3600) -> int:
        """Delete goal_events rows older than N seconds. Returns rows removed."""
        cutoff = time.time() - older_than_seconds
        with self._writing() as conn:
            cur = conn.execute("DELETE FROM goal_events WHERE ts < ?", (cutoff,))
            return cur.rowcount

    # ----- facts -----
    def upsert_fact(
        self, key: str, value: str, episode_id: int | None = None,
        *, source: str = "", trust_tier: int = 3, sensitivity: str = "internal",
    ) -> None:
        """Write the current value of ``key``.

        ``source``/``trust_tier``/``sensitivity`` are Memory Guard provenance
        (see :mod:`maverick.memory_guard`); they default to first-party trust so
        existing internal callers are unaffected. When ``[memory] temporal`` is
        on, a *changed* value also appends a :class:`FactVersion` to
        ``fact_history`` and closes the prior open window -- non-destructive
        evolution. An unchanged value refreshes provenance without a new version.
        """
        now = time.time()
        enc = _enc_field(value)
        with self._writing() as conn:
            if _temporal_memory_enabled():
                prior = conn.execute(
                    "SELECT value FROM facts WHERE key = ? LIMIT 1", (key,),
                ).fetchone()
                changed = prior is None or _dec_field(prior[0]) != value
                if changed:
                    # Close the open window, then open a new one for this value:
                    # the prior value is preserved with the instant it stopped
                    # being current instead of being overwritten and lost.
                    conn.execute(
                        "UPDATE fact_history SET valid_to = ? "
                        "WHERE key = ? AND valid_to IS NULL",
                        (now, key),
                    )
                    conn.execute(
                        "INSERT INTO fact_history(key, value, source_episode_id, "
                        "valid_from, valid_to, source, trust_tier, sensitivity) "
                        "VALUES(?, ?, ?, ?, NULL, ?, ?, ?)",
                        (key, enc, episode_id, now, source, int(trust_tier),
                         sensitivity),
                    )
            conn.execute(
                "INSERT INTO facts(key, value, source_episode_id, updated_at, "
                "source, trust_tier, sensitivity) VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at, source = excluded.source, "
                "trust_tier = excluded.trust_tier, sensitivity = excluded.sensitivity",
                (key, enc, episode_id, now, source, int(trust_tier), sensitivity),
            )

    def get_facts(self, *, min_trust: int | None = None) -> dict[str, str]:
        """All current facts as ``{key: value}``, newest first.

        ``min_trust`` (Memory Guard trust-aware retrieval) drops facts whose
        ``trust_tier`` is below the floor so low-trust/poisoned memory never
        reaches the agent's standing brief. None = no filter (unchanged)."""
        if min_trust is not None:
            rows = self._read_all(
                "SELECT key, value FROM facts WHERE trust_tier >= ? "
                "ORDER BY updated_at DESC", (int(min_trust),),
            )
        else:
            rows = self._read_all(
                "SELECT key, value FROM facts ORDER BY updated_at DESC")
        return {r["key"]: _dec_field(r["value"]) for r in rows}

    def facts_matching(self, token: str) -> dict[str, str]:
        """Facts explicitly scoped to ``token`` by key prefix.

        Facts are global key/value pairs with no per-user attribution.  To
        avoid disclosing or deleting unrelated global facts, GDPR export/erase
        only considers facts whose key is deliberately namespaced as
        ``user:<token>:<name>``.  Values are never searched and arbitrary
        substrings are ignored because short/common user ids can otherwise
        match unrelated secrets or other users' data.
        """
        if not token:
            return {}
        prefix = f"user:{token}:"
        return {k: v for k, v in self.get_facts().items() if k.startswith(prefix)}

    def delete_facts_matching(self, token: str) -> list[str]:
        """Delete explicitly user-scoped facts (see :meth:`facts_matching`).

        Returns the keys removed so the caller can report exactly what was
        scrubbed.
        """
        keys = sorted(self.facts_matching(token).keys())
        if keys:
            ph = ",".join("?" * len(keys))
            with self._writing() as conn:
                conn.execute(f"DELETE FROM facts WHERE key IN ({ph})", keys)
        return keys

    @staticmethod
    def _like_escape(s: str) -> str:
        """Escape LIKE wildcards so a key/query is matched literally."""
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def get_fact(self, key: str, *, as_of: float | None = None) -> str | None:
        """Single fact value by exact key, or None. Locked read.

        With ``as_of`` (a unix timestamp) the value is read from ``fact_history``
        as it stood at that instant (requires ``[memory] temporal``); returns
        None when no recorded version covered that time."""
        if as_of is not None:
            row = self._read_one(
                "SELECT value FROM fact_history WHERE key = ? AND valid_from <= ? "
                "AND (valid_to IS NULL OR valid_to > ?) "
                "ORDER BY valid_from DESC LIMIT 1",
                (key, as_of, as_of),
            )
            return _dec_field(row["value"]) if row else None
        row = self._read_one("SELECT value FROM facts WHERE key = ? LIMIT 1", (key,))
        return _dec_field(row["value"]) if row else None

    def fact_history(self, key: str, *, limit: int = 50) -> list[FactVersion]:
        """Every recorded version of ``key``, newest first (requires ``[memory]
        temporal``). The entry whose ``valid_to is None`` is the current value;
        the rest are superseded values with the window they were believed in."""
        rows = self._read_all(
            "SELECT value, valid_from, valid_to, source, trust_tier, sensitivity "
            "FROM fact_history WHERE key = ? ORDER BY valid_from DESC LIMIT ?",
            (key, max(1, int(limit))),
        )
        return [
            FactVersion(
                value=_dec_field(r["value"]),
                valid_from=r["valid_from"],
                valid_to=r["valid_to"],
                source=r["source"] or "",
                trust_tier=int(r["trust_tier"]),
                sensitivity=r["sensitivity"] or "internal",
            )
            for r in rows
        ]

    def delete_fact(self, key: str) -> int:
        """Delete one fact by exact key; return rows removed (0 or 1).

        When ``[memory] temporal`` is on, the open ``fact_history`` window is
        closed (valid_to = now) rather than erased, so the record that the fact
        existed until this moment survives the delete."""
        with self._writing() as conn:
            if _temporal_memory_enabled():
                conn.execute(
                    "UPDATE fact_history SET valid_to = ? "
                    "WHERE key = ? AND valid_to IS NULL",
                    (time.time(), key),
                )
            return conn.execute("DELETE FROM facts WHERE key = ?", (key,)).rowcount

    def stale_fact_keys(self, older_than: float, limit: int = 500) -> list[str]:
        """Keys of facts not updated since ``older_than``, oldest first.

        Read-only; the dreaming fact-consolidation phase decides what to
        delete (and is itself opt-in)."""
        rows = self._read_all(
            "SELECT key FROM facts WHERE updated_at < ? "
            "ORDER BY updated_at ASC LIMIT ?",
            (older_than, max(1, int(limit))),
        )
        return [r["key"] for r in rows]

    def count_facts(self) -> int:
        row = self._read_one("SELECT COUNT(*) AS n FROM facts", ())
        return int(row["n"]) if row else 0

    def list_facts(self, key_prefix: str, limit: int = 50) -> list[tuple[str, int]]:
        """``(key, value_size)`` for facts whose key starts with ``key_prefix``,
        newest first. Locked read; the prefix is LIKE-escaped."""
        like = self._like_escape(key_prefix) + "%"
        rows = self._read_all(
            "SELECT key, length(value) AS sz FROM facts "
            "WHERE key LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?",
            (like, limit),
        )
        return [(r["key"], r["sz"]) for r in rows]

    def search_facts(
        self, key_prefix: str, query: str, limit: int = 50,
    ) -> list[tuple[str, str]]:
        """``(key, value)`` for facts under ``key_prefix`` whose key or value
        contains ``query`` (literal substring), newest first. Locked read."""
        pfx = self._like_escape(key_prefix) + "%"
        from .crypto_at_rest import at_rest_enabled
        if not at_rest_enabled():
            q = "%" + self._like_escape(query) + "%"
            rows = self._read_all(
                "SELECT key, value FROM facts WHERE key LIKE ? ESCAPE '\\' "
                "AND (key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\') "
                "ORDER BY updated_at DESC LIMIT ?",
                (pfx, q, q, limit),
            )
            return [(r["key"], _dec_field(r["value"])) for r in rows]
        # Encryption on: `value` is sealed ciphertext, so a SQL LIKE over it can
        # never match the plaintext query (the search would silently return
        # nothing). Keys are stored plaintext, so narrow the scan by prefix in
        # SQL, then decrypt and substring-match in Python. Case-insensitive to
        # match SQLite LIKE's ASCII semantics on the plaintext path.
        rows = self._read_all(
            "SELECT key, value FROM facts WHERE key LIKE ? ESCAPE '\\' "
            "ORDER BY updated_at DESC",
            (pfx,),
        )
        needle = query.lower()
        out: list[tuple[str, str]] = []
        for r in rows:
            val = _dec_field(r["value"])
            if needle in r["key"].lower() or (val is not None and needle in val.lower()):
                out.append((r["key"], val))
                if len(out) >= limit:
                    break
        return out

    # ----- questions -----
    def ask(self, question: str, goal_id: int | None = None) -> int:
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO questions(goal_id, question, asked_at) VALUES(?, ?, ?)",
                (goal_id, _enc_field(question), time.time()),
            )
            return cur.lastrowid

    def answer(self, question_id: int, answer: str) -> bool:
        """Record an answer to a question. Returns False if no question with
        that id exists, so callers can flag a typo'd id instead of reporting
        a false success."""
        with self._writing() as conn:
            cur = conn.execute(
                "UPDATE questions SET answer = ?, answered_at = ? WHERE id = ?",
                (_enc_field(answer), time.time(), question_id),
            )
            return cur.rowcount > 0

    def open_questions(self, goal_id: int | None = None) -> list[Question]:
        if goal_id is not None:
            rows = self._read_all(
                "SELECT * FROM questions WHERE answer IS NULL AND goal_id = ? ORDER BY id", (goal_id,)
            )
        else:
            rows = self._read_all(
                "SELECT * FROM questions WHERE answer IS NULL ORDER BY id"
            )
        return [_question_from_row(r) for r in rows]

    def all_questions(self, goal_id: int) -> list[Question]:
        rows = self._read_all(
            "SELECT * FROM questions WHERE goal_id = ? ORDER BY id", (goal_id,)
        )
        return [_question_from_row(r) for r in rows]

    # ----- approvals (high-risk action queue) -----
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

        ``provenance`` is trusted caller-supplied metadata used by operator UIs;
        it must not be inferred from ``detail``, which may contain untrusted
        model, user, or remote-server text.
        """
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO approvals(action, risk, scope, detail, provenance, status, requested_at) "
                "VALUES(?, ?, ?, ?, ?, 'pending', ?)",
                (_enc_field(action), risk, _enc_field(scope), _enc_field(detail),
                 provenance, time.time()),
            )
            return cur.lastrowid

    def get_approval(self, approval_id: int) -> Approval | None:
        row = self._read_one(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        )
        return _approval_from_row(row) if row else None

    def list_approvals(self, limit: int = 500) -> list[Approval]:
        """All approvals, newest first (the Operating Record's human-decision
        feed); ``pending_approvals`` remains the queue view."""
        rows = self._read_all(
            "SELECT * FROM approvals ORDER BY requested_at DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [_approval_from_row(r) for r in rows]

    def pending_approvals(self) -> list[Approval]:
        rows = self._read_all(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY id"
        )
        return [_approval_from_row(r) for r in rows]

    def decide_approval(self, approval_id: int, status: str,
                        decided_by: str | None = None) -> bool:
        """Flip a pending approval to 'approved' or 'denied'.

        Returns True if a pending row was transitioned, False otherwise
        (unknown id, or already decided — so a double-click is a no-op).
        ``decided_by`` records WHICH supervisor decided (collaborative
        supervision attribution); None keeps the legacy unattributed form.
        """
        if status not in ("approved", "denied"):
            raise ValueError("status must be 'approved' or 'denied'")
        with self._writing() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, time.time(), decided_by, approval_id),
            )
            return cur.rowcount > 0

    def claim_approval(self, approval_id: int, principal: str) -> bool:
        """Atomically claim a pending approval for one supervisor.

        Collaborative supervision: a claim marks "I'm handling this" so two
        supervisors don't double-work the same review. Succeeds when the row
        is pending and unclaimed (or already claimed by the SAME principal —
        re-claiming your own claim is a no-op refresh). Returns False when
        someone else holds it, it's decided, or the id is unknown.
        """
        principal = (principal or "").strip()
        if not principal:
            raise ValueError("principal is required to claim an approval")
        with self._writing() as conn:
            cur = conn.execute(
                "UPDATE approvals SET claimed_by = ?, claimed_at = ? "
                "WHERE id = ? AND status = 'pending' "
                "AND (claimed_by IS NULL OR claimed_by = ?)",
                (principal, time.time(), approval_id, principal),
            )
            return cur.rowcount > 0

    def release_approval(self, approval_id: int, principal: str) -> bool:
        """Release a claim you hold (pending rows only). Only the claim
        holder can release; returns False otherwise."""
        principal = (principal or "").strip()
        if not principal:
            raise ValueError("principal is required to release an approval")
        with self._writing() as conn:
            cur = conn.execute(
                "UPDATE approvals SET claimed_by = NULL, claimed_at = NULL "
                "WHERE id = ? AND status = 'pending' AND claimed_by = ?",
                (approval_id, principal),
            )
            return cur.rowcount > 0

    # ----- messages -----
    def append_message(self, goal_id: int, role: str, content: str) -> None:
        with self._writing() as conn:
            conn.execute(
                "INSERT INTO messages(goal_id, role, content, ts) VALUES(?, ?, ?, ?)",
                (goal_id, role, _enc_field(content), time.time()),
            )

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        # Quote the user text as a single FTS5 string literal (escaping
        # embedded quotes). Passing it raw let an unbalanced quote / leading
        # `*` / `NEAR` / `-` raise sqlite3.OperationalError: fts5 syntax error
        # and crash the search on ordinary natural-language input.
        if not query or not query.strip():
            return []
        fts_query = '"' + query.replace('"', '""') + '"'
        rows = self._read_all(
            "SELECT m.* FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
            "WHERE messages_fts MATCH ? ORDER BY m.ts DESC LIMIT ?",
            (fts_query, limit),
        )
        # Decrypt content for any matched rows. Under at-rest encryption the FTS
        # index holds ciphertext, so a plaintext query only matches legacy
        # plaintext rows (search over encrypted messages is disabled); those rows
        # are returned decrypted, and pre-encryption plaintext passes through.
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["content"] = _dec_field(d.get("content"))
            out.append(d)
        return out

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
        goal_id: int | None = None,
    ) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")
        with self._writing() as conn:
            cur = conn.execute(
                "INSERT INTO turns(conversation_id, goal_id, role, content, ts) "
                "VALUES(?, ?, ?, ?, ?)",
                (conversation_id, goal_id, role, _enc_field(content), time.time()),
            )
            return cur.lastrowid

    def recent_turns(self, conversation_id: int, limit: int = 20) -> list[Turn]:
        """Return the most recent N turns in chronological (ascending) order
        so they can be fed straight into a chat-format prompt."""
        rows = self._read_all(
            "SELECT id, conversation_id, goal_id, role, content, ts FROM turns "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        out: list[Turn] = []
        for r in rows:
            d = dict(r)
            d["content"] = _dec_field(d["content"])
            out.append(Turn(**d))
        return list(reversed(out))

    def list_conversations(self, channel: str | None = None) -> list[Conversation]:
        if channel:
            rows = self._read_all(
                "SELECT * FROM conversations WHERE channel = ? ORDER BY last_seen DESC",
                (channel,),
            )
        else:
            rows = self._read_all(
                "SELECT * FROM conversations ORDER BY last_seen DESC"
            )
        return [Conversation(**dict(r)) for r in rows]

    # ----- channel dedup -----
    def mark_message_processed(
        self,
        channel: str,
        external_id: str,
        goal_id: int | None = None,
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

    def release_processed_message(self, channel: str, external_id: str) -> None:
        """Undo a claim made by ``mark_message_processed`` so a retry can
        re-process the message.

        Channels claim the dedup row BEFORE running the goal (atomic, so a
        Twilio retry that races a slow handler is a no-op instead of a
        double-spend). If that run then fails, the claim must be released or
        the message is stuck marked-as-done and never retried.
        """
        with self._writing() as conn:
            conn.execute(
                "DELETE FROM processed_messages "
                "WHERE channel = ? AND external_id = ?",
                (channel, external_id),
            )

    def lookup_processed_message(
        self,
        channel: str,
        external_id: str,
    ) -> int | None:
        """Return the goal_id for an already-processed message, if any.

        Distinguishes 'no row' (returns None) from 'row exists but goal_id
        is null' (returns 0). Callers that just need "have we seen this?"
        should use ``is_processed_message`` to avoid that ambiguity.
        """
        row = self._read_one(
            "SELECT goal_id FROM processed_messages "
            "WHERE channel = ? AND external_id = ?",
            (channel, external_id),
        )
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
        row = self._read_one(
            "SELECT 1 FROM processed_messages "
            "WHERE channel = ? AND external_id = ? LIMIT 1",
            (channel, external_id),
        )
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
        rows = self._read_all(
            "SELECT id, goal_id, filename, mime, size_bytes, sha256, path, created_at "
            "FROM attachments WHERE goal_id = ? ORDER BY id",
            (goal_id,),
        )
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


class PostgresAtRestUnsupported(RuntimeError):
    """Encryption-at-rest is on but the Postgres backend is selected.

    The Postgres backend does not seal content at rest yet (the SQLite backend
    does, via ``crypto_at_rest``). Rather than silently storing regulated /
    encrypted-at-rest data as plaintext, :func:`open_world` fails closed. See
    ``docs/encryption.md`` and ``FIXES.md`` (P1)."""


def open_world(path: Path = DEFAULT_DB) -> Any:
    """Open the configured world-model backend.

    Returns the SQLite ``WorldModel`` by default. When the user opts into
    Postgres (``[world_model] backend = "postgres"`` in config.toml or
    ``MAVERICK_WORLD_BACKEND=postgres``), returns a ``PostgresWorldModel``
    whose public surface mirrors ``WorldModel``; the ``path`` argument is
    ignored in that case (Postgres uses a DSN, not a file).

    The Postgres backend (and its ``psycopg`` dependency) is imported only
    when selected, so the default SQLite path stays dependency-free and the
    kernel runs without psycopg installed.

    **Fail-closed at-rest safety:** the Postgres backend does not seal content
    at rest yet (unlike SQLite). Selecting it while encryption-at-rest is
    enabled raises :class:`PostgresAtRestUnsupported` instead of silently
    storing plaintext — use SQLite for encrypted/regulated deployments until
    Postgres sealing lands.
    """
    from .world_model_backends import is_postgres_configured

    if is_postgres_configured():
        # Fail closed rather than silently degrade the encryption-at-rest
        # guarantee: the Postgres backend stores content as plaintext today.
        # Checked BEFORE importing psycopg so a misconfig surfaces this clear
        # error rather than an ImportError or, worse, plaintext-at-rest.
        from .crypto_at_rest import at_rest_enabled
        if at_rest_enabled():
            raise PostgresAtRestUnsupported(
                "encryption-at-rest is enabled, but the Postgres world-model "
                "backend does not seal content at rest yet. Use the SQLite "
                "backend (unset [world_model] backend / MAVERICK_WORLD_BACKEND) "
                "for encrypted or regulated deployments, or disable "
                "encryption-at-rest. Tracked in FIXES.md / docs/encryption.md."
            )
        from .world_model_backends import open_postgres_world

        return open_postgres_world()
    return WorldModel(path)


# Per-tenant WorldModel cache. P1 multi-tenancy: each tenant gets its own
# world.db under ~/.maverick/tenants/<t>/, mirroring how cross-session memory
# (tools/memory.py) and the audit log resolve their dirs via data_dir(). Keyed
# by the RESOLVED db path so two raw tenant ids that sanitize to the same dir
# share one connection -- a single SQLite file must have exactly one WorldModel
# (its write lock serialises mutations within the process; two instances on the
# same file would not coordinate). Cached for the life of the process, like the
# audit log's default singleton: WorldModel opens with check_same_thread=False +
# WAL + a write lock, so one instance is safely shared across the FastAPI
# threadpool / goal tasks.
MAX_TENANT_WORLDS = 128
_tenant_worlds: dict[str, WorldModel] = {}
_tenant_worlds_lock = threading.Lock()


class TenantWorldLimitError(RuntimeError):
    """Raised when the process has reached its tenant world cache limit."""


def world_for_tenant(tenant: str | None = None) -> WorldModel:
    """Return the process-cached ``WorldModel`` for ``tenant``.

    ``tenant=None`` is the legacy shared world at ``~/.maverick/world.db``
    (single-tenant behaviour unchanged); a tenant ``t`` gets an isolated
    ``~/.maverick/tenants/<t>/world.db``. The path is resolved via
    :func:`maverick.paths.data_dir`, the same primitive memory + audit use, so
    world/memory/audit all land under the same tenant dir.

    Repeated calls for the same tenant return the SAME instance; distinct
    tenants get distinct DBs, up to ``MAX_TENANT_WORLDS`` cached tenant
    connections. Does NOT consult the Postgres backend -- it is the per-tenant
    SQLite factory the server uses for goal/conversation/turn writes.
    """
    from .paths import data_dir

    path = data_dir("world.db", tenant=tenant)
    key = str(path)
    with _tenant_worlds_lock:
        world = _tenant_worlds.get(key)
        if world is None:
            if tenant is not None and len(_tenant_worlds) >= MAX_TENANT_WORLDS:
                raise TenantWorldLimitError("tenant world cache limit reached")
            world = WorldModel(path)
            _tenant_worlds[key] = world
        return world
