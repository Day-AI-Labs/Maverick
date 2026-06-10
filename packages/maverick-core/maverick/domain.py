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


def agent_from_profile(profile: DomainProfile, ctx, task: str, *,
                       parent=None, depth: int = 0, principal: str | None = None):
    """Spawn a live agent from a domain pack -- the factory's "spit out an agent".

    Sets the agent's role, persona, **compartment tag** (so a Rung-2 sector seal
    reaches it and its sub-tree), and a capability envelope derived from the
    profile (attenuated against the parent's grant when one exists). A domain
    agent therefore always runs inside its pack's tool/risk/host envelope, even
    when global capability enforcement is off -- the pack is a hard boundary.
    """
    from .agent import Agent
    principal = principal or f"agent:{profile.name}-{depth}"
    if parent is not None and hasattr(parent, "_effective_capability"):
        parent_cap = parent._effective_capability("spawn_specialist")
    else:
        parent_cap = getattr(parent, "capability", None)
    cap = domain_capability(profile, parent_cap, principal)
    return Agent(
        ctx=ctx, role=profile.name, brief=task, depth=depth, parent=parent,
        domain=profile.compartment, persona=profile.persona, capability=cap,
        knowledge_sources=profile.knowledge_sources,
    )
