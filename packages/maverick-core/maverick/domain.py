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
    "knowledge_sources", "authoring", "extends", "workflow", "output", "effort",
    "refuse",
})


@dataclass
class WorkflowStep:
    """One step in a pack's editable *playbook* -- the ordered procedure a
    specialist follows for its task.

    This is human-authored *guidance* (rendered into the agent's system prompt
    by :func:`render_workflow_prompt`), deliberately distinct from
    :class:`maverick.workflow.Workflow`, which *executes* a tool DAG. A client
    edits these steps to tailor how an agent works; the LLM follows them.
    """
    name: str
    instruction: str = ""          # what the agent does at this step
    tools: list[str] = field(default_factory=list)  # optional tool hints
    gate: str | None = None        # optional human gate: "approval" | "review"


@dataclass
class OutputContract:
    """The *consumption* side of a pack: what the specialist delivers, to whom,
    how often, and what sign-off the deliverable needs before it is acted on.

    Distinct from the capability envelope (what the agent *may do*) and the
    workflow playbook (how it *works*): this declares the *deliverable*. The
    dashboard reads it to render a result as the right kind of artifact (a
    forecast grid vs. a memo), route it to the people who consume it, and gate
    it before it is used. Absent/empty means today's behaviour exactly -- a
    free-text result with no declared consumer, rendered as prose.
    """
    shape: str = "prose"           # render archetype: prose|report|table|forecast
    deliverable: str = ""          # human label, e.g. "13-week cash forecast"
    consumers: list[str] = field(default_factory=list)  # persona roles who receive it
    cadence: str = ""              # "on-demand"|"daily"|"weekly"|"monthly"|...
    gate: str | None = None        # sign-off before the deliverable is used


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
    effort: str | None = None      # reasoning tier (applied only when [effort] on)
    refuse: list[str] = field(default_factory=list)  # pack-specific hard refusals
    extends: str = ""              # overlay base: inherit a pack, patch the rest
    workflow: list[WorkflowStep] = field(default_factory=list)  # editable playbook
    output: OutputContract = field(default_factory=OutputContract)  # the deliverable

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


def _coerce_workflow(raw: object) -> list[WorkflowStep]:
    """Turn a pack's ``[[workflow]]`` array-of-tables into ``WorkflowStep``s.

    Forgiving: a step without a name, or a non-list ``workflow``, is dropped
    rather than raising -- a malformed playbook must not break pack discovery.
    """
    steps: list[WorkflowStep] = []
    if not isinstance(raw, list):
        return steps
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        tools = item.get("tools")
        steps.append(WorkflowStep(
            name=str(item["name"]),
            instruction=str(item.get("instruction") or ""),
            tools=[str(t) for t in tools] if isinstance(tools, list) else [],
            gate=(str(item["gate"]) if item.get("gate") else None),
        ))
    return steps


def _coerce_output(raw: object) -> OutputContract:
    """Turn a pack's ``[output]`` table into an :class:`OutputContract`.

    Forgiving like :func:`_coerce_workflow`: a missing/non-table ``output`` (or
    a stray non-list ``consumers``) yields the empty contract rather than
    raising, so a malformed block can't break pack discovery."""
    if not isinstance(raw, dict):
        return OutputContract()
    consumers = raw.get("consumers")
    return OutputContract(
        shape=str(raw.get("shape") or "prose"),
        deliverable=str(raw.get("deliverable") or ""),
        consumers=[str(c) for c in consumers] if isinstance(consumers, list) else [],
        cadence=str(raw.get("cadence") or ""),
        gate=(str(raw["gate"]) if raw.get("gate") else None),
    )


def _coerce(name: str, data: dict) -> DomainProfile:
    fields = {k: v for k, v in data.items() if k in _FIELDS}
    if "workflow" in fields:
        fields["workflow"] = _coerce_workflow(fields["workflow"])
    if "output" in fields:
        fields["output"] = _coerce_output(fields["output"])
    if "refuse" in fields:
        raw = fields["refuse"]
        fields["refuse"] = ([str(r) for r in raw] if isinstance(raw, list) else [])
    return DomainProfile(name=name, **fields)


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


def _load_raw_domains(directory: str | Path) -> dict[str, dict]:
    """Parse every ``*.toml`` in ``directory`` to its raw dict (keys as written).

    Unlike :func:`load_domains`, this keeps *which keys a file actually set* --
    the basis for a field-level overlay, where an override patches only what it
    touched and inherits the rest. Malformed files are skipped."""
    directory = Path(directory)
    out: dict[str, dict] = {}
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("*.toml")):
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        out[str(data.get("name") or p.stem)] = data
    return out


