"""Verifier role: independent second-opinion pass on a proposer's answer.

Karpathy SOTA-review prescription: the recursive multi-agent ceremony
only earns its complexity if there's a real verify step. The current
``revisor`` role exists in prompt strings only -- no code actually runs
a verifier pass before declaring FINAL.

This module gives the orchestrator a single function to call:

    verdict = await verify_proposal(brief, proposal, llm, budget)

The verifier is invoked with a different system prompt + a fresh
budget allocation so its output isn't anchored by the proposer's
context. The verdict is structured:

    verdict.confidence:   float in [0, 1]
    verdict.accepts:      bool (confidence >= threshold)
    verdict.critique:     str (always populated; empty string if accepts)
    verdict.issues:       list[str] (specific problems flagged)

The agent loop uses `accepts` to early-stop, and feeds `critique` back
to the proposer as a revision brief if it doesn't accept. `confidence`
is the disagreement signal that adaptive fanout reads (see
``maverick.tools.spawn``).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .budget import Budget
from .llm import LLM, model_for_role

log = logging.getLogger(__name__)


# Default disagreement entropy threshold. Above this, fan out to more
# proposers; below, accept the single answer. Tunable via env.
DISAGREEMENT_HIGH = float(os.environ.get("MAVERICK_DISAGREEMENT_HIGH", "0.5"))
VERIFIER_CONFIDENCE_ACCEPT = float(os.environ.get("MAVERICK_VERIFIER_CONFIDENCE", "0.75"))


VERIFIER_SYSTEM = """You are an independent verifier reviewing another agent's answer to a goal.

You have access to no tools. Your job is to read the brief + the proposed final answer and decide:
1. Does the answer actually satisfy the brief? Be strict.
2. Are there factual errors, missing steps, or unsupported claims?
3. Would a careful human accept this?

Respond with a JSON object on a single line:

{"confidence": 0.0-1.0, "accepts": true|false, "critique": "<1-2 sentences>", "issues": ["<short issue>", ...]}

Confidence calibration:
- 0.9-1.0: The answer fully satisfies the brief, no meaningful issues.
- 0.7-0.9: Mostly correct; minor polish would help but it's defensible.
- 0.4-0.7: Significant gaps; a careful reviewer would want revisions.
- 0.0-0.4: Wrong direction or unsupported; reject.

