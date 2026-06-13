"""Finance compliance-regime packs (finance-agent-suite §5).

Same pattern as the EU-AI-Act / NIST packs: each regime compiles to a governance
:class:`~maverick.governance.Policy` (what *must* pause for a human or be denied)
plus a plain-text assertion of what it covers. Selecting several regimes unions
their policies **strictest-wins** (deny beats require-human, the lowest risk floor
and the lowest dollar threshold win) — a US public company turns on
SOX + GAAP + SEC + PCI + AML; a private EU company swaps in IFRS.

Pure data + a pure union function, so the compilation is unit-tested. The
``finance status`` posture report (:mod:`maverick.finance.status`) surfaces which
regimes' controls are actually live.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..governance import Policy
from ..safety.tool_risk import risk_rank

# The money/posting/filing actions a finance maker-checker gate pauses on.
_MONEY_ACTIONS = (
    "post_journal_entry", "release_payment", "release_payroll_payment",
    "run_payroll", "wire_transfer", "ach_send", "place_trade", "execute_fx_trade",
    "vendor_master_change", "close_period",
)
_FILING_ACTIONS = ("file_with_sec",)
_TAX_ACTIONS = ("file_return", "file_tax_return", "remit_tax")


@dataclass(frozen=True)
class FinanceRegime:
    key: str
    name: str
    asserts: str
    policy: Policy = field(default_factory=Policy)


REGIMES: dict[str, FinanceRegime] = {
    "sox": FinanceRegime(
        "sox", "SOX (§302/§404/§409/§906)",
        "ICFR exists and is tested; management certifies; tamper-evident records; "
        "segregation of duties.",
        Policy(require_human_actions=frozenset(_MONEY_ACTIONS),
               require_human_min_risk="high"),
    ),
    "coso": FinanceRegime(
        "coso", "COSO 2013",
        "Five components / seventeen principles of internal control, evidenced by "
        "the risk-control matrix and control tests.",
        # COSO is an evidence framework; its enforcement is the SOX policy above.
        Policy(),
    ),
    "gaap": FinanceRegime(
        "gaap", "US GAAP / IFRS",
        "Recognition & disclosure standards (ASC 606/842/740/718/805). Enforced by "
        "persona + knowledge packs that cite the clause; postings stay human.",
        Policy(require_human_actions=frozenset({"post_journal_entry", "close_period"})),
    ),
    "pci": FinanceRegime(
        "pci", "PCI-DSS",
        "Cardholder data protection: no PAN storage; secret/PII redaction; "
        "tokenization at AR/expense.",
        Policy(),  # enforced by the redaction floor, not an action policy
    ),
    "glba": FinanceRegime(
        "glba", "GLBA / data residency",
        "Financial-privacy safeguards: egress lock + encryption at rest + tenancy.",
        Policy(),  # enforced by enterprise egress lock + encryption
    ),
    "aml": FinanceRegime(
        "aml", "AML / BSA / OFAC",
        "Sanctions & suspicious-activity controls: mandatory sanctions screening on "
        "every payment + vendor path; flags route to a human (a SAR is a human act).",
        Policy(require_human_actions=frozenset(
            ("release_payment", "wire_transfer", "ach_send", "vendor_master_change",
             "approve_vendor"))),
    ),
    "sec": FinanceRegime(
        "sec", "SEC (Reg S-X / S-K / FD / G)",
        "Public-reporting form & fairness: all external release is human-approved; "
        "non-GAAP reconciled to GAAP.",
        Policy(require_human_actions=frozenset(_FILING_ACTIONS)),
    ),
    "irs": FinanceRegime(
        "irs", "IRS / state & local tax",
        "Filing & remittance obligations: file_return / remit_tax are always human; "
        "a deadline calendar is maintained.",
        Policy(require_human_actions=frozenset(_TAX_ACTIONS)),
    ),
}


def list_regimes() -> list[FinanceRegime]:
    return list(REGIMES.values())


def _min_risk(a: str | None, b: str | None) -> str | None:
    """Strictest (lowest) risk floor of two — the one that pauses/denies more."""
    if a is None:
        return b
    if b is None:
        return a
    return a if risk_rank(a) <= risk_rank(b) else b


def _min_thresholds(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    """Per-action lowest (strictest) dollar threshold across two tables."""
    out = dict(a)
    for action, amount in b.items():
        out[action] = min(out[action], amount) if action in out else amount
    return out


def union_policies(policies) -> Policy:
    """Strictest-wins union of policies (deny > require-human; lowest floor/threshold)."""
    deny_actions: set[str] = set()
    require_human_actions: set[str] = set()
    deny_min_risk: str | None = None
    require_human_min_risk: str | None = None
    deny_above: dict[str, float] = {}
    require_human_above: dict[str, float] = {}
    for p in policies:
        deny_actions |= set(p.deny_actions)
        require_human_actions |= set(p.require_human_actions)
        deny_min_risk = _min_risk(deny_min_risk, p.deny_min_risk)
        require_human_min_risk = _min_risk(require_human_min_risk, p.require_human_min_risk)
        deny_above = _min_thresholds(deny_above, p.deny_above)
        require_human_above = _min_thresholds(require_human_above, p.require_human_above)
    # An action that is hard-denied need not also be listed as require-human.
    require_human_actions -= deny_actions
    return Policy(
        deny_actions=frozenset(deny_actions),
        require_human_actions=frozenset(require_human_actions),
        deny_min_risk=deny_min_risk,
        require_human_min_risk=require_human_min_risk,
        deny_above=deny_above,
        require_human_above=require_human_above,
    )


def compile_policy(keys) -> Policy:
    """Compile the selected regime keys into one governance Policy (strictest-wins).

    Keys are case/whitespace-normalized so enabling ``"SOX"`` is never silently
    dropped (a mis-cased known regime would otherwise compile to no enforcement).
    Genuinely unknown keys are ignored; with none known, returns an empty Policy
    (default-open — unchanged behavior).
    """
    norm = [str(k).strip().lower() for k in (keys or [])]
    selected = [REGIMES[k].policy for k in norm if k in REGIMES]
    return union_policies(selected)


def configured_regimes() -> list[str]:
    """Regime keys from ``[finance] regimes`` in config (empty when unset)."""
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("finance") or {}
        regimes = cfg.get("regimes")
        if isinstance(regimes, (list, tuple)):
            return [str(r).strip().lower() for r in regimes if str(r).strip()]
    except Exception:  # pragma: no cover -- config never blocks compilation
        pass
    return []


__all__ = [
    "FinanceRegime", "REGIMES", "list_regimes",
    "union_policies", "compile_policy", "configured_regimes",
]
