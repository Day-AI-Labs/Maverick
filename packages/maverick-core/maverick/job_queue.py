"""Persistent job queue for background goals.

A pure-Python SQLite-backed queue that lets the orchestrator (or
the dashboard) enqueue work that should run *later* without keeping
the request thread alive:

  - "schedule this goal for 3am"
  - "retry this failed goal in 10 minutes"
  - "rate-limit me to 1 of these per minute"

Distinct from ``maverick.runner``, which spawns goals immediately
in a thread pool. The queue is the durable layer underneath: it
survives process restarts and gives the dashboard a single place to
see what's pending.

Schema: ONE table ``jobs(id, kind, payload, run_at, status, attempts,
last_error, created_at, updated_at)``. SQLite WAL mode for concurrent
readers (dashboard) + writer (worker).

Workflow:

  - ``enqueue(kind, payload, run_at=None)`` -> job id
  - ``claim(now)``                          -> next ready job (atomic UPDATE)
  - ``complete(job_id)``                    -> mark done
  - ``fail(job_id, error, retry_after=60)`` -> bump attempts + reschedule
  - ``list(status='pending')``              -> rows for the dashboard
  - ``purge(older_than_days=7)``            -> sweep terminal rows
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

log = logging.getLogger(__name__)


DEFAULT_DB = Path.home() / ".maverick" / "jobs.db"


@dataclass
class Job:
    id: int
    kind: str
    payload: dict
    run_at: float
    status: str
    attempts: int = 0
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL,
  payload     TEXT NOT NULL,
  run_at      REAL NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending',
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_error  TEXT NOT NULL DEFAULT '',
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, run_at);
"""


class JobQueue:
    """Thread-safe persistent job queue.

    Multiple ``JobQueue`` instances against the same DB file are
    safe — SQLite WAL handles concurrent writers; the ``claim()``
    method uses a single UPDATE ... WHERE id=(SELECT MIN id) so
    workers don't double-claim.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(str(self.db_path), isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.row_factory = sqlite3.Row
            yield c
        finally:
            c.close()

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def enqueue(
        self,
        kind: str,
        payload: dict | None = None,
        *,
        run_at: Optional[float] = None,
    ) -> int:
        now = time.time()
        rid = run_at if run_at is not None else now
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO jobs (kind, payload, run_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, json.dumps(payload or {}, default=str), rid, now, now),
            )
            return int(cur.lastrowid)

    def claim(self, *, now: Optional[float] = None) -> Optional[Job]:
        """Atomically pick the next ready pending job + mark it 'running'."""
        n = now if now is not None else time.time()
        with self._lock, self._conn() as c:
            # Pick a candidate.
            row = c.execute(
                "SELECT id FROM jobs WHERE status='pending' AND run_at <= ? "
                "ORDER BY run_at ASC, id ASC LIMIT 1",
                (n,),
            ).fetchone()
            if not row:
                return None
            jid = row[0]
            # Try to mark it running atomically (status check guards
            # against races between SELECT and UPDATE).
            cur = c.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, "
                "updated_at=? WHERE id=? AND status='pending'",
                (n, jid),
            )
            if cur.rowcount == 0:
                return None
            row = c.execute(
                "SELECT * FROM jobs WHERE id=?", (jid,),
            ).fetchone()
        return self._row_to_job(row)

    def complete(self, job_id: int) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status='done', updated_at=? WHERE id=?",
                (time.time(), job_id),
            )
            return cur.rowcount == 1

    def fail(
        self,
        job_id: int,
        error: str,
        *,
        retry_after: Optional[float] = 60.0,
        max_attempts: int = 5,
    ) -> bool:
        """Either reschedule (retry_after seconds) or mark 'failed' permanently."""
        now = time.time()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT attempts FROM jobs WHERE id=?", (job_id,),
            ).fetchone()
            if not row:
                return False
            attempts = int(row[0])
            if retry_after is not None and attempts < max_attempts:
                next_run = now + float(retry_after)
                cur = c.execute(
                    "UPDATE jobs SET status='pending', run_at=?, "
                    "last_error=?, updated_at=? WHERE id=?",
                    (next_run, error[:1000], now, job_id),
                )
            else:
                cur = c.execute(
                    "UPDATE jobs SET status='failed', last_error=?, "
                    "updated_at=? WHERE id=?",
                    (error[:1000], now, job_id),
                )
            return cur.rowcount == 1

    def reclaim_stale(
        self,
        lease_seconds: float,
        *,
        now: Optional[float] = None,
        max_attempts: int = 5,
    ) -> int:
        """Requeue jobs stuck in 'running' past the lease TTL.

        ``claim()`` flips a job to 'running' and bumps ``updated_at``. If the
        worker process then dies before ``complete()``/``fail()`` (a hard
        crash, OOM, or ``kill -9`` — none of which run ``run_once``'s
        ``except`` path), the row stays 'running' forever: ``claim()`` only
        ever looks at 'pending' rows, so no worker re-claims it and the job
        is silently orphaned. Run this on worker start to recover them.

        A job whose ``updated_at`` is older than ``now - lease_seconds`` is
        considered abandoned. Pick a ``lease_seconds`` larger than the
        longest expected job runtime so a still-running job in a live worker
        is not stolen. Abandoned jobs already at/over ``max_attempts`` are
        marked 'failed' (poison-pill guard, mirroring ``fail()``'s terminal
        path) so a job that reliably crashes the *process* can't be requeued
        forever; the rest go back to 'pending' with ``run_at = now`` so
        they're immediately eligible. ``attempts`` is preserved (not reset)
        so the cap is reached. Returns the number of rows transitioned.
        """
        n = now if now is not None else time.time()
        cutoff = n - float(lease_seconds)
        with self._lock, self._conn() as c:
            failed = c.execute(
                "UPDATE jobs SET status='failed', last_error=?, updated_at=? "
                "WHERE status='running' AND updated_at < ? AND attempts >= ?",
                ("lease expired (worker presumed crashed)", n, cutoff, max_attempts),
            ).rowcount
            requeued = c.execute(
                "UPDATE jobs SET status='pending', run_at=?, updated_at=? "
                "WHERE status='running' AND updated_at < ? AND attempts < ?",
                (n, n, cutoff, max_attempts),
            ).rowcount
        return int(failed) + int(requeued)

    def cancel(self, job_id: int) -> bool:
        """Delete a *pending* job (e.g. an armed schedule).

        Only 'pending' rows are removable -- a 'running' job is left for the
        worker to finish, and 'done'/'failed' rows are history. Returns True
        if a row was deleted.
        """
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM jobs WHERE id=? AND status='pending'", (job_id,),
            )
            return cur.rowcount == 1

    def get(self, job_id: int) -> Optional[Job]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list(self, *, status: str = "", limit: int = 100) -> list[Job]:
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,),
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def purge(self, *, older_than_days: float = 7.0) -> int:
        cutoff = time.time() - older_than_days * 86400
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM jobs WHERE status IN ('done','failed') AND updated_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    @staticmethod
    def _row_to_job(row) -> Job:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        return Job(
            id=int(row["id"]),
            kind=str(row["kind"]),
            payload=payload if isinstance(payload, dict) else {"_": payload},
            run_at=float(row["run_at"]),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            last_error=str(row["last_error"] or ""),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


__all__ = ["JobQueue", "Job", "DEFAULT_DB"]
