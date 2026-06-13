"""Domain packs -- the unit the agent factory emits.

A :class:`DomainProfile` describes one specialist domain (finance, legal,
privacy/compliance, generic, ...): its persona, the capability envelope its
agents run under, the tools / MCP servers it may use, model overrides, and the
knowledge sources (uploaded docs) it draws on. Two authoring paths feed the
same schema:

  * hand-authored TOML packs under ``<pkg>/domains/`` (built-in) or
    ``~/.maverick/domains/`` (operator-provided), and
  * intake-generated packs (a business describes itself; we synthesize a
    profile) -- the same dataclass, marked ``authoring="generated"``.

The ``compartment`` tag is the hinge between the factory and the safety
substrate: every agent spawned from a profile inherits that tag, so a Rung-2
sector seal can quarantine an entire domain at once (see
:mod:`maverick.quarantine`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

# Keys we accept from a pack's TOML. Unknown keys are ignored so a newer pack
# can't crash an older loader.
_FIELDS = frozenset({
    "compartment", "description", "persona", "allow_tools", "deny_tools",
    "max_risk", "allow_paths", "allow_hosts", "mcp_servers", "models",
    "knowledge_sources", "authoring",
})


@dataclass
class DomainProfile:
    name: str
    compartment: str = ""          # seal boundary; defaults to ``name``
    description: str = ""
    persona: str = ""              # system-prompt specialization
    allow_tools: list[str] = field(default_factory=list)
    deny_tools: list[str] = field(default_factory=list)
    max_risk: str | None = None
    allow_paths: list[str] = field(default_factory=list)
    allow_hosts: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)
    knowledge_sources: list[str] = field(default_factory=list)
    authoring: str = "manual"      # "manual" | "generated"

    def __post_init__(self) -> None:
        if not self.compartment:
            self.compartment = self.name

    def capability(self, principal: str):
        """Build the Capability envelope agents in this domain run under.

        Ties the factory to the P0 identity layer: the profile's tool / risk /
        path / host scopes become an attenuating grant (:mod:`maverick.capability`).
        """
        from .capability import Capability
        return Capability(
            principal=principal,
            allow_tools=frozenset(self.allow_tools),
            deny_tools=frozenset(self.deny_tools),
            max_risk=self.max_risk,
            allow_paths=frozenset(self.allow_paths),
            allow_hosts=frozenset(self.allow_hosts),
        )


def _coerce(name: str, data: dict) -> DomainProfile:
    return DomainProfile(name=name, **{k: v for k, v in data.items() if k in _FIELDS})


def load_domain(path: str | Path) -> DomainProfile:
    """Parse a single domain pack from TOML."""
    path = Path(path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _coerce(data.get("name") or path.stem, data)


def load_domains(directory: str | Path) -> dict[str, DomainProfile]:
    """Load every ``*.toml`` pack in ``directory``. A malformed pack is skipped
    (it must not break discovery of the rest)."""
    directory = Path(directory)
    out: dict[str, DomainProfile] = {}
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("*.toml")):
        try:
            prof = load_domain(p)
        except Exception:
            continue
        out[prof.name] = prof
    return out


def builtin_dir() -> Path:
    return Path(__file__).parent / "domains"


def user_dir() -> Path:
    """The active workspace's domains directory.

    An explicit ``MAVERICK_DOMAINS_DIR`` override still wins (tests / custom
    layouts); otherwise this is the current tenant's domains dir (per-business
    isolation), falling back to ~/.maverick/domains for the single-tenant default."""
    override = os.environ.get("MAVERICK_DOMAINS_DIR")
    if override:
        return Path(override).expanduser()
    from .workspace import Workspace
    return Workspace.current().domains_dir


def available_domains() -> dict[str, DomainProfile]:
    """All discoverable packs: built-in first, then user-provided (user wins)."""
    domains = load_domains(builtin_dir())
    domains.update(load_domains(user_dir()))
    return domains


# A pack's name prefix maps it to a business *suite* (finance, operations, legal,
# ...), so an operator can enable/disable a whole suite at once. The installer
# wizard writes the choices to ``[suites]`` in config.toml; ``enabled_domains``
# applies them. Forward-looking entries (gtm_/hr_/...) are ready for those suites.
SUITE_PREFIXES: dict[str, str] = {
    "finance_": "finance",
    "ops_": "operations",
    "legal_": "legal",
    "itgrc_": "it_grc",
    "gtm_": "sales_gtm",
    "hr_": "hr",
    "pe_": "product_engineering",
    "strat_": "strategy",
    "cx_": "customer_experience",
    "mkt_": "marketing",
    "proc_": "procurement",
    "data_": "data_analytics",
    "sec_": "security_ops",
    "exec_": "executive_office",
    "ehs_": "facilities_ehs",
    "hc_": "healthcare",
    "ins_": "insurance",
    "bank_": "banking",
    "ret_": "retail",
    "mfg_": "manufacturing_vertical",
    "con_": "construction",
    "log_": "logistics",
    "ps_": "professional_services",
    "gov_": "government_contracting",
    "edu_": "education_nonprofit",
    "tax_": "tax",
}


def suite_for(name: str) -> str | None:
    """The business suite a domain pack belongs to, or ``None`` (legacy/generic)."""
    for prefix, suite in SUITE_PREFIXES.items():
        if name.startswith(prefix):
            return suite
    return None


def _disabled_suites(cfg: dict | None = None) -> set[str]:
    """Suites turned OFF in the ``[suites]`` table (``suite = false``).

    Opt-out: a suite is enabled unless explicitly set false, so an empty/absent
    ``[suites]`` table leaves every suite on (behaviour unchanged)."""
    try:
        if cfg is None:
            from .config import load_config
            cfg = load_config() or {}
        table = cfg.get("suites") or {}
    except Exception:
        return set()
    return {str(k) for k, v in table.items() if v is False}


def enabled_domains(cfg: dict | None = None) -> dict[str, DomainProfile]:
    """:func:`available_domains` minus the packs of any suite disabled in ``[suites]``.

    Backward compatible: with no ``[suites]`` config every domain is returned.
    Legacy/generic packs (no recognized suite prefix) are always kept."""
    domains = available_domains()
    disabled = _disabled_suites(cfg)
    if not disabled:
        return domains
    return {
        name: prof for name, prof in domains.items()
        if (suite_for(name) is None) or (suite_for(name) not in disabled)
    }


def domain_capability(profile: DomainProfile, parent_cap, principal: str):
    """The Capability a domain agent runs under.

    With a parent grant present, attenuate it by the profile's scopes (never
    broaden); otherwise mint the profile's own envelope. Empty profile fields
    pass ``None`` so they inherit the parent's scope rather than emptying it --
    an empty allow-set means "all", which would *broaden* the grant.
    """
    allow = set(profile.allow_tools) or None
    deny = set(profile.deny_tools) or None
    paths = set(profile.allow_paths) or None
    hosts = set(profile.allow_hosts) or None
    if parent_cap is not None:
        return parent_cap.attenuate(
            principal=principal, allow=allow, deny=deny,
            max_risk=profile.max_risk, allow_paths=paths, allow_hosts=hosts,
        )
    return profile.capability(principal)


_VALID_RISKS = frozenset({"low", "medium", "high"})
# Below this, a persona is a label, not a working instruction set.
_MIN_PERSONA_CHARS = 200


def lint_profile(profile: DomainProfile) -> tuple[list[str], list[str]]:
    """Quality-gate one pack. Returns ``(errors, warnings)``.

    Errors are problems that weaken the safety envelope or make the
    specialist unreliable (no tool allowlist = ALL tools; an unknown
    ``max_risk`` silently fails open to "no ceiling"). Warnings are quality
    gaps a pack author should look at. Pure, for tests and the CLI."""
    errors: list[str] = []
    warnings: list[str] = []
    if not profile.allow_tools:
        errors.append("allow_tools is empty: an empty allowlist grants ALL "
                      "tools -- name the tools this specialist needs")
    if profile.max_risk is None:
        errors.append("max_risk is unset: the pack has no risk ceiling")
    elif profile.max_risk not in _VALID_RISKS:
        errors.append(f"max_risk {profile.max_risk!r} is not one of "
                      f"{sorted(_VALID_RISKS)}")
    overlap = set(profile.allow_tools) & set(profile.deny_tools)
    if overlap:
        warnings.append("tools both allowed and denied (deny wins): "
                        + ", ".join(sorted(overlap)))
    if len((profile.persona or "").strip()) < _MIN_PERSONA_CHARS:
        warnings.append(f"persona under {_MIN_PERSONA_CHARS} chars: a label, "
                        "not a working instruction set")
    if not (profile.description or "").strip():
        warnings.append("description is empty (the roster shows it to "
                        "operators and the orchestrator)")
    if not profile.knowledge_sources:
        warnings.append("no knowledge_sources: the specialist can't ground "
                        "answers in company documents")
    if not profile.deny_tools:
        warnings.append("no deny_tools: consider explicitly denying the "
                        "tools this role must never touch")
    return errors, warnings


def _department_memory(profile: DomainProfile, task: str, *,
                       channel: str | None = None, user_id: str | None = None,
                       shield=None) -> str:
    """The department's recalled lessons, formatted for a specialist's brief.

    Pre-run context layers only run at the orchestrator root; a specialist
    spawned mid-run via ``spawn_specialist`` used to start blank. This gives
    every pack its department memory at ANY spawn depth: same-department
    reflexion lessons scoped to the current channel/user and consolidated
    dream insights, both already sanitized/bounded by their formatters. Empty
    (and free) unless the operator enabled those loops; never raises into a
    spawn.
    """
    try:
        from .config import get_domains
        if not get_domains()["memory"]:
            return ""
    except Exception:  # pragma: no cover -- config never blocks a spawn
        pass
    blocks: list[str] = []
    try:
        from . import reflexion
        if reflexion.enabled():
            recalled = reflexion.recall(
                task, k=2, domain=profile.name,
                channel=channel, user_id=user_id,
            )
            block = reflexion.format_context(recalled, shield=shield)
            if block:
                blocks.append(block)
    except Exception:  # pragma: no cover -- recall never blocks a spawn
        pass
    try:
        from . import dreaming
        if dreaming.enabled():
            insights = dreaming.recall_insights(task, domain=profile.name)
            block = dreaming.format_context(insights)
            if block:
                blocks.append(block)
    except Exception:  # pragma: no cover -- recall never blocks a spawn
        pass
    return "\n".join(blocks)


def agent_from_profile(profile: DomainProfile, ctx, task: str, *,
                       parent=None, depth: int = 0, principal: str | None = None):
    """Spawn a live agent from a domain pack -- the factory's "spit out an agent".

    Sets the agent's role, persona, **compartment tag** (so a Rung-2 sector seal
    reaches it and its sub-tree), and a capability envelope derived from the
    profile (attenuated against the parent's grant when one exists). A domain
    agent therefore always runs inside its pack's tool/risk/host envelope, even
    when global capability enforcement is off -- the pack is a hard boundary.

    The pack persona is augmented with the suite's operating discipline
    (:mod:`maverick.domain_discipline`), and the department's recalled
    lessons are appended to the task brief -- so every specialist, at every
    spawn depth, works like a professional with its department's memory.
    """
    from .agent import Agent
    from .domain_discipline import augment_persona
    principal = principal or f"agent:{profile.name}-{depth}"
    if parent is not None and hasattr(parent, "_effective_capability"):
        parent_cap = parent._effective_capability("spawn_specialist")
    else:
        parent_cap = getattr(parent, "capability", None)
    cap = domain_capability(profile, parent_cap, principal)
    memory = _department_memory(
        profile, task,
        channel=getattr(ctx, "channel", None),
        user_id=getattr(ctx, "user_id", None),
        shield=getattr(ctx, "shield", None),
    )
    return Agent(
        ctx=ctx, role=profile.name, brief=task + ("\n" + memory if memory else ""),
        depth=depth, parent=parent,
        domain=profile.compartment,
        persona=augment_persona(profile.name, profile.persona), capability=cap,
        knowledge_sources=profile.knowledge_sources,
    )
