"""Agent-attack hunter -- sweep the audit trail for attacks by or against agents.

Every safety-relevant thing an agent does or has done to it lands in the audit
log: the shield blocking a prompt injection, the egress lock refusing a cloud
call (an exfiltration attempt), a sub-agent denied for trying to exceed its
capability grant, a governance policy firing, the kill switch. This module sweeps
that trail and aggregates those signals into a risk-rated **threat report** --
"search everywhere agents leave a trace, and surface the attacks."

The audit log is already secret-redacted before write, and only event *metadata*
(kind / agent / goal / provider / tool / reason) is summarised here -- never
payload content. Fail-soft like the audit reader it builds on.

Surfaced as ``maverick hunt`` and (next) the threat-hunter agent that investigates
each finding.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

# Audit event kinds that signal a security event, with a description + severity.
# Each is an attack *by* an agent (exfiltration, escalation) or *against* one
# (injection), or a control firing in response.
_INDICATORS: dict[str, tuple[str, str]] = {
    "shield_block": (
        "Shield blocked unsafe content (prompt injection / jailbreak / policy)",
        "high"),
    "egress_blocked": (
        "Exfiltration attempt: an egress to a non-local provider was blocked",
        "high"),
    "capability_denied": (
        "Privilege escalation: an agent tried to exceed its capability grant",
        "high"),
    "governance_denied": (
        "Governance policy denied an action", "medium"),
    "halt": (
        "Kill switch engaged (HALT)", "medium"),
    "secret_redacted": (
        "Secret detected and redacted before write", "low"),
}
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_SAMPLE_KEYS = (
    "kind", "agent", "ts", "goal_id", "provider", "tool", "reason", "rule", "detail",
)


@dataclass
class ThreatFinding:
    kind: str
    title: str
    severity: str
    count: int
    agents: list[str]
    last_seen: float
    samples: list[dict] = field(default_factory=list)


@dataclass
class ThreatReport:
    findings: list[ThreatFinding]
    events_scanned: int
    risk_rating: str          # "high" | "medium" | "low" | "clear"


def _sample(event: dict) -> dict:
    """A compact, redaction-safe summary of one event (metadata only)."""
    return {k: event[k] for k in _SAMPLE_KEYS if k in event}


def _rollup(findings: list[ThreatFinding]) -> str:
    if not findings:
        return "clear"
    top = max(_SEVERITY_RANK.get(f.severity, 1) for f in findings)
    return {3: "high", 2: "medium", 1: "low"}[top]


def hunt(*, all_days: bool = True, since: str | None = None,
         until: str | None = None, tenant: str | None = None) -> ThreatReport:
    """Sweep the audit trail and aggregate the attack signals into a report.

    Defaults to every day-file (``all_days``); pass ``since``/``until`` (UTC
    ``YYYY-MM-DD``) to bound the window. Never raises -- a missing/unreadable log
    yields an empty, ``clear`` report.
    """
    from .audit.export import iter_audit_events

    buckets: dict[str, dict] = {}
    scanned = 0
    try:
        events = iter_audit_events(
            all_days=all_days, since=since, until=until, tenant=tenant,
        )
        for ev in events:
            scanned += 1
            kind = ev.get("kind")
            if kind not in _INDICATORS:
                continue
            b = buckets.setdefault(
                kind, {"count": 0, "agents": set(), "last": 0.0, "samples": []})
            b["count"] += 1
            b["agents"].add(str(ev.get("agent", "system")))
            ts = float(ev.get("ts") or 0.0)
            b["last"] = max(b["last"], ts)
            if len(b["samples"]) < 3:
                b["samples"].append(_sample(ev))
    except Exception:  # noqa: BLE001 -- a hunt must never crash on a bad log
        pass

    findings = [
        ThreatFinding(
            kind=kind,
            title=_INDICATORS[kind][0],
            severity=_INDICATORS[kind][1],
            count=b["count"],
            agents=sorted(b["agents"]),
            last_seen=b["last"],
            samples=b["samples"],
        )
        for kind, b in buckets.items()
    ]
    findings.sort(key=lambda f: (_SEVERITY_RANK[f.severity], f.count), reverse=True)
    return ThreatReport(findings, scanned, _rollup(findings))


def render_report_json(report: ThreatReport) -> str:
    import json
    return json.dumps(asdict(report), indent=2, default=str)


def render_report_text(report: ThreatReport) -> str:
    head = "Agent threat hunt"
    lines = [
        head, "=" * len(head), "",
        f"Risk: {report.risk_rating.upper()}  "
        f"({report.events_scanned} audit event(s) scanned, "
        f"{len(report.findings)} signal type(s))",
        "",
    ]
    if not report.findings:
        lines.append("No attack signals found in the audit trail.")
        return "\n".join(lines)
    for f in report.findings:
        when = (
            time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(f.last_seen))
            if f.last_seen else "?"
        )
        lines.append(f"  [{f.severity.upper()}] {f.title}")
        lines.append(
            f"      {f.count} event(s); agents: {', '.join(f.agents) or '?'}; "
            f"last {when}")
    return "\n".join(lines)


__all__ = [
    "ThreatFinding",
    "ThreatReport",
    "hunt",
    "render_report_json",
    "render_report_text",
]
