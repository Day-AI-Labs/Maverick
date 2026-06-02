"""Audit-log erase coverage extension.

GDPR Art. 17 right-to-erasure already covers world-model state via
``maverick erase --channel X --user Y``. This module extends that to
the audit log: scrub or tombstone audit events tied to the same user
identity.

Two modes:

  - ``scrub_user(channel, user_id)``: rewrites matching lines to a
    tombstone form, preserving the row count and timestamps but
    removing identifying payload fields. Default behavior.
  - ``delete_user(channel, user_id)``: removes matching lines entirely.
    More aggressive; use when you need the audit log to look like the
    user never existed.

Both walk every `*.ndjson` file in ``~/.maverick/audit/``. They never
modify files mid-write — they write to a temp file and atomically
rename.

Matching: an event matches a user iff its payload contains
``channel`` AND ``user_id`` keys equal to the args (or
``channel:user_id`` appears in any string field).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .writer import DEFAULT_AUDIT_DIR

log = logging.getLogger(__name__)


def _subject_digest(channel: str, user_id: str) -> str:
    """Return a short, non-reversible identifier for erase log messages."""
    return hashlib.sha256(f"{channel}:{user_id}".encode()).hexdigest()[:16]


def _event_matches(event: dict, channel: str, user_id: str) -> bool:
    if event.get("channel") == channel and event.get("user_id") == user_id:
        return True
    target = f"{channel}:{user_id}"
    for v in event.values():
        if isinstance(v, str) and target in v:
            return True
    return False


def _tombstone(event: dict, channel: str, user_id: str) -> dict:
    """Replace identifying fields with [REDACTED]. Keep ts + kind."""
    keep = {"v", "ts", "kind", "schema_version"}
    out = {k: v for k, v in event.items() if k in keep}
    out["agent"] = "[REDACTED]"
    out["channel"] = channel  # keep so audit still reports who-was-scrubbed
    out["user_id"] = "[REDACTED]"
    out["erased_at"] = __import__("time").time()
    return out


def _process_file(
    path: Path,
    channel: str,
    user_id: str,
    *,
    delete: bool,
) -> tuple[int, int]:
    """Walk a single audit-log file. Returns (matched, written)."""
    if not path.exists() or path.is_dir():
        return 0, 0
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("audit erase: %s: %s", path, e)
        return 0, 0

    rows: list[tuple[str, dict | None]] = []
    matched = 0
    any_signed = False
    for raw in original.splitlines(keepends=True):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            rows.append((raw, None))
            continue
        if event.get("sig") and event.get("hash") and event.get("key_id"):
            any_signed = True
        if _event_matches(event, channel, user_id):
            matched += 1
        rows.append((raw, event))

    if matched == 0:
        return 0, len(rows)

    # If this is a signed audit file, validate it before making the authorized
    # erase mutation. Re-anchoring after the rewrite may only bless changes we
    # just made to a previously clean chain, never unrelated old tampering.
    if any_signed:
        try:
            from .signing import verify_chain

            breaks = verify_chain(path)
        except Exception as e:  # pragma: no cover - defensive/crypto missing
            log.warning("audit erase: could not verify %s before rewrite: %s", path, e)
            return 0, len(rows)
        if breaks:
            log.warning(
                "audit erase: refusing to rewrite %s; signed chain is not clean (%s)",
                path,
                breaks[0],
            )
            return 0, len(rows)

    tmp = path.with_suffix(".ndjson.erasetmp")
    written = 0
    try:
        with open(tmp, "w", encoding="utf-8") as dst:
            for raw, event in rows:
                if event is None:
                    dst.write(raw)
                    written += 1
                    continue
                if not _event_matches(event, channel, user_id):
                    dst.write(raw)
                    written += 1
                    continue
                if delete:
                    continue
                dst.write(json.dumps(_tombstone(event, channel, user_id), default=str) + "\n")
                written += 1
        # Preserve perms.
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
        tmp.replace(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
        if any_signed:
            try:
                from .signing import reanchor_day_after_erase, reanchor_file

                reanchor_file(path, force=True, preverified=True)
                # The rewrite changed the file's tip hash -> append a fresh
                # superseding tip-ledger anchor so verify_anchors matches the
                # new state (the prior anchor stays, recording the change).
                reanchor_day_after_erase(path.parent, path)
            except Exception as e:  # pragma: no cover - defensive/crypto missing
                log.warning("audit erase: could not reanchor %s after rewrite: %s", path, e)
    except OSError as e:
        log.warning("audit erase: %s: %s", path, e)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return 0, 0
    return matched, written


def scrub_user(
    channel: str,
    user_id: str,
    *,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> tuple[int, int]:
    """Replace matching events with tombstones. Returns (matched, scanned)."""
    total_matched = 0
    total_scanned = 0
    if not audit_dir.exists():
        return 0, 0
    for path in sorted(audit_dir.glob("*.ndjson")):
        m, w = _process_file(path, channel, user_id, delete=False)
        total_matched += m
        total_scanned += w
    log.info(
        "audit erase (scrub): subject_hash=%s matched=%d scanned=%d",
        _subject_digest(channel, user_id),
        total_matched,
        total_scanned,
    )
    return total_matched, total_scanned


def delete_user(
    channel: str,
    user_id: str,
    *,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> tuple[int, int]:
    """Delete matching events entirely. Returns (deleted, scanned)."""
    total_matched = 0
    total_scanned = 0
    if not audit_dir.exists():
        return 0, 0
    for path in sorted(audit_dir.glob("*.ndjson")):
        m, w = _process_file(path, channel, user_id, delete=True)
        total_matched += m
        total_scanned += w
    log.info(
        "audit erase (delete): subject_hash=%s matched=%d scanned=%d",
        _subject_digest(channel, user_id),
        total_matched,
        total_scanned,
    )
    return total_matched, total_scanned


__all__ = ["scrub_user", "delete_user"]
