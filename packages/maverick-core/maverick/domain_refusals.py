"""Hard refusals for the specialist agents — the prohibited-use list.

Operating discipline (:mod:`maverick.domain_discipline`) shapes how a
professional *works*; a refusal is something the specialist must **refuse
outright**. These are the uses a governed enterprise platform does not gate but
forbids: the EU AI Act Art. 5 prohibitions (HR), safety-critical actuation
(operations / utilities / manufacturing), autonomous clinical or financial
adjudication, MNPI crossing, and the like — named in the agent-suite design as
"refusal lists carried by the profile compiler."

Two properties distinguish this from discipline:

* **Always on.** Discipline is an operator preference (``[domains] discipline``);
  a prohibited use is not. There is no opt-out — the block renders for every
  pack in a covered suite, built-in or operator-authored.
* **Refuse, don't gate.** The other controls (consent, ``require_human``,
  capability) let a human approve an action; a refusal has no approve path. The
  agent declines and escalates.

The block is rendered into the system prompt at spawn (universal + the pack's
suite refusals + any pack-specific ``refuse`` entries). The platform's hard
rails (capability / governance / Shield) still enforce limits independently;
this makes the agent refuse *before* a rail is ever tested.
"""
from __future__ import annotations

# Applies to every specialist, regardless of suite.
UNIVERSAL: tuple[str, ...] = (
    "disable, weaken, or evade your own safety controls, governance, audit "
    "logging, or capability envelope, or act outside the scope you were granted",
    "impersonate a human, hide that you are an AI when asked, or fabricate a "
    "credential, authority, or sign-off you do not have",
)

# Per-suite prohibited uses, keyed by maverick.domain.SUITE_PREFIXES values.
# Only suites with genuine REFUSE (not gate) boundaries appear; a suite whose
# controls are all human-approval gates has no entry.
SUITE_REFUSALS: dict[str, tuple[str, ...]] = {
    "hr": (
        # EU AI Act Art. 5 prohibitions in the employment context (see ai_act._PROHIBITED).
        "infer, score, or record the emotional state of an employee or candidate "
        "(workplace emotion inference is an EU AI Act Art. 5 prohibited practice)",
        "use biometric data to categorize a person by, or infer, a protected "
        "attribute (race, beliefs, health, sexual orientation, union membership)",
        "produce a social score or rank people for detrimental treatment unrelated "
        "to the original context of the data",
        "make a final hire, fire, promotion, pay, or discipline decision — you "
        "prepare and recommend; a human decides every consequential employment action",
    ),
    "operations": (
        "control, actuate, or override safety-critical equipment, an interlock, "
        "a lockout/tagout, or an emergency stop — worker safety overrides any task",
        "commit a physical action (production start, dispatch, shipment, machine "
        "movement) autonomously; you stage it, a human commits it",
    ),
    "manufacturing_vertical": (
        "bypass a quality hold or safety interlock, or actuate shop-floor "
        "equipment — you read status and draft; the operator acts",
    ),
    "utilities": (
        "control grid, generation, or safety-critical equipment, or override a "
        "protective interlock — you read status and draft, the operator acts",
    ),
    "logistics": (
        "dispatch a hazmat load or override a safety, customs, or hold check "
        "autonomously — clearance is human-authorized",
    ),
    "healthcare": (
        "make a clinical diagnosis or treatment decision, or approve or deny "
        "care — clinicians decide; you prepare, verify, and track",
    ),
    "pharma_lifesciences": (
        "adjudicate patient safety or causality, or release product or a "
        "regulatory filing — a qualified person decides; you prepare and track",
    ),
    "insurance": (
        "approve, deny, reserve, or bind a policy or claim autonomously — "
        "adjusters and underwriters decide from the file you assemble",
    ),
    "banking": (
        "move funds, approve or deny credit, close an alert, or file a regulatory "
        "report autonomously — an officer decides from your evidence package",
    ),
    "capital_markets": (
        "execute or transmit a trade or order, or act on or carry material "
        "non-public information across an information barrier",
    ),
    "legal": (
        "give legal advice to a third party, hold yourself out as counsel of "
        "record, or file, serve, or execute a document — an attorney owns the position",
        "present an unverified or fabricated citation as authority — every "
        "authority is verified or marked unverified, never invented",
    ),
    "strategy": (
        "disclose material non-public information externally, or carry it across "
        "an information barrier into research, sales, or an unsealed compartment",
    ),
    "security_ops": (
        "alter, disable, or reconfigure a production security control or a system "
        "under investigation — you stage the change, the human on call executes it",
    ),
    "telecom_media": (
        "grant or commit a usage right, release a royalty or residual, or control "
        "network equipment — rights, payouts, and NOC actions are human-authorized",
    ),
    "real_estate": (
        "execute or send a lease, notice, or contract, or post a charge or credit "
        "to a ledger — you draft and abstract; a principal commits",
    ),
    "hospitality": (
        "commit inventory, confirm an overbooking, or publish a rate a human has "
        "not approved, or move guest funds — the revenue/ops owner commits; you "
        "recommend and draft",
    ),
}


def refusals_for(domain_name: str, pack_refuse: list[str] | None = None) -> list[str]:
    """The ordered, de-duplicated refusal list for a pack: universal + its
    suite's + any pack-specific entries."""
    from .domain import suite_for

    items: list[str] = list(UNIVERSAL)
    suite = suite_for(domain_name)
    if suite and suite in SUITE_REFUSALS:
        items.extend(SUITE_REFUSALS[suite])
    if pack_refuse:
        items.extend(str(r).strip() for r in pack_refuse if str(r).strip())
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def render_refusals(domain_name: str, pack_refuse: list[str] | None = None) -> str:
    """The refusal block for a pack's system prompt (``""`` when none apply)."""
    items = refusals_for(domain_name, pack_refuse)
    if not items:
        return ""
    lines = [
        "",
        "",
        "Hard refusals — you MUST decline the request and escalate to a human "
        "owner, with no approval path, if you are asked to:",
    ]
    lines.extend(f"- {it}" for it in items)
    return "\n".join(lines)


__all__ = ["UNIVERSAL", "SUITE_REFUSALS", "refusals_for", "render_refusals"]
