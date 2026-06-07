"""Intake -- the agent factory's front door.

Turns "what the business does" + its uploaded documents into a live, sealed,
knowledge-loaded domain agent:

    IntakeSpec --generate(LLM)--> DomainProfile --validate/clamp--> human approve
        --> save to ~/.maverick/domains/ --> agent_from_profile

The pack is LLM-generated (persona *and* capability envelope) from the business
description, but ALWAYS passed through ``validate_profile`` first -- a freshly
generated pack can never auto-grant high-impact tools or escalate risk. A human
widens the envelope at approval. This is the compartment "door" philosophy
applied to onboarding: an unvetted, model-authored agent starts locked down.

This module is the generation + safety core. The conversational intake agent
(interview + document/diagram collection) and the ``maverick onboard`` UX build
on top of it, supplying the ``propose`` callable and the human-approval step.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .domain import DomainProfile, user_dir

log = logging.getLogger(__name__)

# A freshly-generated pack must not auto-grant high-impact tools; a human widens
# the envelope at approval. Generation cannot self-escalate past this floor.
_GENERATED_DENY = frozenset({
    "shell", "write_file", "edit_file", "delete_file", "code_exec",
    "computer", "browser", "clipboard",
})
_MAX_GENERATED_RISK = "medium"


@dataclass
class IntakeSpec:
    """What we learned about a business during intake."""
    name: str
    description: str = ""
    industry: str = ""
    goals: list[str] = field(default_factory=list)
    doc_paths: list[str] = field(default_factory=list)


def _slug(name: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in (name or "").lower())
    return "_".join(filter(None, s.split("_"))) or "business"


def _default_persona(spec: IntakeSpec) -> str:
    who = spec.description or (f"a {spec.industry} business" if spec.industry else "this business")
    return (
        f"You are a specialist assistant for {spec.name} ({who}). Answer from the "
        "company's uploaded documents first and cite them; say plainly when the "
        "documents don't cover something rather than guessing."
    )


def validate_profile(profile: DomainProfile) -> DomainProfile:
    """Clamp a generated pack to a safe envelope: union a baseline deny set,
    strip denied or over-ceiling tools out of allow, and cap ``max_risk``.
    Mutates and returns the profile. A human widens this at approval; the
    generator cannot."""
    from .safety.tool_risk import risk_rank, tool_risk

    if profile.max_risk is None or risk_rank(profile.max_risk) > risk_rank(_MAX_GENERATED_RISK):
        profile.max_risk = _MAX_GENERATED_RISK
    ceiling = risk_rank(profile.max_risk)
    over_ceiling = {
        tool for tool in profile.allow_tools
        if risk_rank(tool_risk(tool)) > ceiling
    }
    deny = set(profile.deny_tools) | _GENERATED_DENY | over_ceiling
    profile.deny_tools = sorted(deny)
    profile.allow_tools = [t for t in profile.allow_tools if t not in deny]
    if not profile.compartment:
        profile.compartment = profile.name
    profile.authoring = "generated"
    return profile


def generate_profile(spec: IntakeSpec, propose=None) -> DomainProfile:
    """Turn an IntakeSpec into a validated DomainProfile.

    ``propose(spec) -> dict`` is the pluggable generator: an LLM in production
    (keys: persona, description, allow_tools, deny_tools, max_risk), or ``None``
    for a deterministic fallback. The proposed envelope is ALWAYS run through
    ``validate_profile``, so the result is safe regardless of what the model
    returned (or if it failed)."""
    name = _slug(spec.name)
    proposed: dict = {}
    if propose is not None:
        try:
            proposed = propose(spec) or {}
        except Exception as e:  # generation must fail soft to a safe default
            log.warning("intake: proposer failed (%s); using default pack", e)

    profile = DomainProfile(
        name=name,
        compartment=name,
        description=str(proposed.get("description") or spec.description),
        persona=str(proposed.get("persona") or _default_persona(spec)),
        allow_tools=list(proposed.get("allow_tools") or ["read_file", "web_search"]),
        deny_tools=list(proposed.get("deny_tools") or []),
        max_risk=proposed.get("max_risk"),
        knowledge_sources=[name],
        authoring="generated",
    )
    return validate_profile(profile)


def ingest_docs(spec: IntakeSpec, kb, collection: str | None = None) -> int:
    """Ingest the spec's uploaded documents into the pack's knowledge collection.
    Returns the number of chunks stored. Fail-soft per document."""
    collection = collection or _slug(spec.name)
    total = 0
    for path in spec.doc_paths:
        try:
            total += kb.ingest_path(collection, path)
        except Exception as e:  # one bad upload must not abort onboarding
            log.warning("intake: failed to ingest %s (%s)", path, e)
    return total


def _to_toml(p: DomainProfile) -> str:
    # json.dumps emits valid TOML string/array literals (incl. \n-escaped
    # multi-line personas), so a generated pack round-trips through load_domain.
    lines = [
        f"name = {json.dumps(p.name)}",
        f"compartment = {json.dumps(p.compartment)}",
        f"description = {json.dumps(p.description)}",
        f"persona = {json.dumps(p.persona)}",
        f"allow_tools = {json.dumps(p.allow_tools)}",
        f"deny_tools = {json.dumps(p.deny_tools)}",
        f"max_risk = {json.dumps(p.max_risk)}" if p.max_risk else "",
        f"knowledge_sources = {json.dumps(p.knowledge_sources)}",
        f"authoring = {json.dumps(p.authoring)}",
    ]
    return "\n".join(line for line in lines if line) + "\n"


def save_profile(profile: DomainProfile, *, approved: bool,
                 dest_dir: str | Path | None = None) -> str:
    """Persist an APPROVED pack so ``available_domains()`` picks it up. Refuses
    to write a pack that hasn't been human-approved -- the safety gate is here."""
    if not approved:
        raise PermissionError("refusing to save an unapproved generated pack")
    d = Path(dest_dir) if dest_dir else user_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{profile.name}.toml"
    path.write_text(_to_toml(profile), encoding="utf-8")
    return str(path)


