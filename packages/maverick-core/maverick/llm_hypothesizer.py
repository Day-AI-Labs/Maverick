"""LLM-creative hypothesis generation for the Operations Scientist.

``operations_scientist.propose_creative`` takes an injected
``generate(failure_class) -> list[str]``; this is the LLM-backed implementation of
that seam. It builds a prompt from a causally-harmful failure class, asks the
model for concrete alternative actions, and parses the reply into candidate
action names -- which the Operations Scientist then *validates in the
world-model* before any real experiment, so a hallucinated suggestion can't reach
production on the model's say-so.

The actual completion is injected (a ``(prompt: str) -> str`` callable), so the
prompt-building and response-parsing -- the only non-trivial logic -- are fully
testable without a provider key. Wiring it to a real model is the caller's
two-liner::

    from maverick.llm import LLM
    llm = LLM(...)
    gen = lambda fc: generate_interventions(fc, llm.complete)
    hyps = operations_scientist.propose_creative(classes, generate=gen)
"""
from __future__ import annotations

import re

_PROMPT = (
    "You are an operations scientist improving an AI agent workforce.\n"
    "The action '{action}' has been shown — by causal analysis of real production "
    "outcomes — to LOWER task success (effect {effect:+.2f}).\n"
    "Suggest up to {n} concrete alternative actions or tools that could replace it "
    "and improve outcomes. Each must be a single short action name (e.g. a tool "
    "name), not a sentence.\n"
    "Respond with ONLY the action names, one per line, no numbering or explanation."
)

# Strip list bullets / numbering / quoting / code-fencing from a candidate line.
_CLEAN = re.compile(r"^[\s\-\*\d\.\)•`'\"]+|[`'\".]+$")


def build_prompt(failure_class, *, n: int = 3) -> str:
    """The instruction asking the model to propose replacements for a harmful action."""
    return _PROMPT.format(
        action=failure_class.action, effect=float(failure_class.causal_effect), n=int(n))


def parse_interventions(text: str, *, n: int = 3) -> list[str]:
    """Extract up to ``n`` clean, de-duplicated action names from a model reply."""
    out: list[str] = []
    seen: set = set()
    for raw in (text or "").splitlines():
        token = _CLEAN.sub("", raw).strip()
        # Keep it action-name-shaped: a single token-ish phrase, not prose.
        if not token or len(token.split()) > 4 or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= n:
            break
    return out


def generate_interventions(failure_class, complete, *, n: int = 3) -> list[str]:
    """Ask the model (via the injected ``complete``) for replacement actions.

    ``complete`` is a ``(prompt: str) -> str`` callable. Returns [] on any error
    (a flaky model never breaks the discovery loop), so it's a drop-in
    ``generate`` for ``operations_scientist.propose_creative``.
    """
    try:
        text = complete(build_prompt(failure_class, n=n))
    except Exception:  # pragma: no cover -- the generator must never crash discovery
        return []
    return parse_interventions(text, n=n)


__all__ = ["build_prompt", "parse_interventions", "generate_interventions"]