# A tenant override may patch any pack field except its identity (``name``,
# which selects the base) and ``extends`` (the link itself, not patched in).
_OVERLAYABLE = _FIELDS - {"extends"}


def overridden_fields(patch: dict) -> set[str]:
    """The set of pack fields a raw override dict actually customizes."""
    return {k for k in patch if k in _OVERLAYABLE}


def overlay_profile(base: DomainProfile, patch: dict) -> DomainProfile:
    """Field-level override: start from ``base`` and replace only the keys the
    override sets, so a client inherits everything it didn't touch.

    ``patch`` is the raw TOML dict of an override pack. The result keeps the
    base's ``name`` (identity is not overlaid). This is the upgrade from the old
    whole-file replacement: a tenant can change just a persona line or one
    workflow step and keep the rest of the built-in pack."""
    data: dict = {
        "compartment": base.compartment,
        "description": base.description,
        "persona": base.persona,
        "allow_tools": list(base.allow_tools),
        "deny_tools": list(base.deny_tools),
        "max_risk": base.max_risk,
        "allow_paths": list(base.allow_paths),
        "allow_hosts": list(base.allow_hosts),
        "mcp_servers": list(base.mcp_servers),
        "models": dict(base.models),
        "knowledge_sources": list(base.knowledge_sources),
        "authoring": base.authoring,
        "effort": base.effort,
        "refuse": list(base.refuse),
        "workflow": list(base.workflow),
        "output": base.output,
    }
    for k in overridden_fields(patch):
        data[k] = patch[k]
    if "workflow" in patch:
        data["workflow"] = _coerce_workflow(patch["workflow"])
    if "output" in patch:
        data["output"] = _coerce_output(patch["output"])
    return DomainProfile(name=base.name, **data)


def render_workflow_prompt(workflow: list[WorkflowStep]) -> str:
    """A pack's playbook as a system-prompt block (``""`` when there is none,
    so packs without a workflow behave exactly as before)."""
    if not workflow:
        return ""
    lines = ["", "", "Workflow -- follow these steps in order:"]
    for i, step in enumerate(workflow, 1):
        line = f"{i}. {step.name}"
        if step.instruction:
            line += f": {step.instruction}"
        if step.tools:
            line += f"  [tools: {', '.join(step.tools)}]"
        if step.gate:
            line += f"  [gate: {step.gate}]"
        lines.append(line)
    return "\n".join(lines)


def available_domains() -> dict[str, DomainProfile]:
    """All discoverable packs: built-in bases, with user/tenant overrides applied
    as field-level overlays.

    A user pack whose name matches a built-in (or that declares ``extends``)
    *patches* that base, inheriting every field it doesn't set. A user pack with
    a brand-new name is added as a standalone pack. This is what lets a client
    customize an agent without re-stating the whole pack."""
    builtin = load_domains(builtin_dir())
    resolved = dict(builtin)
    for name, patch in _load_raw_domains(user_dir()).items():
        base = resolved.get(str(patch.get("extends") or name))
        resolved[name] = overlay_profile(base, patch) if base else _coerce(name, patch)
    return resolved


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
    # Council-expansion verticals (2026): new business suites the factory can
    # spawn from. Each maps to a SUITE_DISCIPLINE block (domain_discipline) and
    # a wizard AGENT_SUITES entry, so a Rung-2 seal + the [suites] toggle reach
    # the whole vertical at once.
    "util_": "utilities",
    "re_": "real_estate",
    "pharma_": "pharma_lifesciences",
    "tmt_": "telecom_media",
    "hosp_": "hospitality",
    "cap_": "capital_markets",
    # New industry suites (2026 build-out).
    "oilgas_": "oil_gas",
    "auto_": "automotive",
    "pubsec_": "public_sector",
    "ag_": "agriculture",
    "aero_": "aerospace_defense",
    "mar_": "maritime",
    "trv_": "travel_aviation",
    "min_": "mining_metals",
    "crypto_": "crypto_digital_assets",
    "chem_": "chemicals",
    "fbcpg_": "food_beverage_cpg",
    "meddev_": "medical_devices",
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
# Reasoning-effort tiers a pack may declare (mirrors maverick.effort._LEVELS).
_VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_VALID_GATES = frozenset({"approval", "review"})
# Sign-off strength: a deliverable must not claim a lighter gate than the
# human-handoff its own playbook ends on (approval > review > none).
_GATE_RANK = {None: 0, "review": 1, "approval": 2}
# Render archetypes the dashboard knows how to present a deliverable as. An
# unknown shape is a warning, not an error: it falls back to prose rendering, so
# a newer pack naming a future shape still loads on an older dashboard.
_VALID_SHAPES = frozenset({"prose", "report", "table", "forecast"})
# Below this, a persona is a label, not a working instruction set.
_MIN_PERSONA_CHARS = 200
# The state-mutating tools a read-only specialist (one that doesn't allow
# ``shell``/``code_exec``) must explicitly DENY, even though its tool allowlist
# already excludes them: defense-in-depth, so a later edit that loosens the
# allowlist can't silently hand a drafting agent a shell or a file writer.
_READONLY_DENY_FLOOR = ("shell", "write_file")


