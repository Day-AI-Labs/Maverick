"""Seal existing plaintext data after at-rest encryption is enabled.

Enabling at-rest encryption (``[encryption] at_rest``) only seals **new** writes;
rows written before are left plaintext and read back transparently (lazy
migration). This module force-seals that pre-existing plaintext so the whole
store is encrypted, not just new data. It is **idempotent** — already-sealed
values are skipped — so it is safe to re-run.

Exposed as ``maverick encryption migrate [--dry-run]``.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .crypto_at_rest import (
    EncryptionUnavailable,
    at_rest_enabled,
    is_sealed_str,
    seal_to_str,
)

log = logging.getLogger(__name__)

# (table, text-column) pairs that at-rest encryption seals. Names come from this
# fixed allow-set -- never user input -- so the f-string interpolation below is
# injection-free (same discipline as audit/retention.py).
_SEALED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("turns", "content"),
    ("facts", "value"),
    ("messages", "content"),
    ("questions", "question"),
    ("questions", "answer"),
    ("goals", "title"),
    ("goals", "description"),
    ("goals", "result"),
    ("goal_events", "content"),
    ("episodes", "summary"),
    ("episodes", "outcome"),
    ("approvals", "action"),
    ("approvals", "scope"),
    ("approvals", "detail"),
)


def migrate_world_db(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Seal any remaining plaintext in the world DB's sensitive columns.

    Returns a ``{"table.column": rows_sealed}`` report. Requires at-rest
    encryption to be enabled (so the key is configured); raises
    :class:`EncryptionUnavailable` otherwise, or if the crypto backend / key is
    missing -- this never writes plaintext.
    """
    if not at_rest_enabled():
        raise EncryptionUnavailable(
            "at-rest encryption is not enabled; set [encryption] at_rest = true "
            "(or MAVERICK_ENCRYPT_AT_REST=1) before migrating"
        )
    report: dict[str, int] = {}
    if not db_path.exists():
        return report
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        # Zero freed cells as rows are re-sealed in place, so the pre-encryption
        # plaintext can't be recovered from the DB file's free list.
        if not dry_run:
            conn.execute("PRAGMA secure_delete=ON")
        for table, col in _SEALED_COLUMNS:
            try:
                rows = conn.execute(
                    f"SELECT rowid AS rid, {col} AS val FROM {table}"
                ).fetchall()
            except sqlite3.OperationalError:
                continue  # table/column absent on an older schema
            sealed = 0
            for r in rows:
                val = r["val"]
                if val is None or is_sealed_str(val):
                    continue
                if not dry_run:
                    conn.execute(
                        f"UPDATE {table} SET {col} = ? WHERE rowid = ?",
                        (seal_to_str(val), r["rid"]),
                    )
                sealed += 1
            report[f"{table}.{col}"] = sealed
        if not dry_run:
            conn.commit()
            _shred_residue(conn, report)
    finally:
        conn.close()
    log.info("encryption migrate (dry_run=%s): %s", dry_run, report)
    return report


def _shred_residue(conn: sqlite3.Connection, report: dict[str, int]) -> None:
    """Make the pre-encryption plaintext unrecoverable from the DB file.

    ``secure_delete=ON`` already zeroed the freed cells as rows were re-sealed in
    place; this additionally flushes + truncates the WAL sidecar (which can still
    hold pre-migration plaintext frames) and VACUUMs to rebuild the file with no
    residual free pages. Best-effort: if the DB is locked (e.g. the agent is
    running) the rebuild is skipped with a warning -- the in-place zeroing stands.
    """
    if not any(report.values()):
        return
    conn.isolation_level = None   # autocommit: VACUUM / checkpoint need no open txn
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as e:
        log.warning(
            "encryption migrate: could not VACUUM/checkpoint to shred residue "
            "(%s); freed pages were still zeroed in place via secure_delete", e,
        )


__all__ = ["migrate_world_db"]
