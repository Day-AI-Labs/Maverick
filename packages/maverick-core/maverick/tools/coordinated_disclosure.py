"""Coordinated-disclosure timeline tracker (roadmap: 2027 H1 safety —
"coordinated-disclosure log").

Computes the disclosure status and deadline for a set of vulnerability reports
under a coordinated-disclosure policy: each report gets an embargo window from
its report date (90 days by default, optionally per-severity), after which
public disclosure is permitted. A report that is patched or already disclosed
short-circuits the clock. Pure date arithmetic — deterministic and offline.

ops:
  - status(records, [today], [policy], [embargo_days])  — per-report status
    (EMBARGOED / DUE_SOON / OVERDUE / PATCHED / DISCLOSED), deadline, and days
    remaining, plus a summary count. ``records`` is a list of
    ``{id, reported, [severity], [patched], [disclosed]}`` with ISO dates.
    ``policy`` is ``{severity: days, ...}`` (with optional ``default``);
    ``embargo_days`` sets a flat window when no policy is given. ``today``
    defaults to the system date.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import Tool

_DEFAULT_EMBARGO = 90
_DUE_SOON = 14  # days


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} is not a valid ISO date (YYYY-MM-DD): {value!r}")


def _embargo_for(severity: str | None, policy: dict, flat: int) -> int:
    if severity is not None and severity in policy:
        return int(policy[severity])
    if "default" in policy:
        return int(policy["default"])
    return flat


def _status(records: list, today: date, policy: dict, flat: int) -> str:
    rows = []
    for i, r in enumerate(records):
        if not isinstance(r, dict) or "id" not in r or "reported" not in r:
            return f"ERROR: record {i} needs at least 'id' and 'reported'"
        rid = str(r["id"])
        reported = _parse_date(r["reported"], f"record {rid} 'reported'")
        severity = r.get("severity")
        severity = None if severity is None else str(severity)
        window = _embargo_for(severity, policy, flat)
        if window < 0:
            return f"ERROR: record {rid} embargo window is negative ({window})"
        deadline = date.fromordinal(reported.toordinal() + window)
        remaining = deadline.toordinal() - today.toordinal()

        if r.get("disclosed"):
            d = _parse_date(r["disclosed"], f"record {rid} 'disclosed'")
            status, detail = "DISCLOSED", f"public on {d.isoformat()}"
        elif r.get("patched"):
            d = _parse_date(r["patched"], f"record {rid} 'patched'")
            status, detail = "PATCHED", f"fixed {d.isoformat()}; disclosure permitted"
        elif remaining < 0:
            status, detail = "OVERDUE", f"deadline {deadline.isoformat()} passed {-remaining}d ago; disclosure permitted"
        elif remaining <= _DUE_SOON:
            status, detail = "DUE_SOON", f"{remaining}d to deadline {deadline.isoformat()}"
        else:
            status, detail = "EMBARGOED", f"{remaining}d to deadline {deadline.isoformat()}"
        rows.append((rid, status, detail))

    order = {"OVERDUE": 0, "DUE_SOON": 1, "EMBARGOED": 2, "PATCHED": 3, "DISCLOSED": 4}
    rows.sort(key=lambda x: (order.get(x[1], 9), x[0]))

    counts: dict[str, int] = {}
    for _, status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in sorted(counts, key=lambda s: order.get(s, 9)))

    lines = [f"as of {today.isoformat()}: {summary}"]
    for rid, status, detail in rows:
        lines.append(f"  [{status}] {rid}: {detail}")
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "status"):
        return f"ERROR: unknown op {args.get('op')!r}"
    records = args.get("records")
    if not isinstance(records, list):
        return "ERROR: records must be an array of {id, reported, ...}"
    policy = args.get("policy", {})
    if not isinstance(policy, dict):
        return "ERROR: policy must be an object {severity: days}"
    flat = args.get("embargo_days", _DEFAULT_EMBARGO)
    try:
        flat = int(flat)
    except (TypeError, ValueError):
        return "ERROR: embargo_days must be an integer"
    if flat < 0:
        return "ERROR: embargo_days must be non-negative"
    today_arg = args.get("today")
    try:
        today = _parse_date(today_arg, "today") if today_arg is not None else date.today()
        for k in policy:
            int(policy[k])
        return _status(records, today, policy, flat)
    except ValueError as e:
        return f"ERROR: {e}"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["status"]},
        "records": {
            "type": "array",
            "description": "vulnerability reports; each {id, reported, [severity], [patched], [disclosed]} with ISO dates",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reported": {"type": "string"},
                    "severity": {"type": "string"},
                    "patched": {"type": "string"},
                    "disclosed": {"type": "string"},
                },
                "required": ["id", "reported"],
            },
        },
        "policy": {
            "type": "object",
            "description": "severity -> embargo days (optional 'default' key)",
        },
        "embargo_days": {
            "type": "integer",
            "description": f"flat embargo window when no policy given (default {_DEFAULT_EMBARGO})",
        },
        "today": {"type": "string", "description": "ISO date to evaluate against; defaults to system date"},
    },
    "required": ["records"],
}


def coordinated_disclosure() -> Tool:
    return Tool(
        name="coordinated_disclosure",
        description=(
            "Track coordinated vulnerability disclosure timelines. op=status with "
            "'records' ([{id, reported, [severity], [patched], [disclosed]}], ISO "
            "dates). Applies an embargo window (90d default, or per-severity "
            "'policy' / flat 'embargo_days') from each report date and reports "
            "EMBARGOED / DUE_SOON / OVERDUE / PATCHED / DISCLOSED with the deadline "
            "and days remaining, plus a summary. Deterministic, offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
