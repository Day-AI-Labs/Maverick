"""Coordinated-disclosure log (roadmap: 2027 H1 safety).

A small, offline ledger for running a coordinated vulnerability disclosure
(CVD) process: record a report, compute its embargo window, and render a
public advisory. Deterministic date arithmetic, no network, no DB -- the
caller persists the list of entries however it likes and passes it back in.

ops:
  - status(reported, embargo_days[, today])  — compute the disclosure date
    and whether the embargo is OPEN or EXPIRED relative to 'today'.
  - advisory(id, severity, summary, reported, embargo_days[, today, ...])
    — render a coordinated-disclosure advisory block.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import Tool

_SEVERITIES = ("low", "medium", "high", "critical")


def _parse_date(value: Any, field: str) -> tuple[date | None, str]:
    if not isinstance(value, str):
        return None, f"ERROR: {field} must be an ISO date string (YYYY-MM-DD)"
    try:
        return date.fromisoformat(value), ""
    except ValueError:
        return None, f"ERROR: {field} is not a valid ISO date (YYYY-MM-DD): {value!r}"


def _embargo_days(value: Any) -> tuple[int | None, str]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, "ERROR: embargo_days must be an integer >= 0"
    return value, ""


def _window(args: dict[str, Any]) -> tuple[date, date, date, str]:
    reported, err = _parse_date(args.get("reported"), "reported")
    if err:
        return date.min, date.min, date.min, err
    days, err = _embargo_days(args.get("embargo_days"))
    if err:
        return date.min, date.min, date.min, err
    assert reported is not None and days is not None
    disclose = reported + timedelta(days=days)
    if "today" in args:
        today, err = _parse_date(args.get("today"), "today")
        if err:
            return date.min, date.min, date.min, err
        assert today is not None
    else:
        today = date.today()
    return reported, disclose, today, ""


def _status(args: dict[str, Any]) -> str:
    reported, disclose, today, err = _window(args)
    if err:
        return err
    remaining = (disclose - today).days
    state = "EXPIRED" if today >= disclose else "OPEN"
    lines = [
        f"reported: {reported.isoformat()}",
        f"disclose-on: {disclose.isoformat()}",
        f"today: {today.isoformat()}",
        f"embargo: {state}",
    ]
    if state == "OPEN":
        lines.append(f"days-remaining: {remaining}")
    return "\n".join(lines)


def _advisory(args: dict[str, Any]) -> str:
    for req in ("id", "summary"):
        if not args.get(req):
            return f"ERROR: {req} is required for advisory"
    severity = str(args.get("severity", "")).lower()
    if severity not in _SEVERITIES:
        return f"ERROR: severity must be one of {', '.join(_SEVERITIES)}"
    reported, disclose, today, err = _window(args)
    if err:
        return err
    state = "EXPIRED" if today >= disclose else "OPEN"
    lines = [
        f"# Advisory {args['id']}  [{severity.upper()}]",
        f"Summary: {args['summary']}",
        f"Reported: {reported.isoformat()}",
        f"Coordinated-disclosure date: {disclose.isoformat()} (embargo {state})",
    ]
    if args.get("reporter"):
        lines.append(f"Reporter: {args['reporter']}")
    if args.get("fixed_in"):
        lines.append(f"Fixed in: {args['fixed_in']}")
    if args.get("cve"):
        lines.append(f"CVE: {args['cve']}")
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if op == "status":
        return _status(args)
    if op == "advisory":
        return _advisory(args)
    return f"ERROR: unknown op {op!r} (expected 'status' or 'advisory')"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["status", "advisory"]},
        "id": {"type": "string", "description": "advisory id (advisory op)"},
        "severity": {"type": "string", "enum": list(_SEVERITIES)},
        "summary": {"type": "string"},
        "reported": {"type": "string", "description": "ISO date the issue was reported"},
        "embargo_days": {"type": "integer", "description": "embargo length in days (>=0)"},
        "today": {"type": "string", "description": "ISO date to evaluate against (default: today)"},
        "reporter": {"type": "string"},
        "fixed_in": {"type": "string"},
        "cve": {"type": "string"},
    },
    "required": ["op", "reported", "embargo_days"],
}


def coordinated_disclosure() -> Tool:
    return Tool(
        name="coordinated_disclosure",
        description=(
            "Run a coordinated vulnerability disclosure (CVD) timeline offline. "
            "op=status computes the disclosure date and OPEN/EXPIRED embargo "
            "state from 'reported' + 'embargo_days'. op=advisory renders an "
            "advisory block (needs id, severity, summary). Deterministic date "
            "math; no network."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
