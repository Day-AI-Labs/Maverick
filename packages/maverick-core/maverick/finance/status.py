"""Finance posture report — the ``finance status`` view (finance-agent-suite §5).

Generalises ``compliance_report()`` to the finance control plane: it introspects
the deployment and reports which finance controls are actually live — SoD
cleanliness of the roster, the maker-checker gate on money movement, amount-aware
delegation-of-authority tiers, the tamper-evident book of record, sanctions
screening, read-only-by-default, encryption at rest, and the egress lock — plus
which compliance regimes are enabled. Honest framing: this is *control coverage*,
not an audit opinion (Maverick supplies the controls + evidence; humans post, pay,
file, and certify).
"""
from __future__ import annotations

import logging

from ..compliance import ControlCheck
from . import regimes as _regimes

log = logging.getLogger(__name__)

FINANCE_DISCLAIMER = (
    "Finance control-coverage report, not an audit opinion or a certification. "
    "Agents draft; humans post, pay, file, and certify. No agent attests to ICFR, "
    "signs a §302 certification, or files with the SEC/IRS."
)


def _money_gate_active() -> tuple[bool, str]:
    """Is every money/posting action gated to a human (config + regimes)?"""
    from ..governance import Policy
    from ..safety.tool_risk import risk_rank
    effective = _regimes.union_policies(
        [Policy.from_config(), _regimes.compile_policy(_regimes.configured_regimes())])
    floor_ok = (effective.require_human_min_risk is not None
                and risk_rank(effective.require_human_min_risk) <= risk_rank("high"))
    covered = set(effective.require_human_actions) | set(effective.deny_actions)
    missing = [a for a in _regimes._MONEY_ACTIONS if a not in covered]
    if floor_ok or not missing:
        return True, "money movement pauses for a human (require_human gate)"
    return False, ("set [governance] require_human_min_risk=\"high\" or enable a "
                   "finance regime (e.g. [finance] regimes=[\"sox\"]); ungated: "
                   + ", ".join(missing[:5]))


def _amount_tiers_active() -> tuple[bool, str]:
    from ..governance import Policy
    pol = _regimes.union_policies(
        [Policy.from_config(), _regimes.compile_policy(_regimes.configured_regimes())])
    on = bool(pol.require_human_above or pol.deny_above)
    return on, ("delegation-of-authority dollar tiers configured" if on
                else "set [governance] require_human_above / deny_above thresholds")


def _sod_active() -> tuple[bool, str]:
    from ..domain import builtin_dir, load_domains
    from .sod_linter import lint_roster
    packs = {n: p for n, p in load_domains(builtin_dir()).items()
             if n.startswith("finance_")}
    conflicts = lint_roster(packs)
    if conflicts:
        return False, f"{len(conflicts)} SoD conflict(s): {conflicts[0]}"
    return True, f"{len(packs)} finance packs are segregation-of-duties clean"


def _signing_active() -> tuple[bool, str]:
    try:
        from ..audit.writer import _resolve_signing
        if _resolve_signing(None):
            return True, "Ed25519 hash-chain on; verify with 'maverick audit verify'"
    except Exception as e:
        log.warning("finance status: audit-signing probe failed: %s", e)
        return False, f"could not verify audit signing (probe error: {type(e).__name__})"
    return False, "enable [audit] sign = true for the SOX-grade book of record"


def _sanctions_active() -> tuple[bool, str]:
    from ..tools.sanctions_screen import _list_path, load_list
    path = _list_path()
    names = load_list(path)
    if names:
        return True, f"sanctions list loaded ({len(names)} names) at {path}"
    return False, f"add an OFAC SDN list at {path} (or set [screening] sdn_path)"


def _enc_active() -> tuple[bool, str]:
    try:
        from ..crypto_at_rest import at_rest_enabled
        if at_rest_enabled():
            return True, "AES-256-GCM seals payroll PII / bank details at rest"
    except Exception as e:
        log.warning("finance status: encryption-at-rest probe failed: %s", e)
        return False, f"could not verify encryption at rest (probe error: {type(e).__name__})"
    return False, "enable [encryption] at_rest = true (payroll/treasury PII)"


def _egress_active() -> tuple[bool, str]:
    try:
        from ..enterprise import enterprise_enabled
        if enterprise_enabled():
            return True, "enterprise egress lock: LLM calls pinned on-box (GLBA/PCI)"
    except Exception as e:
        log.warning("finance status: egress-lock probe failed: %s", e)
        return False, f"could not verify egress lock (probe error: {type(e).__name__})"
    return False, "enable [enterprise] mode = true to keep financial data on-box"


def _check(control: str, regulation: str, probe) -> ControlCheck:
    ok, detail = probe()
    return ControlCheck(control, regulation,
                        "active" if ok else "action_needed", detail, framework="finance")


def finance_status() -> list[ControlCheck]:
    """Map live finance controls to their state. Powers ``maverick finance status``."""
    checks = [
        _check("Segregation of duties (roster)", "SOX / COSO", _sod_active),
        _check("Maker-checker on money movement", "SOX §404 / EU AI Act Art 14",
               _money_gate_active),
        _check("Amount-aware authorization (DoA tiers)", "Delegation of Authority",
               _amount_tiers_active),
        _check("Tamper-evident book of record", "SOX §404 / §409", _signing_active),
        _check("Sanctions screening", "AML / BSA / OFAC", _sanctions_active),
        _check("Encryption at rest", "GLBA / PCI-DSS", _enc_active),
        _check("Data-egress lock", "GLBA / data residency", _egress_active),
    ]
    enabled = _regimes.configured_regimes()
    known = [k for k in enabled if k in _regimes.REGIMES]
    checks.append(ControlCheck(
        "Compliance regimes enabled",
        ", ".join(_regimes.REGIMES[k].name for k in known) or "(none configured)",
        "active" if known else "action_needed",
        "regimes compile to the governance policy (strictest-wins)" if known
        else "set [finance] regimes = [\"sox\", \"gaap\", ...]",
        framework="finance",
    ))
    return checks


def render_status_text(checks: list[ControlCheck]) -> str:
    width = max((len(c.control) for c in checks), default=10)
    label = {"active": "active", "action_needed": "ACTION NEEDED", "available": "on-demand"}
    rows = []
    for c in checks:
        rows.append(f"  [{label.get(c.status, c.status):>13}]  {c.control:<{width}}  {c.regulation}")
        rows.append(f"  {'':>13}    {'':<{width}}  -> {c.detail}")
    active = sum(1 for c in checks if c.status == "active")
    needed = sum(1 for c in checks if c.status == "action_needed")
    head = "Finance control coverage"
    return "\n".join([head, "=" * len(head), "", *rows, "",
                      f"{active} active, {needed} need action, {len(checks)} total",
                      "", FINANCE_DISCLAIMER])


def render_status_json(checks: list[ControlCheck]) -> str:
    import json
    from dataclasses import asdict
    return json.dumps({
        "controls": [asdict(c) for c in checks],
        "summary": {"active": sum(1 for c in checks if c.status == "active"),
                    "action_needed": sum(1 for c in checks if c.status == "action_needed"),
                    "total": len(checks)},
        "disclaimer": FINANCE_DISCLAIMER,
    }, indent=2)


__all__ = ["finance_status", "render_status_text", "render_status_json", "FINANCE_DISCLAIMER"]
