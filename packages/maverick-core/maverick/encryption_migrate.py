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
    finally:
        conn.close()
    log.info("encryption migrate (dry_run=%s): %s", dry_run, report)
    return report


__all__ = ["migrate_world_db"]
