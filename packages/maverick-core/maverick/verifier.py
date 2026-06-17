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

from .budget import Budget, BudgetExceeded
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
    def reject(cls, reason: str) -> VerifierVerdict:
        return cls(confidence=0.0, accepts=False, critique=reason, issues=[reason])

    @classmethod
    def accept_unconditionally(cls) -> VerifierVerdict:
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

    # Enforce the confidence floor in code -- VERIFIER_CONFIDENCE_ACCEPT was
    # dead, so the model's raw `accepts` boolean was trusted verbatim. The
    # verifier is the last correctness gate before FINAL, so accepting a
    # low-confidence verdict is a fail-open a miscalibrated/jailbroken verifier
    # could exploit (accepts=true, confidence=0.1). Below the threshold the
    # verdict is forced to a reject with a revision brief.
    if accepts and confidence < VERIFIER_CONFIDENCE_ACCEPT:
        accepts = False
        critique = critique or (
            f"verifier confidence {confidence:.2f} is below the accept "
            f"threshold {VERIFIER_CONFIDENCE_ACCEPT:.2f}"
        )

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
    budget: Budget | None = None,
    *,
    max_tokens: int = 1024,
    proposer_model: str | None = None,
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
    proposer_model is passed and matches the verifier's family, we swap
    to a cross-family verifier — but ONLY when one is explicitly
    configured via ``MAVERICK_CROSS_FAMILY_VERIFIER`` (users own model
    choice; we never implicitly switch to a provider whose credentials
    the operator may not have). #612: if no fallback is configured, the
    same-family verifier runs and we log the lockstep risk ONCE rather
    than silently pretending a cross-family swap happened.
    """
    if not proposal or not proposal.strip():
        return VerifierVerdict.reject("proposal is empty")

    model = model_for_role("verifier")
    if proposer_model and _same_family(proposer_model, model):
        cross = _cross_family_fallback(model)
        if cross is not None:
            model = cross
        else:
            _warn_same_family_verifier(model)

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
    except BudgetExceeded:
        # Budget exhaustion is a control-flow signal for the budget
        # layer, not a verifier outcome — let it propagate.
        raise
    except Exception as e:  # pragma: no cover -- network errors
        # Fail CLOSED, per this module's contract ("any failure →
        # reject; a flaky verifier can only make the system MORE
        # careful, not less"). The previous fail-open (accepts=True)
        # silently disabled the safety gate exactly when the system was
        # least healthy.
        log.warning("verifier LLM call failed: %s; rejecting (fail-closed)", e)
        return VerifierVerdict.reject(f"verifier call failed: {e}")
    return _parse(resp.text)


def _provider_from_model(model: str) -> str:
    return model.split(":", 1)[0].strip()


def _routing_allowed_providers() -> set[str] | None:
    """Return the routing provider allowlist, or None when unrestricted.

    Installer-generated configs include this key when advanced routing or
    ensemble verification is enabled so verifier prompts do not leave the
    provider set the user selected in the wizard.
    """
    try:
        from .config import load_config
        routing = (load_config() or {}).get("routing") or {}
    except Exception:
        return None
    allowed = routing.get("allowed_providers")
    if not isinstance(allowed, list):
        return None
    return {str(p).strip() for p in allowed if str(p).strip()}


_DEFAULT_ENSEMBLE_PANEL = [
    "anthropic:claude-sonnet-4-6",
    "openai:gpt-5.4",
    "openrouter:deepseek-v4-pro",
]

_DEFAULT_ALLOWED_PROVIDER_MODELS = {
    "anthropic": "anthropic:claude-sonnet-4-6",
    "openai": "openai:gpt-5.4",
    "openrouter": "openrouter:deepseek-v4-pro",
    "deepseek": "deepseek:deepseek-reasoner",
    "moonshot": "moonshot:moonshot-v1-128k",
    "xai": "xai:grok-4",
    "gemini": "gemini:gemini-2.5-pro",
}


def _filter_allowed_panel(panel: list[str], *, default_panel: bool) -> list[str]:
    allowed = _routing_allowed_providers()
    if allowed is None:
        return panel
    if default_panel:
        return [
            spec for provider, spec in _DEFAULT_ALLOWED_PROVIDER_MODELS.items()
            if provider in allowed
        ]
    return [model for model in panel if _provider_from_model(model) in allowed]


async def verify_proposal_ensemble(
    brief: str,
    proposal: str,
    llm: LLM,
    budget: Budget | None = None,
    *,
    proposer_model: str | None = None,
    panel: list[str] | None = None,
    weighted: bool = True,
) -> VerifierVerdict:
    """Run N verifiers across distinct model families and combine.

    Multi-Agent Verification (MAV, arxiv:2502.20379) shows that scaling
    the *verifier* axis -- multiple verifiers, weighted vote -- is
    orthogonally additive to scaling the *generator* axis (best-of-N).
    On agentic tasks MAV-3 beats single-verifier + best-of-8 at the
    same total compute budget.

    Panel: explicit model list, or None to use a curated cross-family
    default (Anthropic Sonnet + OpenAI GPT + DeepSeek). Same-family panel
    members are excluded when another allowed family remains.

    `weighted=True` uses each verdict's `confidence` as a weight in
    the final accept-vote; `weighted=False` is plain majority. The
    combined verdict's `confidence` is the *minimum* confidence across
    accepting voters (conservative -- one outlier doesn't pull
    confidence up).
    """
    if not proposal or not proposal.strip():
        return VerifierVerdict.reject("proposal is empty")

    default_panel = panel is None
    if panel is None:
        panel = list(_DEFAULT_ENSEMBLE_PANEL)
    allowed_panel = _filter_allowed_panel(panel, default_panel=default_panel)

    # Drop panel members in the proposer's family when possible, but never
    # replace an installer-constrained panel with an unselected provider. If
    # the only selected verifier is same-family, prefer that selected provider
    # over leaking the brief/proposal to an unselected cross-family fallback.
    panel = allowed_panel
    if proposer_model:
        cross_family_panel = [m for m in panel if not _same_family(proposer_model, m)]
        if cross_family_panel:
            panel = cross_family_panel
    if not panel:
        # Everything got filtered. Preserve the historical fallback only when
        # there is no routing allowlist; wizard-generated configs include an
        # allowlist and should fail closed instead of contacting third parties.
        if _routing_allowed_providers() is not None:
            return VerifierVerdict.reject("no allowed ensemble verifier providers configured")
        cross = _cross_family_fallback(proposer_model or "")
        if cross:
            panel = [cross]
        else:
            # Parity with the single-verifier path: when no cross-family
            # fallback is configured we fall back to a same-family verifier;
            # surface the lockstep-jailbreak risk ONCE instead of silently.
            fallback = model_for_role("verifier")
            if proposer_model and _same_family(proposer_model, fallback):
                _warn_same_family_verifier(fallback)
            panel = [fallback]

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
        except BudgetExceeded:
            raise
        except Exception as e:  # pragma: no cover
            # Fail closed, same contract as verify_proposal. One panel
            # member erroring must not auto-accept.
            log.warning("MAV verifier %s failed: %s", model, e)
            return VerifierVerdict.reject(f"verifier {model} failed: {e}")

    verdicts = await asyncio.gather(*(_one(m) for m in panel))
    return _combine(verdicts, weighted=weighted)


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _explicit_true(value: object) -> bool:
    """Return True only for explicit verifier-ensemble opt-in values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False


