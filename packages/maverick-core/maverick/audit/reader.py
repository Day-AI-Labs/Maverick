"""Single source of truth for reading the tamper-evident audit NDJSON log.

Three read-side consumers used to each re-implement the same three steps with
ad-hoc globs and filename literals:

  - :mod:`maverick.audit.export` (SIEM export / ``maverick audit export``),
  - :mod:`maverick.dsar` (GDPR Art. 15/20 subject-access export),
  - :mod:`maverick.soc2` (the audit-chain compliance probe).

They drifted apart in ways that were quietly wrong -- ``dsar`` read the
cross-file ``anchors.ndjson`` tip-ledger as if it were a day-file and ignored
at-rest sealing, while ``export`` excluded the ledger and decrypted sealed
segments. This module defines, once:

  - :func:`day_files` -- what counts as a day-file (re-exported from
    :mod:`maverick.audit.signing`, where the ``YYYY-MM-DD`` pattern and the
    :data:`ANCHOR_FILENAME` constant live), so the anchor ledger is excluded the
    same way everywhere; and
  - :func:`iter_events` -- how to turn the selected day-files into event dicts,
    transparently decrypting sealed segments (:func:`maverick.audit.sealing.segment_text`)
    and skipping malformed/unreadable input (fail-soft).

Read-only: nothing here ever mutates the log or touches the signing chain.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .events import is_valid_day
from .sealing import segment_text
from .signing import ANCHOR_FILENAME, day_files  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)

__all__ = ["ANCHOR_FILENAME", "day_files", "event_paths", "iter_events"]


def resolve_audit_dir(tenant: str | None) -> Path:
    """The tenant-aware audit directory (``<data>/audit``).

    Mirrors :class:`maverick.audit.writer.AuditLog`'s own default so a read
    reflects where rows are *currently* written. ``tenant=None`` follows the
    active tenant (env / contextvar), matching the writer and the export CLI.
    """
    from ..paths import data_dir

    return data_dir("audit", tenant=tenant) if tenant else data_dir("audit")


def event_paths(
    *, day: str | None = None, all_days: bool = False,
    since: str | None = None, until: str | None = None,
    tenant: str | None = None,
) -> list[Path]:
    """Return the tenant-aware audit day-files selected for reading.

    Selection precedence: a ``since``/``until`` window (inclusive, over day-file
    dates) wins; then ``all_days`` sweeps every day-file; otherwise a single
    day-file (``day`` or today, UTC) is returned. The cross-file anchor ledger
    is never included (it is not a date-named day-file).
    """
    # Validate the path-forming input first -- before any filesystem check that
    # could otherwise short-circuit (an empty dir) and let a crafted ``day``
    # slip past. (``since``/``until`` are only compared lexically below, never
    # built into a path.)
    if day is not None and not is_valid_day(day):
        raise ValueError(f"invalid audit day {day!r}: expected YYYY-MM-DD")

    audit_dir = resolve_audit_dir(tenant)
    if not audit_dir.exists() or not audit_dir.is_dir():
        return []

    if since or until:
        # Inclusive [since, until] window over day-file dates. ISO YYYY-MM-DD
        # sorts lexically, so a plain string compare on the file stem works.
        lo = since or "0000-00-00"
        hi = until or "9999-99-99"
        return [p for p in day_files(audit_dir) if lo <= p.stem <= hi]
    if all_days:
        return day_files(audit_dir)

    # ``day`` was validated up front; default to today (UTC) when unset.
    d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    return [audit_dir / f"{d}.ndjson"]


def iter_events(
    *, day: str | None = None, all_days: bool = False,
    since: str | None = None, until: str | None = None,
    tenant: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield audit event dicts from the tenant-aware audit dir.

    Sealing-aware (transparently decrypts an at-rest-sealed segment) and
    fail-soft: malformed/unreadable lines and a missing dir are skipped
    silently, and the anchor ledger is excluded. See :func:`event_paths` for the
    selection precedence.
    """
    for path in event_paths(
        day=day, all_days=all_days, since=since, until=until, tenant=tenant,
    ):
        # segment_text transparently decrypts a sealed (at-rest) segment and is
        # fail-soft (returns "" on a read/decrypt error).
        for line in segment_text(path).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
