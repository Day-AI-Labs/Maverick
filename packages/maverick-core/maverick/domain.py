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
    cap = domain_capability(profile, getattr(parent, "capability", None), principal)
    return Agent(
        ctx=ctx, role=profile.name, brief=task, depth=depth, parent=parent,
        domain=profile.compartment, persona=profile.persona, capability=cap,
        knowledge_sources=profile.knowledge_sources,
    )
