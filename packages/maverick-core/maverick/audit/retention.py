"""Data-retention enforcement.

Reads ``[retention]`` from ``~/.maverick/config.toml`` and prunes:

  - ``~/.maverick/audit/YYYY-MM-DD.ndjson`` files older than
    ``audit_days``.
  - ``episodes`` rows in ``~/.maverick/world.db`` with
    ``ended_at`` older than ``episodes_days``.
  - ``goal_events`` rows with ``ts`` older than ``events_days``.
  - usage-ledger ``(principal, day)`` cost buckets older than
    ``usage_days`` (the per-principal chargeback tally grows forever
    otherwise).

Config defaults are "no pruning" — retention is opt-in. The CLI
exposes ``maverick retention enforce [--dry-run]``.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _config() -> dict:
    try:
        from ..config import load_config
        return (load_config() or {}).get("retention") or {}
    except Exception as e:
        log.debug("retention: cannot load config: %s", e)
        return {}


def _cutoff_for_days(days: int, *, now: float | None = None) -> float:
    now = now if now is not None else time.time()
    return now - max(1, int(days)) * 86400.0


def purge_audit_files(
    *,
    days: int,
    audit_dir: Path | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> dict:
    """Remove ``YYYY-MM-DD.ndjson`` files older than ``days``.

    Filename date wins over mtime — easier to reason about, immune to
    filesystem mtime drift from backups/rsync.
    """
    if days is None or int(days) <= 0:
        return {"removed": [], "kept": 0, "reason": "disabled"}
    if audit_dir is None:
        # Match the writer's (home + active-tenant) audit dir; the old frozen
        # ~/.maverick/audit default made enforce() report "no audit dir" and
        # purge nothing whenever MAVERICK_HOME / a tenant moved the real files.
        from ..paths import data_dir
        audit_dir = data_dir("audit")
    if not audit_dir.exists():
        return {"removed": [], "kept": 0, "reason": "no audit dir"}

    cutoff_ts = _cutoff_for_days(days, now=now)
    cutoff_day = datetime.utcfromtimestamp(cutoff_ts).date()
    removed: list[str] = []
    kept = 0
    for path in sorted(audit_dir.glob("*.ndjson")):
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            kept += 1
            continue
        # <= : the day-file dated exactly `days` ago is expired and must be
        # purged. Strict < kept it, making the window days+1.
        if day <= cutoff_day:
            removed.append(path.name)
            if not dry_run:
                try:
                    path.unlink()
                except OSError as e:
                    log.warning("retention: cannot unlink %s: %s", path, e)
                    continue
        else:
            kept += 1
    log.info(
        "retention: audit purge cutoff=%s removed=%d kept=%d dry_run=%s",
        cutoff_day, len(removed), kept, dry_run,
    )
    return {"removed": removed, "kept": kept, "cutoff_day": str(cutoff_day)}


def _purge_table_by_time(
    db_path: Path,
    table: str,
    time_col: str,
    cutoff_ts: float,
    *,
    dry_run: bool,
) -> int:
    if not db_path.exists():
        return 0
    # Table/column names can't be parameter-bound, so they MUST come from
    # this fixed allow-set — never from caller/user input — to keep the
    # f-string interpolation below injection-free.
    _ALLOWED = {("episodes", "ended_at"), ("goal_events", "ts")}
    if (table, time_col) not in _ALLOWED:
        raise ValueError(
            f"refusing to purge unknown table/column: {table!r}/{time_col!r}"
        )
    conn = sqlite3.connect(str(db_path))
    try:
        # The agent may be writing concurrently; wait rather than fail fast.
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {time_col} IS NOT NULL AND {time_col} < ?",
            (cutoff_ts,),
        )
        (count,) = cur.fetchone()
        if not dry_run and count > 0:
            conn.execute(
                f"DELETE FROM {table} WHERE {time_col} IS NOT NULL AND {time_col} < ?",
                (cutoff_ts,),
            )
            conn.commit()
        return int(count or 0)
    finally:
        conn.close()


def purge_world_episodes(
    *,
    days: int,
    db_path: Path | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> dict:
    """Delete ``episodes`` rows ended before ``days`` ago."""
    if days is None or int(days) <= 0:
        return {"deleted": 0, "reason": "disabled"}
    from ..world_model import DEFAULT_DB
    db_path = db_path or DEFAULT_DB
    cutoff_ts = _cutoff_for_days(days, now=now)
    deleted = _purge_table_by_time(
        db_path, "episodes", "ended_at", cutoff_ts, dry_run=dry_run,
    )
    log.info("retention: episodes deleted=%d dry_run=%s", deleted, dry_run)
    return {"deleted": deleted, "cutoff_ts": cutoff_ts}


def purge_world_events(
    *,
    days: int,
    db_path: Path | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> dict:
    """Delete ``goal_events`` rows older than ``days``."""
    if days is None or int(days) <= 0:
        return {"deleted": 0, "reason": "disabled"}
    from ..world_model import DEFAULT_DB
    db_path = db_path or DEFAULT_DB
    cutoff_ts = _cutoff_for_days(days, now=now)
    deleted = _purge_table_by_time(
        db_path, "goal_events", "ts", cutoff_ts, dry_run=dry_run,
    )
    log.info("retention: goal_events deleted=%d dry_run=%s", deleted, dry_run)
    return {"deleted": deleted, "cutoff_ts": cutoff_ts}


def purge_usage_ledger(
    *,
    days: int,
    ledger_path: Path | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> dict:
    """Prune usage-ledger ``(principal, day)`` buckets older than ``days``."""
    if days is None or int(days) <= 0:
        return {"removed_buckets": 0, "reason": "disabled"}
    from ..quotas import UsageLedger
    ledger = UsageLedger(ledger_path) if ledger_path is not None else UsageLedger()
    result = ledger.prune(int(days), now=now, dry_run=dry_run)
    log.info("retention: usage ledger removed_buckets=%d dry_run=%s",
             result.get("removed_buckets", 0), dry_run)
    return result


def enforce(
    *,
    config: dict | None = None,
    dry_run: bool = False,
    audit_dir: Path | None = None,
    db_path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Apply every configured retention rule. Returns a per-rule report.

    ``audit_dir`` defaults to the writer's home/tenant-aware audit dir
    (resolved by :func:`purge_audit_files`), not a frozen path.
    """
    cfg = config if config is not None else _config()
    if not cfg:
        return {"status": "disabled", "reason": "no [retention] in config"}

    audit_days = cfg.get("audit_days")
    episodes_days = cfg.get("episodes_days")
    events_days = cfg.get("events_days")
    usage_days = cfg.get("usage_days")

    report: dict = {"dry_run": dry_run}
    if audit_days:
        report["audit"] = purge_audit_files(
            days=audit_days, audit_dir=audit_dir, dry_run=dry_run, now=now,
        )
    if episodes_days:
        report["episodes"] = purge_world_episodes(
            days=episodes_days, db_path=db_path, dry_run=dry_run, now=now,
        )
    if events_days:
        report["goal_events"] = purge_world_events(
            days=events_days, db_path=db_path, dry_run=dry_run, now=now,
        )
    if usage_days:
        report["usage_ledger"] = purge_usage_ledger(
            days=usage_days, dry_run=dry_run, now=now,
        )
    return report


__all__ = [
    "enforce",
    "purge_audit_files",
    "purge_world_episodes",
    "purge_world_events",
    "purge_usage_ledger",
]
