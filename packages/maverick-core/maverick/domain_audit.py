"""Governance audit surface for the specialist roster.

``maverick domains-lint`` answers "is each pack well-formed?". This answers the
enterprise question: "what can these agents do, and what stops them?" — the
auditable inventory a GRC reviewer, security assessment, or procurement needs.

For each pack it records the governance posture the other modules enforce:
the compartment seal, the capability envelope (risk ceiling + whether any
state-mutating tool is reachable), the hard refusals it carries, the human
sign-off gate on its deliverable, and the reasoning tier. Pure functions: the
CLI renders them, tests assert the roster-wide invariants (e.g. no drafting
agent can reach a shell), and the JSON export feeds an external GRC system.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .domain import DomainProfile, available_domains, suite_for
from .domain_refusals import refusals_for

# State-mutating / host-control tools a drafting agent must never reach.
_DANGEROUS = ("shell", "write_file", "code_exec", "computer", "browser")
# Irreversible business actions; a pack denying these shows its segregation-of-
# duties posture ("agents draft; humans post, pay, file, certify").
_IRREVERSIBLE = (
    "release_payment", "wire_transfer", "ach_send", "run_payroll",
    "post_journal_entry", "file_return", "file_tax_return", "file_with_sec",
    "place_trade", "execute_fx_trade", "vendor_master_change", "send_payment",
    "approve_expense", "approve_po", "approve_vendor", "set_credit_limit",
    "send_invoice", "self_edit",
)


@dataclass
class PackAudit:
    name: str
    suite: str | None
    compartment: str
    max_risk: str | None
    effort: str | None
    is_builder: bool
    reachable_dangerous: list[str] = field(default_factory=list)
    denied_irreversible: list[str] = field(default_factory=list)
    n_refusals: int = 0
    refusals: list[str] = field(default_factory=list)
    human_gate: str | None = None          # the sign-off on the deliverable / playbook
    deliverable: str = ""
    consumers: list[str] = field(default_factory=list)
    knowledge_sources: list[str] = field(default_factory=list)
    autonomy: str = "suggest"              # baseline authority rung (pack block or suite default)
    autonomy_onboarding: bool = True       # starts supervised until graduated


def _human_gate(p: DomainProfile) -> str | None:
    """The strongest human sign-off the pack declares (approval > review)."""
    gates = {p.output.gate} | {s.gate for s in p.workflow}
    if "approval" in gates:
        return "approval"
    if "review" in gates:
        return "review"
    return None


def audit_profile(profile: DomainProfile) -> PackAudit:
    """The governance posture of one pack (pure)."""
    allow = set(profile.allow_tools)
    is_builder = bool(allow & {"shell", "code_exec"})
    cap = profile.capability(f"agent:{profile.name}")
    reachable = [t for t in _DANGEROUS if cap.permits(t)]
    denied = [t for t in _IRREVERSIBLE if t in set(profile.deny_tools)]
    refusals = refusals_for(profile.name, profile.refuse)
    from .agent_autonomy import default_profile_for
    _auto = profile.autonomy or default_profile_for(profile.name)
    return PackAudit(
        name=profile.name,
        suite=suite_for(profile.name),
        compartment=profile.compartment,
        max_risk=profile.max_risk,
        effort=profile.effort,
        is_builder=is_builder,
        reachable_dangerous=reachable,
        denied_irreversible=denied,
        n_refusals=len(refusals),
        refusals=refusals,
        human_gate=_human_gate(profile),
        deliverable=profile.output.deliverable,
        consumers=list(profile.output.consumers),
        knowledge_sources=list(profile.knowledge_sources),
        autonomy=_auto.default.value,
        autonomy_onboarding=_auto.onboarding,
    )


def audit_roster(domains: dict[str, DomainProfile] | None = None) -> list[PackAudit]:
    """Audit every discoverable pack (built-in + operator overrides)."""
    domains = domains if domains is not None else available_domains()
    return [audit_profile(domains[name]) for name in sorted(domains)]


def summarize(audits: list[PackAudit]) -> dict:
    """Roster-wide governance summary -- the headline numbers for an assessor."""
    total = len(audits)
    builders = [a for a in audits if a.is_builder]
    non_builders = [a for a in audits if not a.is_builder]
    return {
        "packs": total,
        "suites": len({a.suite for a in audits if a.suite}),
        "builders": len(builders),
        # The load-bearing safety invariant: no drafting agent reaches a mutator.
        "drafting_agents_reaching_a_mutator": sum(
            1 for a in non_builders if a.reachable_dangerous),
        "packs_with_human_gate": sum(1 for a in audits if a.human_gate),
        "packs_with_refusals_beyond_universal": sum(
            1 for a in audits if a.n_refusals > 2),
        "packs_with_effort_tier": sum(1 for a in audits if a.effort),
        "packs_with_deliverable": sum(1 for a in audits if a.deliverable),
        # Per-agent authority posture (the agent-as-employee dial). Distribution
        # of the baseline rung each hire starts at, and how many begin supervised.
        "autonomy_posture": {
            rung: sum(1 for a in audits if a.autonomy == rung)
            for rung in ("observe", "suggest", "request", "auto")
        },
        "packs_onboarding": sum(1 for a in audits if a.autonomy_onboarding),
    }


def to_json(audits: list[PackAudit]) -> dict:
    """A machine-readable audit document for ingestion into a GRC system."""
    return {"summary": summarize(audits), "packs": [asdict(a) for a in audits]}


__all__ = ["PackAudit", "audit_profile", "audit_roster", "summarize", "to_json"]
