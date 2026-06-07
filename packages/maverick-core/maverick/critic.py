"""Critic: graded, structured critique of an agent's output.

Distinct from the verifier (which gates pass/fail): a critic returns *graded*
feedback — a confidence score, a list of concrete issues, and a recommendation
(accept / revise / reject) — to drive an iterative improvement loop without
hard-stopping. The LLM call is injected (``complete``) so the parsing + prompt
logic is unit-tested with a fake model; ``review`` tolerates a JSON object
embedded in prose and degrades to safe defaults on a malformed reply.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

_RECOMMENDATIONS = ("accept", "revise", "reject")


@dataclass
class CriticReview:
    confidence: float            # 0.0–1.0
    recommendation: str          # accept | revise | reject
    issues: list[str] = field(default_factory=list)
    raw: str = ""


def _build_prompt(output: str, criteria: str) -> str:
    crit = f"\nEvaluate against these criteria:\n{criteria}\n" if criteria else "\n"
    return (
        "You are a critic. Review the work below and respond with ONLY a JSON "
        'object: {"confidence": <0..1>, "recommendation": "accept|revise|reject", '
        '"issues": ["..."]}. confidence is how strongly you endorse the work; '
        "list concrete, actionable issues (empty if none)." + crit +
        "\n--- WORK ---\n" + (output or "") + "\n--- END ---"
    )


def _extract_json(raw: str) -> dict:
    """Best-effort: parse a JSON object, even when wrapped in prose/code fences."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def _coerce(data: dict, raw: str) -> CriticReview:
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rec = str(data.get("recommendation", "")).strip().lower()
    if rec not in _RECOMMENDATIONS:
        # Infer from confidence when the model omitted/garbled the field.
        rec = "accept" if confidence >= 0.8 else "revise" if confidence >= 0.4 else "reject"
    issues_raw = data.get("issues") or []
    if isinstance(issues_raw, str):
        issues_raw = [issues_raw]
    issues = [str(i).strip() for i in issues_raw if str(i).strip()]
    return CriticReview(confidence=confidence, recommendation=rec,
                        issues=issues, raw=raw)


class Critic:
    """Wrap an LLM ``complete(prompt) -> str`` as a structured critic."""

    def __init__(self, complete: Callable[[str], str]):
        self._complete = complete

    def review(self, output: str, criteria: str = "") -> CriticReview:
        raw = self._complete(_build_prompt(output, criteria))
        return _coerce(_extract_json(raw), raw if isinstance(raw, str) else str(raw))


__all__ = ["Critic", "CriticReview"]