_PROPOSER_SYSTEM = (
    "You configure a specialist business-assistant agent. Given a business "
    "description, return ONLY a JSON object with these keys:\n"
    '  "persona": the agent\'s system instructions (string),\n'
    '  "description": a one-line summary (string),\n'
    '  "allow_tools": array of tool names it needs (e.g. read_file, web_search),\n'
    '  "max_risk": "low" or "medium".\n'
    "Never include shell, code-execution, or file-writing tools. Output JSON only."
)


def _intake_prompt(spec: IntakeSpec) -> str:
    parts = [f"Business name: {spec.name}"]
    if spec.industry:
        parts.append(f"Industry: {spec.industry}")
    if spec.description:
        parts.append(f"What they do: {spec.description}")
    if spec.goals:
        parts.append("Goals: " + "; ".join(spec.goals))
    return "\n".join(parts)


def _parse_proposal(text: str) -> dict:
    """Extract the JSON pack from an LLM response and sanitize it to expected
    types. Returns {} on anything unparseable -- generate_profile then uses its
    safe default, and validate_profile clamps the result regardless."""
    if not text:
        return {}
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for key in ("persona", "description", "max_risk"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    for key in ("allow_tools", "deny_tools"):
        v = data.get(key)
        if isinstance(v, list):
            out[key] = [str(x) for x in v if isinstance(x, str)]
    return out


def build_llm_proposer(llm, *, model: str | None = None, budget=None):
    """A ``propose(spec)`` callable backed by an LLM -- the generative authoring
    path ("describe the business, we synthesize the pack"). The result is still
    run through ``validate_profile``, so the model can't widen the envelope."""
    def propose(spec: IntakeSpec) -> dict:
        resp = llm.complete(
            system=_PROPOSER_SYSTEM,
            messages=[{"role": "user", "content": _intake_prompt(spec)}],
            model=model, budget=budget, max_tokens=1500,
        )
        return _parse_proposal(getattr(resp, "text", "") or "")

    return propose


def run_intake(spec: IntakeSpec, *, llm=None, kb=None,
               model: str | None = None, budget=None) -> DomainProfile:
    """Ingest the business's documents and generate a validated (but UNSAVED)
    DomainProfile for human approval. Pass ``llm`` to use the generative path;
    omit it for the deterministic fallback. Persisting is a separate, approved
    step (``save_profile``)."""
    if kb is not None:
        ingest_docs(spec, kb)
    propose = (
        build_llm_proposer(llm, model=model, budget=budget) if llm is not None else None
    )
    return generate_profile(spec, propose=propose)


INTAKE_PERSONA = (
    "You are Maverick's onboarding specialist. Interview the business to learn "
    "what it does, its industry, and its goals, and ask for any documents or "
    "process diagrams it can share. As you learn, call record_business, "
    "add_goal, and add_document. Ask one focused question at a time -- don't "
    "overwhelm. Once you have the business's name and a clear sense of what it "
    "does, call finalize_intake to draft its specialist agent, then tell the "
    "user the draft is ready for review. You NEVER activate an agent yourself; "
    "a human approves it."
)


@dataclass
class IntakeSession:
    """Evolving state of a conversational intake. The intake agent fills it via
    the intake tools; ``finalize`` turns it into a validated (unsaved) pack."""
    name: str = ""
    description: str = ""
    industry: str = ""
    goals: list[str] = field(default_factory=list)
    doc_paths: list[str] = field(default_factory=list)

    def to_spec(self) -> IntakeSpec:
        return IntakeSpec(
            name=self.name or "business", description=self.description,
            industry=self.industry, goals=list(self.goals),
            doc_paths=list(self.doc_paths),
        )

    def is_ready(self) -> bool:
        """Enough to draft a pack: a name plus some sense of what they do."""
        return bool(self.name and (self.description or self.industry))

    def finalize(self, *, llm=None, kb=None) -> DomainProfile:
        return run_intake(self.to_spec(), llm=llm, kb=kb)


def build_intake_agent(ctx, session: IntakeSession | None = None, *, llm=None, kb=None):
    """Construct the conversational intake agent: an Agent with the onboarding
    persona and the intake tools bound to a shared IntakeSession. Returns
    ``(agent, session)``. The live chat loop reuses the normal agent/channel
    surface; this just assembles the interviewer."""
    from .agent import Agent
    from .tools.intake_tools import intake_tools

    session = session or IntakeSession()
    agent = Agent(
        ctx=ctx, role="intake",
        brief="Interview the business and assemble its specialist agent.",
        persona=INTAKE_PERSONA,
    )
    for tool in intake_tools(session, llm=llm or getattr(ctx, "llm", None),
                             kb=kb or getattr(ctx, "knowledge", None)):
        agent.tools.register(tool)
    return agent, session
