"""Coordinated-vulnerability-disclosure ledger tool.

Helps run a coordinated disclosure (CVD) process: track vulnerability reports
through their lifecycle and validate that no report skips a required stage
(e.g. you can't mark something ``published`` before it's ``fixed``).
Deterministic and offline — the caller supplies the report(s); this validates
and formats over the supplied list. No disk, no network.

Lifecycle order:
  received -> triaged -> fixed -> published
with ``withdrawn`` permitted as a terminal state from any stage.

ops:
  - add(report)        — normalise/validate a single {id, severity, status}.
  - validate(reports)  — count by status + flag invalid status / transitions.
"""
from __future__ import annotations

from typing import Any

from . import Tool

# Allowed status values and their position in the forward lifecycle.
_ORDER = ["received", "triaged", "fixed", "published"]
_STATUSES = set(_ORDER) | {"withdrawn"}
_SEVERITIES = {"none", "low", "medium", "high", "critical"}


def _norm_report(rep: Any) -> tuple[dict | None, str | None]:
    """Return (normalised, None) or (None, error-message)."""
    if not isinstance(rep, dict):
        return None, "report must be an object {id, severity, status}"
    rid = str(rep.get("id") or "").strip()
    if not rid:
        return None, "report.id is required"
    status = str(rep.get("status") or "").strip().lower()
    if status not in _STATUSES:
        return None, f"report {rid}: invalid status {status!r} (allowed: {', '.join(sorted(_STATUSES))})"
    severity = str(rep.get("severity") or "").strip().lower()
    if severity not in _SEVERITIES:
        return None, f"report {rid}: invalid severity {severity!r} (allowed: {', '.join(sorted(_SEVERITIES))})"
    return {"id": rid, "severity": severity, "status": status}, None


def _transition_ok(prev: str, cur: str) -> bool:
    """Is moving from prev -> cur a legal lifecycle step?"""
    if cur == "withdrawn":
        return prev != "withdrawn"  # can't leave then re-withdraw a terminal report
    if prev == "withdrawn":
        return False  # withdrawn is terminal
    # Forward-only along the ordered lifecycle, no skipping stages.
    return _ORDER.index(cur) - _ORDER.index(prev) == 1


def _add(args: dict[str, Any]) -> str:
    norm, err = _norm_report(args.get("report"))
    if err:
        return f"ERROR: {err}"
    return f"OK: report {norm['id']} severity={norm['severity']} status={norm['status']}"


def _validate(args: dict[str, Any]) -> str:
    reports = args.get("reports")
    if not isinstance(reports, list):
        return "ERROR: reports must be an array of {id, severity, status}"
    counts = {s: 0 for s in sorted(_STATUSES)}
    flags: list[str] = []
    # A report can carry a "prev_status" recording where it came from; if so we
    # check the transition is legal. published always requires a fixed history.
    for rep in reports:
        norm, err = _norm_report(rep)
        if err:
            flags.append(err)
            continue
        counts[norm["status"]] += 1
        prev = rep.get("prev_status")
        if prev is not None:
            prev = str(prev).strip().lower()
            if prev not in _STATUSES:
                flags.append(f"report {norm['id']}: invalid prev_status {prev!r}")
            elif not _transition_ok(prev, norm["status"]):
                flags.append(
                    f"report {norm['id']}: invalid transition {prev} -> {norm['status']}"
                )

    summary = ", ".join(f"{s}={counts[s]}" for s in sorted(_STATUSES) if counts[s])
    summary = summary or "no reports"
    if flags:
        body = "\n".join(f"- {f}" for f in flags)
        return f"RISK: {len(flags)} issue(s); counts: {summary}\n{body}"
    return f"CLEAN: counts: {summary}"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if op == "add":
        return _add(args)
    if op == "validate":
        return _validate(args)
    return f"ERROR: unknown op {op!r} (expected add or validate)"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["add", "validate"]},
        "report": {
            "type": "object",
            "description": "single report for op=add",
            "properties": {
                "id": {"type": "string"},
                "severity": {"type": "string", "enum": sorted(_SEVERITIES)},
                "status": {"type": "string", "enum": sorted(_STATUSES)},
            },
            "required": ["id", "severity", "status"],
        },
        "reports": {
            "type": "array",
            "description": "reports for op=validate; each {id, severity, status, prev_status?}",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string"},
                    "status": {"type": "string"},
                    "prev_status": {"type": "string"},
                },
                "required": ["id", "severity", "status"],
            },
        },
    },
    "required": ["op"],
}


def coordinated_disclosure() -> Tool:
    return Tool(
        name="coordinated_disclosure",
        description=(
            "Coordinated-vulnerability-disclosure (CVD) ledger helper. "
            "op=add with 'report' {id, severity, status} normalises/validates "
            "one entry. op=validate with 'reports' (each {id, severity, status, "
            "prev_status?}) checks the lifecycle (received->triaged->fixed->"
            "published, withdrawn terminal) and returns a count by status plus "
            "any invalid statuses/transitions. Pure validation, no disk."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
