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
    "computer", "browser",
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
    strip denied tools out of allow, and cap ``max_risk``. Mutates and returns
    the profile. A human widens this at approval; the generator cannot."""
    from .safety.tool_risk import risk_rank

    deny = set(profile.deny_tools) | _GENERATED_DENY
    profile.deny_tools = sorted(deny)
    profile.allow_tools = [t for t in profile.allow_tools if t not in deny]
    if profile.max_risk is None or risk_rank(profile.max_risk) > risk_rank(_MAX_GENERATED_RISK):
        profile.max_risk = _MAX_GENERATED_RISK
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
