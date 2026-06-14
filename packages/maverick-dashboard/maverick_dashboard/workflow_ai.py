"""AI-drafted workflows.

Turn a natural-language brief (or the text of an uploaded document) into one of
two editable artifacts the operator can save and run:

  * a reusable, parameterized **template** (:func:`draft_workflow`) — saved via
    ``maverick.templates.save_user_template`` and run from the goal box, and
  * a specialist **agent playbook** (:func:`draft_playbook`) — a domain pack
    with a persona, a tool allowlist, a risk ceiling, and an ordered procedure
    whose steps can carry human gates; saved via the existing
    ``/agents/<name>/override`` path (``maverick.domain_edit.write_override``).

Each is one short structured LLM completion under a hard budget cap; the JSON
it returns is parsed forgivingly into a normalized draft.

The LLM call is isolated behind an injectable ``complete`` callable so the
parsing/normalizing — the part with all the edge cases — is unit-testable
without a provider key.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Drafting is one short structured completion; cap it hard and low so the
# feature can never become an expensive surprise (kernel rule 3: budget caps
# are not optional).
DRAFT_MAX_DOLLARS = 0.50
_MAX_PARAMS = 12
_MAX_STEPS = 20
_MAX_TOOLS = 40
_MAX_DOC_CHARS = 12_000

# Playbook gates and risk levels mirror maverick.domain (_VALID_GATES /
# _VALID_RISKS); kept local so this dashboard module stays self-contained and
# the loader stays the single source of truth at save time.
_PLAYBOOK_GATES = frozenset({"approval", "review"})
_RISKS = frozenset({"low", "medium", "high"})

WORKFLOW_SYSTEM = (
    "You design reusable, parameterized agent WORKFLOWS for Maverick. From the "
    "user's brief (and any provided document) produce ONE workflow as STRICT "
    "JSON with exactly this shape:\n"
    '{"name": "<slug: lowercase letters, digits, hyphens>", '
    '"title": "<short title; may contain {{param}} placeholders>", '
    '"params": ["<identifier>", ...], '
    '"steps": ["<imperative step>", ...], '
    '"budget_dollars": <number between 0.5 and 20>}\n'
    "Rules: 5-9 concrete, ordered steps an autonomous agent can execute. Use "
    "{{snake_case}} placeholders for the few values that change per run and "
    "list each placeholder name (without the braces) in params. Output the "
    "JSON object only — no prose, no code fence."
)

PLAYBOOK_SYSTEM = (
    "You design specialist AGENT PLAYBOOKS for Maverick: a governed domain "
    "agent with a persona, a tool allowlist, a risk ceiling, and an ordered "
    "procedure whose steps can require a human gate. From the user's brief (and "
    "any provided document) produce ONE playbook as STRICT JSON with exactly "
    "this shape:\n"
    '{"name": "<slug: lowercase letters, digits, hyphens>", '
    '"description": "<one sentence: what this specialist is for>", '
    '"persona": "<a few sentences addressed to the agent: who it is, how it '
    'works, the standards it holds>", '
    '"allow_tools": ["<tool the agent may use>", ...], '
    '"deny_tools": ["<tool it must never use>", ...], '
    '"max_risk": "low" | "medium" | "high", '
    '"steps": [{"name": "<short step name>", "instruction": "<what to do>", '
    '"tools": ["<tool used at this step>", ...], '
    '"gate": "approval" | "review" | null}]}\n'
    "Rules: 4-9 concrete, ordered steps. Put an \"approval\" gate on any step "
    "that takes an irreversible or outbound action (sending, paying, "
    "publishing, deleting) and a \"review\" gate where a human should check the "
    "work before it continues; otherwise gate is null. List in allow_tools only "
    "the tools the steps actually use. Set max_risk to the most sensitive "
    "action's level. Output the JSON object only — no prose, no code fence."
)

_SLUG = re.compile(r"[^a-z0-9-]+")
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


def build_prompt(brief: str, source_text: str = "", *, produce: str = "the workflow JSON") -> str:
    """Compose the user-turn prompt from the brief and optional document text."""
    brief = (brief or "").strip()
    parts = [f"BRIEF:\n{brief or '(none provided)'}"]
    doc = (source_text or "").strip()
    if doc:
        parts.append("DOCUMENT (extract the workflow from this):\n" + doc[:_MAX_DOC_CHARS])
    parts.append(f"Produce {produce}.")
    return "\n\n".join(parts)


def build_refine_prompt(current: dict[str, Any], instruction: str) -> str:
    """Compose the user turn for a *refinement*: the current draft plus the
    change to apply. The model returns the FULL revised draft in the same JSON
    shape (the system prompt is unchanged), so the same parser normalizes it."""
    return (
        "Here is the current draft as JSON:\n"
        + json.dumps(current or {}, ensure_ascii=False)
        + "\n\nApply this change and return the COMPLETE revised draft in the "
        "same JSON shape (not a diff, not only the changed fields):\n"
        + (instruction or "").strip()
    )


def _slugify(name: str, fallback: str = "workflow") -> str:
    s = _SLUG.sub("-", (name or "").strip().lower()).strip("-")
    return (s or fallback)[:48]


def _strip_fence(raw: str) -> str:
    """Drop a leading ``` / ```json code fence the model may wrap JSON in."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw[:4].lower() == "json":
            raw = raw[4:].strip()
    return raw


