"""Security remediation -- assess the deployment's posture and (bounded) fix it.

The security assessor's engine. It reads the live security posture (control gaps
from :func:`maverick.compliance.compliance_report`, active breach signals from
:func:`maverick.threat_hunt.hunt`) and maps each gap to the remediation that
closes it. Some remediations are **auto-fixable** -- a reversible, in-boundary
flip of *Maverick's own* config (enable audit signing, set retention) -- and the
rest are **gated**: behaviour-changing (enterprise mode, at-rest encryption) or
outward-facing, so they are *proposed* for a human, never auto-applied.

Two hard guards on every auto-fix, both off by default:
  1. it runs only under **enterprise mode + an explicit opt-in**
     (``[security] auto_fix = true`` / ``MAVERICK_SECURITY_AUTOFIX=1``);
  2. it only ever **appends** a config block when that section is absent (the
     least-destructive write -- it never edits or clobbers a hand-edited section).
Every applied fix is recorded as a ``config_remediated`` audit event and reports
how to undo it. ``apply`` defaults to a dry run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Remediation:
    control: str                     # the compliance control it closes
    title: str
    section: str                     # the config.toml table it writes
    changes: dict[str, Any]
    auto: bool                       # True = low-risk reversible auto-fix; False = gated
    rationale: str


# Each action-needed control -> its remediation. ``auto`` is reserved for
# reversible, in-boundary flips that cannot break a running workflow; anything
# that changes LLM routing, data handling, or consent behaviour is gated.
_REMEDIATIONS: tuple[Remediation, ...] = (
    Remediation(
        "Tamper-evident audit", "Enable Ed25519 audit signing",
        "audit", {"sign": True}, auto=True,
        rationale="reversible flag; makes the audit log tamper-evident "
                  "(EU AI Act Art. 12 / SOC 2)"),
    Remediation(
        "Storage limitation (retention)", "Set data-retention windows",
        "retention", {"audit_days": 365, "episodes_days": 90, "events_days": 365},
        auto=True,
        rationale="reversible; bounds retention (GDPR Art. 5(1)(e)) without "
                  "changing agent behaviour"),
    Remediation(
        "Data-egress control", "Enable enterprise mode (egress lock)",
        "enterprise", {"mode": True}, auto=False,
        rationale="pins LLM calls to local models -- can break a cloud workflow, "
                  "so propose for human review, do not auto-apply"),
    Remediation(
        "Encryption at rest", "Enable at-rest encryption",
        "encryption", {"at_rest": True}, auto=False,
        rationale="changes data handling (new writes sealed); propose for review"),
    Remediation(
        "Human oversight (consent gating)", "Gate destructive actions (consent ask)",
        "enterprise", {"mode": True}, auto=False,
        rationale="gates destructive actions -- can block non-interactive runs; "
                  "propose for review"),
)
_BY_CONTROL = {r.control: r for r in _REMEDIATIONS}


@dataclass
class RemediationItem:
    control: str
    title: str
    auto: bool
    section: str
    changes: dict[str, Any]
    rationale: str
    detail: str


@dataclass
class RemediationPlan:
    gaps: list[RemediationItem]
    breaches: list[dict]              # active attack signals from the threat hunt
    auto_fix_enabled: bool


@dataclass
class ApplyResult:
    control: str
    applied: bool
    dry_run: bool = False
    reason: str = ""
    block: str = ""                  # the config block added / that would be added
    undo: str = ""


def _truthy(v: object) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def auto_fix_enabled() -> bool:
    """Off by default. Auto-fix requires enterprise mode AND an explicit opt-in
    (``MAVERICK_SECURITY_AUTOFIX`` env wins over ``[security] auto_fix``)."""
    try:
        from .enterprise import enterprise_enabled
        if not enterprise_enabled():
            return False
    except Exception:
        return False
    env = os.environ.get("MAVERICK_SECURITY_AUTOFIX")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .config import load_config
        return _truthy(((load_config() or {}).get("security") or {}).get("auto_fix"))
    except Exception:
        return False


def plan(*, include_breaches: bool = True) -> RemediationPlan:
    """Assess the security posture: control gaps (each mapped to its remediation)
    plus active breach signals. Read-only; never raises."""
    gaps: list[RemediationItem] = []
    try:
        from .compliance import compliance_report
        for c in compliance_report():
            rem = _BY_CONTROL.get(c.control)
            if c.status == "action_needed" and rem is not None:
                gaps.append(RemediationItem(
                    control=c.control, title=rem.title, auto=rem.auto,
                    section=rem.section, changes=dict(rem.changes),
                    rationale=rem.rationale, detail=c.detail,
                ))
    except Exception:
        pass
    breaches: list[dict] = []
    if include_breaches:
        try:
            from .threat_hunt import hunt
            breaches = [
                {"kind": f.kind, "title": f.title, "severity": f.severity,
                 "count": f.count}
                for f in hunt().findings
            ]
        except Exception:
            pass
    return RemediationPlan(gaps=gaps, breaches=breaches,
                           auto_fix_enabled=auto_fix_enabled())


def _toml_scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_block(section: str, changes: dict[str, Any]) -> str:
    lines = [f"[{section}]"]
    lines += [f"{k} = {_toml_scalar(v)}" for k, v in changes.items()]
    return "\n".join(lines) + "\n"


def apply_remediation(item: RemediationItem, *, dry_run: bool = True) -> ApplyResult:
    """Apply one auto-fix (append its config block), or report why it was refused.

    Refuses -- never writes -- unless the item is ``auto``, auto-fix is enabled
    (enterprise + opt-in), and the target section is **absent** from config (so the
    append cannot clobber an existing hand-edited table). ``dry_run`` reports the
    block without writing. A real apply records a ``config_remediated`` audit event.
    """
    if not item.auto:
        return ApplyResult(item.control, False,
                           reason="gated -- propose for human review, not auto-applied")
    if not auto_fix_enabled():
        return ApplyResult(
            item.control, False,
            reason="auto-fix disabled (needs enterprise mode + "
                   "[security] auto_fix = true)")
    block = _emit_block(item.section, item.changes)
    try:
        from .config import config_path, load_config
        cfg = load_config() or {}
        if item.section in cfg:
            return ApplyResult(
                item.control, False, block=block,
                reason=f"[{item.section}] already present -- apply by hand to avoid "
                       "clobbering existing keys")
        path = config_path()
    except Exception as e:
        return ApplyResult(item.control, False, reason=f"could not read config: {e}")

    if dry_run:
        return ApplyResult(item.control, False, dry_run=True, block=block,
                           undo=f"remove the appended [{item.section}] block")
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        joined = (existing.rstrip() + "\n\n" + block) if existing.strip() else block
        path.write_text(joined, encoding="utf-8")
    except OSError as e:
        return ApplyResult(item.control, False, reason=f"could not write config: {e}")
    try:  # audit -- best-effort, must not fail the apply
        from .audit import EventKind, record
        record(EventKind.CONFIG_REMEDIATED, agent="security_assessor",
               section=item.section, control=item.control)
    except Exception:
        pass
    return ApplyResult(item.control, True, block=block,
                       undo=f"remove the appended [{item.section}] block from {path}")


def render_plan_text(plan_: RemediationPlan) -> str:
    lines = ["Security remediation plan", "=" * 25, ""]
    if plan_.breaches:
        lines.append("Active breach signals (from the threat hunt):")
        for b in plan_.breaches:
            lines.append(f"  [{b['severity'].upper()}] {b['title']} (x{b['count']})")
        lines.append("")
    auto = [g for g in plan_.gaps if g.auto]
    gated = [g for g in plan_.gaps if not g.auto]
    if not plan_.gaps:
        lines.append("No control gaps -- posture is clean.")
    if auto:
        state = "ENABLED" if plan_.auto_fix_enabled else "disabled"
        lines.append(f"Auto-fixable (low-risk, reversible; auto-fix is {state}):")
        for g in auto:
            mark = "will apply" if plan_.auto_fix_enabled else "run with auto-fix on"
            lines.append(f"  [{mark}] {g.title}  ->  [{g.section}] {g.changes}")
    if gated:
        lines.append("")
        lines.append("Proposed (gated -- needs human approval):")
        for g in gated:
            lines.append(f"  - {g.title}  ({g.rationale})")
    return "\n".join(lines)


def render_plan_json(plan_: RemediationPlan) -> str:
    import json
    from dataclasses import asdict
    return json.dumps(asdict(plan_), indent=2, default=str)


__all__ = [
    "Remediation",
    "RemediationItem",
    "RemediationPlan",
    "ApplyResult",
    "auto_fix_enabled",
    "plan",
    "apply_remediation",
    "render_plan_text",
    "render_plan_json",
]