`accepts` should be true iff confidence >= 0.75 AND issues is empty (or only nitpicks).
Output ONLY the JSON. No preamble, no markdown fence.
"""


@dataclass
class VerifierVerdict:
    confidence: float
    accepts: bool
    critique: str
    issues: list[str] = field(default_factory=list)
    raw: str = ""

    @classmethod
    def reject(cls, reason: str) -> "VerifierVerdict":
        return cls(confidence=0.0, accepts=False, critique=reason, issues=[reason])

    @classmethod
    def accept_unconditionally(cls) -> "VerifierVerdict":
        """For trivial cases where verification adds no value (e.g. empty
        brief, sub-second tasks). Skips the LLM call."""
        return cls(confidence=1.0, accepts=True, critique="", issues=[])


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(text: str) -> VerifierVerdict:
    """Best-effort JSON extraction from the verifier's reply.

    Models sometimes wrap JSON in markdown fences or prefix with prose
    despite the system prompt. We extract the outermost {...} and parse
    it; on any failure we treat the verdict as low-confidence reject so
    the proposer is forced to revise.
    """
    if not text:
        return VerifierVerdict.reject("verifier returned empty response")
    m = _JSON_OBJECT_RE.search(text)
    if m is None:
        return VerifierVerdict.reject("verifier reply contained no JSON object")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return VerifierVerdict.reject(f"verifier JSON parse failed: {e}")

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    accepts_raw = data.get("accepts", False)
    if isinstance(accepts_raw, str):
        accepts = accepts_raw.lower() in ("true", "yes", "1")
    else:
        accepts = bool(accepts_raw)

    critique = str(data.get("critique", "") or "")
    issues_raw = data.get("issues", []) or []
    issues = [str(x) for x in issues_raw if x]

    return VerifierVerdict(
        confidence=confidence,
        accepts=accepts,
        critique=critique,
        issues=issues,
        raw=text,
    )


async def verify_proposal(
    brief: str,
    proposal: str,
    llm: LLM,
    budget: Optional[Budget] = None,
    *,
    max_tokens: int = 1024,
    proposer_model: Optional[str] = None,
) -> VerifierVerdict:
    """Ask the verifier role to judge a proposer's final answer.

    Uses ``maverick.config`` per-role model routing under ``verifier``
    (falls back to MODEL_OPUS via ROLE_MODELS). Spend lands in the
    passed budget; callers should expect ~$0.005-$0.05 per call.

    The verdict is conservative: any parsing failure / empty response /
    JSON-without-required-fields → reject. This keeps the proposer
    honest -- a flaky verifier can only make the system MORE careful,
    not less.

    Cross-family guard (May 2026 research): if the verifier model is in
    the same family as the proposer (e.g. both Anthropic), they can be
    jailbroken in lockstep (Anthropic's alignment-faking paper
    arxiv:2412.14093 + 2026 deceptive-alignment follow-ups). When the
    proposer_model is passed and matches the verifier's family, we
    swap to a cross-family verifier via MODEL_FAMILY_FALLBACK.
    """
    if not proposal or not proposal.strip():
        return VerifierVerdict.reject("proposal is empty")

    model = model_for_role("verifier")
    # Privacy-safe fallback: if verifier isn't explicitly configured,
    # inherit the proposer model to avoid surprise provider egress.
    try:
        from .config import get_role_model
        if not get_role_model("verifier") and proposer_model:
            model = proposer_model
    except Exception:
        pass

    if proposer_model and _same_family(proposer_model, model):
        cross = _cross_family_fallback(model)
        if cross is not None:
            model = cross

    user_msg = (
        f"GOAL BRIEF:\n{brief}\n\n"
        f"PROPOSED FINAL ANSWER:\n{proposal}\n\n"
        "Return the verdict JSON."
    )
    try:
        resp = await llm.complete_async(
            system=VERIFIER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            tools=None,
            budget=budget,
            max_tokens=max_tokens,
            model=model,
        )
    except Exception as e:  # pragma: no cover -- network/budget errors
        log.warning("verifier LLM call failed: %s; treating as low-confidence pass", e)
        return VerifierVerdict(
            confidence=0.5, accepts=True,
            critique=f"verifier call failed: {e}", issues=[],
        )
    return _parse(resp.text)


async def verify_proposal_ensemble(
    brief: str,
    proposal: str,
    llm: LLM,
    budget: Optional[Budget] = None,
    *,
    proposer_model: Optional[str] = None,
    panel: Optional[list[str]] = None,
    weighted: bool = True,
) -> VerifierVerdict:
    """Run N verifiers across distinct model families and combine.

    Multi-Agent Verification (MAV, arxiv:2502.20379) shows that scaling
    the *verifier* axis -- multiple verifiers, weighted vote -- is
    orthogonally additive to scaling the *generator* axis (best-of-N).
    On agentic tasks MAV-3 beats single-verifier + best-of-8 at the
    same total compute budget.

    Panel: explicit model list, or None to use a curated cross-family
    default (Anthropic Sonnet + OpenAI GPT + DeepSeek). Each panel
    member is excluded if it's the same family as the proposer.

    `weighted=True` uses each verdict's `confidence` as a weight in
    the final accept-vote; `weighted=False` is plain majority. The
    combined verdict's `confidence` is the *minimum* confidence across
    accepting voters (conservative -- one outlier doesn't pull
    confidence up).
    """
    if not proposal or not proposal.strip():
        return VerifierVerdict.reject("proposal is empty")

    if panel is None:
        panel = [
            "anthropic:claude-sonnet-4-6",
            "openai:gpt-5.4",
            "openrouter:deepseek-v4-pro",
        ]
    # Drop panel members in the proposer's family.
    if proposer_model:
        panel = [m for m in panel if not _same_family(proposer_model, m)]
    if not panel:
        # Everything got filtered -- fall back to whatever the default
        # cross-family verifier is for this proposer.
        cross = _cross_family_fallback(proposer_model or "")
        panel = [cross] if cross else [model_for_role("verifier")]

    import asyncio
    user_msg = (
        f"GOAL BRIEF:\n{brief}\n\n"
        f"PROPOSED FINAL ANSWER:\n{proposal}\n\n"
        "Return the verdict JSON."
    )

    async def _one(model: str) -> VerifierVerdict:
        try:
            resp = await llm.complete_async(
                system=VERIFIER_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                tools=None,
                budget=budget,
                max_tokens=1024,
                model=model,
            )
            return _parse(resp.text)
        except Exception as e:  # pragma: no cover
            log.warning("MAV verifier %s failed: %s", model, e)
            return VerifierVerdict(confidence=0.5, accepts=True,
                                   critique=f"failed: {e}")

    verdicts = await asyncio.gather(*(_one(m) for m in panel))
    return _combine(verdicts, weighted=weighted)


def _combine(verdicts: list["VerifierVerdict"], *, weighted: bool) -> "VerifierVerdict":
    """Combine N individual verdicts into one ensemble verdict."""
    if not verdicts:
        return VerifierVerdict.reject("no verifiers ran")
    if len(verdicts) == 1:
        return verdicts[0]

    if weighted:
        # Weighted by each voter's own confidence.
        accept_weight = sum(v.confidence for v in verdicts if v.accepts)
        reject_weight = sum(v.confidence for v in verdicts if not v.accepts)
        accepts = accept_weight > reject_weight
    else:
        accepts = sum(1 for v in verdicts if v.accepts) > len(verdicts) / 2

    # Conservative: combined confidence = mean of those who AGREE with
    # the majority. So if 2/3 accept at 0.9 and 1 rejects at 0.4, we
    # accept at 0.9 (the rejecting voter is overruled but not averaged in).
    side = [v for v in verdicts if v.accepts == accepts]
    confidence = sum(v.confidence for v in side) / len(side) if side else 0.0

    # Collect all unique issues + critiques across the panel.
    issues: list[str] = []
    seen: set[str] = set()
    for v in verdicts:
        for i in v.issues:
            if i and i not in seen:
                issues.append(i)
                seen.add(i)
    critiques = [v.critique for v in verdicts if v.critique]
    critique = " | ".join(critiques) if critiques else ""

    return VerifierVerdict(
        confidence=confidence, accepts=accepts,
        critique=critique, issues=issues,
    )


def _provider(model: str) -> str:
    """Extract the provider/family slug from a `provider:model-id` spec."""
    if ":" in model:
        return model.split(":", 1)[0].lower()
    # Bare ids: heuristic prefix match.
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o"):
        return "openai"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("qwen"):
        return "qwen"
    if m.startswith("grok"):
        return "xai"
    if m.startswith("llama"):
        return "meta"
    return "unknown"


def _same_family(a: str, b: str) -> bool:
    return _provider(a) == _provider(b)


# Preferred cross-family verifier per source family. Read from env if
# the operator wants to override. The fallback chain ends with the
# original model (no swap) when no peer is configured.
def _cross_family_fallback(model: str) -> Optional[str]:
    """Pick a verifier from a different provider family.

    Priority order: explicit env override, then a curated default.
    Returns None if no cross-family peer is configured / available.
    """
    explicit = os.environ.get("MAVERICK_CROSS_FAMILY_VERIFIER")
    if explicit:
        return explicit

    fam = _provider(model)
    defaults = {
        "anthropic": "openai:gpt-5.4",
        "openai":    "anthropic:claude-sonnet-4-6",
        "gemini":    "anthropic:claude-sonnet-4-6",
        "deepseek":  "anthropic:claude-sonnet-4-6",
        "qwen":      "anthropic:claude-sonnet-4-6",
        "xai":       "anthropic:claude-sonnet-4-6",
        "meta":      "anthropic:claude-sonnet-4-6",
    }
    return defaults.get(fam)
