"""Two-person rule tool (roadmap: 2027 H1 safety — "two-person rule for irreversible ops").

Validates dual-control (four-eyes) sign-off on an irreversible/high-impact
action: are there at least N *distinct* approvers who are not the requester
(separation of duties), optionally spanning distinct roles? Deterministic and
offline — the caller passes the action, the requester, and the collected
sign-offs; this returns SATISFIED / BLOCKED with the reason.

ops:
  - check(signoffs[, requester][, min_approvers][, require_distinct_roles])
"""
from __future__ import annotations

from typing import Any

from . import Tool


def _check(args: dict[str, Any]) -> str:
    signoffs = args.get("signoffs")
    if not isinstance(signoffs, list):
        return "ERROR: signoffs must be an array of {approver[, role]}"
    requester = str(args.get("requester") or "").strip().lower()
    try:
        need = int(args.get("min_approvers", 2))
    except (TypeError, ValueError):
        need = 2
    need = max(1, need)
    require_roles = bool(args.get("require_distinct_roles", False))

    valid_approvers: set[str] = set()
    valid_roles: set[str] = set()
    self_approved = False
    for s in signoffs:
        if not isinstance(s, dict):
            continue
        who = str(s.get("approver") or "").strip().lower()
        if not who:
            continue
        if who == requester:
            self_approved = True
            continue  # separation of duties: requester can't approve their own action
        valid_approvers.add(who)
        role = str(s.get("role") or "").strip().lower()
        if role:
            valid_roles.add(role)

    notes = []
    if self_approved:
        notes.append("requester's own sign-off was excluded (separation of duties)")

    if len(valid_approvers) < need:
        reason = f"{len(valid_approvers)} distinct approver(s), need {need}"
        return _result("BLOCKED", reason, notes)
    if require_roles and len(valid_roles) < need:
        reason = f"{len(valid_roles)} distinct role(s) among approvers, need {need}"
        return _result("BLOCKED", reason, notes)

    detail = f"{len(valid_approvers)} distinct approver(s)"
    if require_roles:
        detail += f", {len(valid_roles)} distinct role(s)"
    return _result("SATISFIED", detail, notes)


def _result(verdict: str, reason: str, notes: list[str]) -> str:
    out = f"{verdict}: {reason}"
    if notes:
        out += "\n" + "\n".join(f"- {n}" for n in notes)
    return out


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "check"):
        return f"ERROR: unknown op {args.get('op')!r}"
    if not isinstance(args.get("signoffs"), list):
        return "ERROR: signoffs (array of {approver[, role]}) is required"
    return _check(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["check"]},
        "signoffs": {
            "type": "array",
            "description": "collected approvals; each {approver, role?}",
            "items": {
                "type": "object",
                "properties": {
                    "approver": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["approver"],
            },
        },
        "requester": {"type": "string", "description": "who requested the action (excluded from approvers)"},
        "min_approvers": {"type": "integer", "description": "distinct approvers required (default 2)"},
        "require_distinct_roles": {"type": "boolean", "description": "also require that many distinct roles"},
    },
    "required": ["signoffs"],
}


def two_person_rule() -> Tool:
    return Tool(
        name="two_person_rule",
        description=(
            "Validate dual-control (four-eyes) sign-off on an irreversible "
            "action. op=check with 'signoffs' (each {approver, role?}), optional "
            "'requester' (excluded from approvers — separation of duties), "
            "'min_approvers' (default 2), and 'require_distinct_roles'. Returns "
            "SATISFIED/BLOCKED with the reason. Deterministic, offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