def _clean_tools(raw: object) -> list[str]:
    """Trimmed, de-duplicated, bounded list of tool names (drops blanks)."""
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for t in raw:
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= _MAX_TOOLS:
            break
    return out


def parse_workflow(raw: str) -> dict[str, Any]:
    """Parse the model's reply into a normalized draft dict.

    Forgiving by design: strips a ``` / ```json fence, coerces types, clamps
    the budget, keeps only identifier-like params, and renders the steps into a
    numbered markdown body. Raises ``ValueError`` only when there's nothing
    usable (non-JSON, or no steps)."""
    raw = _strip_fence(raw)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValueError("the model did not return valid workflow JSON") from e
    if not isinstance(data, dict):
        raise ValueError("workflow JSON must be a single object")

    steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()][:_MAX_STEPS]
    if not steps:
        raise ValueError("the drafted workflow had no steps")

    title = " ".join(str(data.get("title") or "Workflow").split())[:200]
    name = _slugify(str(data.get("name") or title))

    params: list[str] = []
    for p in (data.get("params") or []):
        p = str(p).strip()
        if _IDENT.match(p) and p not in params:
            params.append(p)
        if len(params) >= _MAX_PARAMS:
            break

    try:
        budget = float(data.get("budget_dollars") or 5.0)
    except (TypeError, ValueError):
        budget = 5.0
    budget = max(0.5, min(budget, 20.0))

    body = "## Steps\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return {
        "name": name,
        "title": title,
        "params": params,
        "steps": steps,
        "body": body,
        "budget_dollars": round(budget, 2),
    }


def _run_completion(
    system: str,
    user_content: str,
    *,
    complete: Callable[..., Any] | None,
    max_tokens: int,
) -> str:
    """One structured completion under the hard ``DRAFT_MAX_DOLLARS`` cap, used
    by every draft/refine path. ``complete`` (an ``LLM.complete``-style callable)
    is injectable for tests; by default a fresh role-resolved LLM is used — never
    a hard-coded model (kernel rule 2). Returns the raw reply text."""
    from maverick.budget import Budget

    if complete is None:
        from maverick.llm import LLM, model_for_role
        complete = LLM(model=model_for_role("orchestrator")).complete

    budget = Budget(max_dollars=DRAFT_MAX_DOLLARS)
    resp = complete(
        system=system,
        messages=[{"role": "user", "content": user_content}],
        budget=budget,
        max_tokens=max_tokens,
        model=None,
    )
    return getattr(resp, "text", "") or ""