def _lint_output(out: OutputContract) -> list[str]:
    """Quality-gate a pack's output contract. Returns warnings only -- a
    misdeclared deliverable degrades the consumption surface (it renders as
    prose, doesn't route) but never weakens the safety envelope, so nothing
    here is a hard error."""
    warnings: list[str] = []
    if out.shape and out.shape not in _VALID_SHAPES:
        warnings.append(f"output.shape {out.shape!r} is not one of "
                        f"{sorted(_VALID_SHAPES)} (it will render as prose)")
    if out.gate and out.gate not in _VALID_GATES:
        warnings.append(f"output.gate {out.gate!r} is not one of "
                        f"{sorted(_VALID_GATES)}")
    if out.deliverable and not out.consumers:
        warnings.append("output declares a deliverable but no consumers: name "
                        "the roles who receive it so it can be routed")
    return warnings


def _lint_workflow(profile: DomainProfile) -> tuple[list[str], list[str]]:
    """Quality-gate a pack's editable playbook. Returns ``(errors, warnings)``.

    A nameless or duplicate step is an error (it breaks the ordered procedure);
    an unknown gate or a step naming a tool the pack doesn't allow is a warning."""
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for i, step in enumerate(profile.workflow, 1):
        name = (step.name or "").strip()
        if not name:
            errors.append(f"workflow step {i} has no name")
        elif name in seen:
            errors.append(f"duplicate workflow step name {name!r}")
        seen.add(name)
        if step.gate and step.gate not in _VALID_GATES:
            warnings.append(f"workflow step {name or i!r}: unknown gate "
                            f"{step.gate!r} (expected {sorted(_VALID_GATES)})")
        stray = [t for t in step.tools if profile.allow_tools and t not in profile.allow_tools]
        if stray:
            warnings.append(f"workflow step {name or i!r} names tools not in "
                            f"allow_tools: {', '.join(stray)}")
    return errors, warnings


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
    if profile.effort is not None and profile.effort not in _VALID_EFFORTS:
        errors.append(f"effort {profile.effort!r} is not one of "
                      f"{sorted(_VALID_EFFORTS)}")
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
    allow = set(profile.allow_tools)
    if not (allow & {"shell", "code_exec"}):
        # A read-only/drafting pack: it should pin the mutators shut.
        deny = set(profile.deny_tools)
        ungated = [t for t in _READONLY_DENY_FLOOR if t not in deny and t not in allow]
        if ungated:
            warnings.append(
                "read-only pack doesn't explicitly deny "
                f"{', '.join(ungated)}: add to deny_tools for defense-in-depth "
                "(the allowlist already excludes them, but an explicit deny "
                "survives a later allowlist change)")
    warnings.extend(_lint_output(profile.output))
    wf_errors, wf_warnings = _lint_workflow(profile)
    errors.extend(wf_errors)
    warnings.extend(wf_warnings)
    # The deliverable's sign-off must not be lighter than the human-handoff its
    # own playbook ends on -- otherwise the contract under-states the gate.
    if profile.output.deliverable and profile.workflow:
        final_gate = profile.workflow[-1].gate
        if _GATE_RANK.get(final_gate, 0) > _GATE_RANK.get(profile.output.gate, 0):
            warnings.append(
                f"output.gate {profile.output.gate!r} is lighter than the final "
                f"workflow step's gate {final_gate!r}: raise output.gate so the "
                "deliverable's sign-off matches its playbook")
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
    from .domain_refusals import render_refusals
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
        persona=(augment_persona(profile.name, profile.persona)
                 + render_refusals(profile.name, profile.refuse)
                 + render_workflow_prompt(profile.workflow)),
        capability=cap,
        knowledge_sources=profile.knowledge_sources,
        domain_effort=profile.effort,
    )