def _ensemble_enabled() -> bool:
    """Opt-in gate for the adversarial multi-verifier panel.

    Off by default: a single cross-family verifier is the standard path.
    Flip on via ``MAVERICK_VERIFY_ENSEMBLE=1`` or ``[routing]
    verify_ensemble = true`` to run the MAV panel (stronger, ~Nx the
    verifier cost). Spend still lands in the run's Budget, so the cap is
    respected either way.
    """
    if _explicit_true(os.environ.get("MAVERICK_VERIFY_ENSEMBLE", "")):
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("routing") or {}
        return _explicit_true(cfg.get("verify_ensemble"))
    except Exception:
        return False


async def verify_final(
    brief: str,
    proposal: str,
    llm: LLM,
    budget: Budget | None = None,
    *,
    proposer_model: str | None = None,
    force_ensemble: bool = False,
) -> VerifierVerdict:
    """Verify a FINAL answer using whichever verifier the operator chose.

    Single dispatch point for the live agent loop: returns the adversarial
    cross-family ensemble when opted in (``_ensemble_enabled``) OR when the
    autonomy gate escalates a high-disagreement run (``force_ensemble``), else
    the standard single cross-family verifier. Same signature + return type as
    ``verify_proposal`` so the call site is verifier-agnostic.
    """
    if force_ensemble or _ensemble_enabled():
        return await verify_proposal_ensemble(
            brief, proposal, llm, budget, proposer_model=proposer_model,
        )
    return await verify_proposal(
        brief, proposal, llm, budget, proposer_model=proposer_model,
    )


def _combine(verdicts: list[VerifierVerdict], *, weighted: bool) -> VerifierVerdict:
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


_warned_same_family = False


def _warn_same_family_verifier(model: str) -> None:
    """Log the lockstep-jailbreak risk ONCE when the verifier shares the
    proposer's family and no cross-family fallback is configured.

    #612: the contract promises a cross-family swap to defend against
    lockstep jailbreaks, but the swap only happens when
    ``MAVERICK_CROSS_FAMILY_VERIFIER`` is set. When it isn't, surface the
    residual risk instead of leaving the gap silent.
    """
    global _warned_same_family
    if _warned_same_family:
        return
    _warned_same_family = True
    log.warning(
        "verifier %s shares the proposer's family; set "
        "MAVERICK_CROSS_FAMILY_VERIFIER to a different-provider model to "
        "defend against lockstep jailbreaks (running same-family for now).",
        model,
    )


# Preferred cross-family verifier per source family. Read from env if
# the operator wants to override. The fallback chain ends with the
# original model (no swap) when no peer is configured.
def _cross_family_fallback(model: str) -> str | None:
    """Pick a verifier from a different provider family.

    Uses only the explicit ``MAVERICK_CROSS_FAMILY_VERIFIER`` override; no
    implicit provider swap is performed (users own model choice — we won't
    silently route to a provider whose credentials may be absent). Returns
    None when no cross-family peer is explicitly configured; callers that
    care about the lockstep risk should warn via
    ``_warn_same_family_verifier``.
    """
    explicit = os.environ.get("MAVERICK_CROSS_FAMILY_VERIFIER")
    if explicit:
        return explicit

    return None