def draft_workflow(
    brief: str,
    source_text: str = "",
    *,
    complete: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Draft a workflow from a brief and/or document text.

    Makes one LLM completion under a hard ``DRAFT_MAX_DOLLARS`` cap and returns
    the normalized draft."""
    return parse_workflow(_run_completion(
        WORKFLOW_SYSTEM, build_prompt(brief, source_text),
        complete=complete, max_tokens=1200,
    ))


def refine_workflow(
    current: dict[str, Any],
    instruction: str,
    *,
    complete: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Revise an existing workflow draft per a natural-language ``instruction``
    (e.g. "add a step to email the summary"). Same cap and parser as
    :func:`draft_workflow`; returns the full normalized, revised draft."""
    return parse_workflow(_run_completion(
        WORKFLOW_SYSTEM, build_refine_prompt(current, instruction),
        complete=complete, max_tokens=1200,
    ))


def parse_playbook(raw: str) -> dict[str, Any]:
    """Parse the model's reply into a normalized agent-playbook draft.

    Forgiving like :func:`parse_workflow`: strips a code fence, coerces types,
    validates the gate and risk vocabularies (an unknown gate is dropped, an
    unknown risk defaults to ``"medium"``), keeps only non-empty tool names, and
    derives a starting allowlist from the steps' own tools when the model gave
    none. Raises ``ValueError`` only when there's nothing usable (non-JSON, or
    no steps). The returned dict matches the shape the ``/agents/<name>/override``
    save path (``AgentOverrideIn``) accepts — ``workflow`` is the editable
    playbook, each step ``{name, instruction, tools, gate}``."""
    raw = _strip_fence(raw)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValueError("the model did not return valid playbook JSON") from e
    if not isinstance(data, dict):
        raise ValueError("playbook JSON must be a single object")

    # Accept "steps" (our prompt) or "workflow" (the pack's own key) for resilience.
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("workflow")
    steps: list[dict[str, Any]] = []
    for item in (raw_steps or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        gate = str(item.get("gate") or "").strip().lower()
        steps.append({
            "name": name[:80],
            "instruction": " ".join(str(item.get("instruction") or "").split())[:600],
            "tools": _clean_tools(item.get("tools")),
            "gate": gate if gate in _PLAYBOOK_GATES else None,
        })
        if len(steps) >= _MAX_STEPS:
            break
    if not steps:
        raise ValueError("the drafted playbook had no steps")

    description = " ".join(str(data.get("description") or "").split())[:300]
    name = _slugify(str(data.get("name") or description or "agent"), fallback="agent")
    persona = str(data.get("persona") or "").strip()[:4000]

    allow = _clean_tools(data.get("allow_tools"))
    if not allow:  # fall back to the union of the steps' own tool hints
        for s in steps:
            for t in s["tools"]:
                if t not in allow:
                    allow.append(t)
        allow = allow[:_MAX_TOOLS]

    risk = str(data.get("max_risk") or "").strip().lower()
    if risk not in _RISKS:
        risk = "medium"

    return {
        "form": "playbook",
        "name": name,
        "description": description,
        "persona": persona,
        "allow_tools": allow,
        "deny_tools": _clean_tools(data.get("deny_tools")),
        "max_risk": risk,
        "workflow": steps,
    }


def draft_playbook(
    brief: str,
    source_text: str = "",
    *,
    complete: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Draft a specialist agent playbook from a brief and/or document text.

    The playbook counterpart to :func:`draft_workflow`: one LLM completion under
    the same hard ``DRAFT_MAX_DOLLARS`` cap, returning a normalized draft the
    operator edits and saves as a domain pack."""
    return parse_playbook(_run_completion(
        PLAYBOOK_SYSTEM, build_prompt(brief, source_text, produce="the playbook JSON"),
        complete=complete, max_tokens=1500,
    ))


def refine_playbook(
    current: dict[str, Any],
    instruction: str,
    *,
    complete: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Revise an existing playbook draft per a natural-language ``instruction``
    (e.g. "require approval before any payment"). Same cap and parser as
    :func:`draft_playbook`; returns the full normalized, revised draft."""
    return parse_playbook(_run_completion(
        PLAYBOOK_SYSTEM, build_refine_prompt(current, instruction),
        complete=complete, max_tokens=1500,
    ))
