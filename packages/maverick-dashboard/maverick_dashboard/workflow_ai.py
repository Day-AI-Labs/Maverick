"""AI-drafted workflows.

Turn a natural-language brief (or the text of an uploaded document) into a
reusable, parameterized **workflow** the operator can edit, save (as a
Template), and run. One short structured LLM completion under a hard budget
cap; the JSON it returns is parsed forgivingly into a normalized draft.

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
_MAX_DOC_CHARS = 12_000

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

_SLUG = re.compile(r"[^a-z0-9-]+")
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


def build_prompt(brief: str, source_text: str = "") -> str:
    """Compose the user-turn prompt from the brief and optional document text."""
    brief = (brief or "").strip()
    parts = [f"BRIEF:\n{brief or '(none provided)'}"]
    doc = (source_text or "").strip()
    if doc:
        parts.append("DOCUMENT (extract the workflow from this):\n" + doc[:_MAX_DOC_CHARS])
    parts.append("Produce the workflow JSON.")
    return "\n\n".join(parts)


def _slugify(name: str, fallback: str = "workflow") -> str:
    s = _SLUG.sub("-", (name or "").strip().lower()).strip("-")
    return (s or fallback)[:48]


def parse_workflow(raw: str) -> dict[str, Any]:
    """Parse the model's reply into a normalized draft dict.

    Forgiving by design: strips a ``` / ```json fence, coerces types, clamps
    the budget, keeps only identifier-like params, and renders the steps into a
    numbered markdown body. Raises ``ValueError`` only when there's nothing
    usable (non-JSON, or no steps)."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw[:4].lower() == "json":
            raw = raw[4:].strip()
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


def draft_workflow(
    brief: str,
    source_text: str = "",
    *,
    complete: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Draft a workflow from a brief and/or document text.

    Makes one LLM completion under a hard ``DRAFT_MAX_DOLLARS`` cap and returns
    the normalized draft. ``complete`` (an ``LLM.complete``-style callable) is
    injectable for tests; by default a fresh role-resolved LLM is used — never
    a hard-coded model (kernel rule 2)."""
    from maverick.budget import Budget

    if complete is None:
        from maverick.llm import LLM, model_for_role
        complete = LLM(model=model_for_role("orchestrator")).complete

    budget = Budget(max_dollars=DRAFT_MAX_DOLLARS)
    resp = complete(
        system=WORKFLOW_SYSTEM,
        messages=[{"role": "user", "content": build_prompt(brief, source_text)}],
        budget=budget,
        max_tokens=1200,
        model=None,
    )
    return parse_workflow(getattr(resp, "text", "") or "")
