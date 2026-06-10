"""Compliance mode profiles (roadmap: 2027 H1 safety — "HIPAA mode profile").

Cross-domain runtime postures you turn on the way the finance suite turns on
``[finance] regimes``: each profile asserts the safeguards it stands for, names
the protection *floors* it requires to be live (redaction, encryption-at-rest,
egress lock, audit), and compiles to a governance :class:`~maverick.governance.Policy`
(what must pause for a human). Selecting several unions them strictest-wins via
the same helper the finance regimes use.

The first profile is **HIPAA mode** — a PHI-handling posture. This is the
enforcement counterpart to the HIPAA *assessment* template in
:mod:`maverick.assessment`: the assessment scores readiness; the profile turns
the guardrails on. Pure data + pure functions, so the compilation is unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .finance.regimes import union_policies  # generic strictest-wins policy union
from .governance import Policy

# Protection floors a profile can require. These are advisory keys the posture
# report and the preflight check read; turning them on is the operator's job
# (egress lock, encryption-at-rest, audit retention are existing knobs).
FLOOR_PII_REDACTION = "pii_redaction"
FLOOR_ENCRYPTION_AT_REST = "encryption_at_rest"
FLOOR_EGRESS_LOCK = "egress_lock"
FLOOR_AUDIT_LOG = "audit_log"


@dataclass(frozen=True)
class ComplianceProfile:
    key: str
    name: str
    asserts: str
    required_floors: frozenset[str] = frozenset()
    policy: Policy = field(default_factory=Policy)


PROFILES: dict[str, ComplianceProfile] = {
    "hipaa": ComplianceProfile(
        "hipaa",
        "HIPAA Security Rule (45 CFR Part 164)",
        "PHI minimum-necessary; access controls; encryption at rest and in "
        "transit; audit controls; breach-notification readiness; BAAs with "
        "processors. Any high-risk action pauses for a human.",
        required_floors=frozenset({
            FLOOR_PII_REDACTION, FLOOR_ENCRYPTION_AT_REST,
            FLOOR_EGRESS_LOCK, FLOOR_AUDIT_LOG,
        }),
        # PHI handling warrants human oversight on every high-risk action.
        policy=Policy(require_human_min_risk="high"),
    ),
}


def list_profiles() -> list[ComplianceProfile]:
    return list(PROFILES.values())


def get_profile(key: str) -> ComplianceProfile | None:
    return PROFILES.get(str(key).strip().lower())


def compile_policy(keys) -> Policy:
    """Compile selected profile keys into one Policy (strictest-wins).

    Unknown keys are ignored; no known keys yields an empty (default-open) Policy.
    """
    selected = [PROFILES[k].policy for k in (keys or []) if k in PROFILES]
    return union_policies(selected)


def required_floors(keys) -> frozenset[str]:
    """Union of the protection floors the selected profiles require."""
    out: set[str] = set()
    for k in keys or []:
        prof = PROFILES.get(k)
        if prof:
            out |= set(prof.required_floors)
    return frozenset(out)


def configured_profiles() -> list[str]:
    """Profile keys from ``[compliance] profiles`` in config (empty when unset)."""
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("compliance") or {}
        profiles = cfg.get("profiles")
        if isinstance(profiles, (list, tuple)):
            return [str(p).strip().lower() for p in profiles if str(p).strip()]
    except Exception:  # pragma: no cover -- config never blocks compilation
        pass
    return []


def profile_posture(keys) -> str:
    """Human-readable posture report for the selected profiles."""
    known = [PROFILES[k] for k in (keys or []) if k in PROFILES]
    if not known:
        return "compliance profiles: none active"
    lines = [f"compliance profiles: {', '.join(p.key for p in known)}"]
    for p in known:
        lines.append(f"- {p.name}")
        lines.append(f"    asserts: {p.asserts}")
        if p.required_floors:
            lines.append(f"    required floors: {', '.join(sorted(p.required_floors))}")
    pol = compile_policy([p.key for p in known])
    if pol.require_human_min_risk:
        lines.append(f"enforcement: require-human at/above risk '{pol.require_human_min_risk}'")
    return "\n".join(lines)


__all__ = [
    "ComplianceProfile", "PROFILES", "list_profiles", "get_profile",
    "compile_policy", "required_floors", "configured_profiles", "profile_posture",
    "FLOOR_PII_REDACTION", "FLOOR_ENCRYPTION_AT_REST", "FLOOR_EGRESS_LOCK",
    "FLOOR_AUDIT_LOG",
]
