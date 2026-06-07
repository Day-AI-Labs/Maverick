"""Export audit events for SIEM ingestion.

Reads the tamper-evident NDJSON audit log and re-emits each event as
either compact JSON (one event per line) or ArcSight CEF, ready to ship
to a SIEM (Splunk, Sentinel, QRadar, ...). Read-only: it never mutates
the log or touches the signing chain.

Event shape and tenant-aware path resolution are reused from the writer
(:class:`maverick.audit.writer.AuditLog`) via :func:`maverick.paths.data_dir`.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# CEF severity (0-10). Default low; bump for denial/halt/block kinds so a
# SIEM correlation rule can alert on the dangerous ones without parsing
# every field.
_CEF_SEVERITY = {
    "shield_block": 7,
    "capability_denied": 7,
    "egress_blocked": 7,
    "halt": 9,
    "consent_result": 5,
    "secret_redacted": 5,
    "erase": 5,
}
_DEFAULT_SEVERITY = 2


def _audit_version() -> str:
    try:
        from .. import __version__

        return str(__version__)
    except Exception:
        return "0"


def audit_event_paths(
    *, day: str | None = None, all_days: bool = False,
    since: str | None = None, until: str | None = None,
    tenant: str | None = None,
) -> list[Path]:
    """Return tenant-aware audit day-files selected for export."""
    from ..paths import data_dir

    audit_dir = data_dir("audit", tenant=tenant) if tenant else data_dir("audit")
    if not audit_dir.exists() or not audit_dir.is_dir():
        return []

    if since or until:
        # Inclusive [since, until] window over day-file dates. ISO YYYY-MM-DD
        # sorts lexically, so a plain string compare on the file stem works.
        lo = since or "0000-00-00"
        hi = until or "9999-99-99"
        return [
            p for p in sorted(audit_dir.glob("*.ndjson"))
            if p.name != "anchors.ndjson" and lo <= p.stem <= hi
        ]
    if all_days:
        return [
            p for p in sorted(audit_dir.glob("*.ndjson")) if p.name != "anchors.ndjson"
        ]

    d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    return [audit_dir / f"{d}.ndjson"]


def iter_audit_events(
    *, day: str | None = None, all_days: bool = False,
    since: str | None = None, until: str | None = None,
    tenant: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield audit event dicts from the tenant-aware audit dir.

    Selection precedence: a ``since``/``until`` window (inclusive, over day-file
    dates) wins; then ``all_days`` sweeps every ``*.ndjson`` day-file except the
    cross-file ``anchors.ndjson`` tip-ledger (matching ``audit verify``);
    otherwise a single day-file is read (``day`` or today, UTC).
    Malformed/unreadable lines and a missing dir are skipped silently
    (fail-soft).
    """
    paths = audit_event_paths(
        day=day, all_days=all_days, since=since, until=until, tenant=tenant,
    )

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def to_jsonl(event: dict[str, Any]) -> str:
    """A compact, stable JSON line for one event."""
    return json.dumps(event, default=str, sort_keys=True, separators=(",", ":"))


def _cef_escape(value: str) -> str:
    """Escape a CEF extension value: backslash, equals, and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def to_cef(event: dict[str, Any]) -> str:
    """Render one event as an ArcSight CEF line.

    ``CEF:0|Maverick|maverick-agent|<version>|<kind>|<kind>|<sev>|<extensions>``
    where extensions are space-separated ``key=value`` of the event's scalar
    fields (CEF-escaped). Non-scalar fields (dicts/lists) are skipped.
    """
    kind = str(event.get("kind", "event"))
    severity = _CEF_SEVERITY.get(kind, _DEFAULT_SEVERITY)
    header = f"CEF:0|Maverick|maverick-agent|{_audit_version()}|{kind}|{kind}|{severity}|"
    parts = []
    for key, val in event.items():
        if isinstance(val, bool) or isinstance(val, (str, int, float)) or val is None:
            parts.append(f"{_cef_escape(str(key))}={_cef_escape(str(val))}")
    return header + " ".join(parts)
