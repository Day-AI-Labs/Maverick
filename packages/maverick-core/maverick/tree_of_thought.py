"""Tree-of-thought planner primitive.

A topology helper for the orchestrator: fork N candidate plans for a
goal, score each via a small critic prompt, return the winning plan
(plus the critic's reasoning). The orchestrator then dispatches the
winner like any other plan.

This is the *primitive* — wiring it into the agent loop is the
orchestrator's call, opt-in via [planning] mode = "tree_of_thought".

Each candidate gets a fresh LLM call but a tightly-bounded budget
(default 1500 tokens each); the critic gets another bounded call.
Total ToT overhead at N=3: ~6000 tokens vs single-plan ~1500. Worth
it for goals that would otherwise need expensive replans on failure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .budget import Budget
from .llm import LLM

log = logging.getLogger(__name__)


_PLANNER_SYSTEM = (
    "You are a planning agent. Given a goal, produce a concise plan "
    "(5-15 numbered steps). Cover assumptions, risks, and the order "
    "of operations. Output the plan only — no preamble, no commentary."
)

_CRITIC_SYSTEM = (
    "You score competing plans for the same goal. For each plan, "
    "judge: feasibility, risk, completeness, simplicity. Output STRICT "
    "JSON: {\"scores\": [<n>, <n>, ...], \"winner\": <0-indexed>, "
    "\"reason\": \"<short>\"}. Higher score = better."
)


@dataclass
class PlanCandidate:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ToTResult:
    winning_plan: str
    candidates: list[PlanCandidate]
    scores: list[float]
    winning_index: int
    critic_reason: str
    total_dollars: float


def _draft_candidate(
    llm: LLM, goal_text: str, *, budget: Budget,
    model: Optional[str], max_tokens: int = 1500,
) -> PlanCandidate:
    resp = llm.complete(
        system=_PLANNER_SYSTEM,
        messages=[{"role": "user", "content": goal_text}],
        budget=budget,
        max_tokens=max_tokens,
        model=model,
    )
    return PlanCandidate(text=(resp.text or "").strip())


def _score_candidates(
    llm: LLM, goal_text: str, candidates: list[PlanCandidate],
    *, budget: Budget, model: Optional[str],
) -> tuple[list[float], int, str]:
    import json
    numbered = "\n\n".join(
        f"### Plan {i}\n{c.text}" for i, c in enumerate(candidates)
    )
    prompt = (
        f"GOAL:\n{goal_text}\n\n"
        f"CANDIDATE PLANS:\n\n{numbered}\n\n"
        "Score and pick a winner. Reply with the JSON object only."
    )
    resp = llm.complete(
        system=_CRITIC_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        budget=budget,
        max_tokens=512,
        model=model,
    )
    raw = (resp.text or "").strip()
    # Strip ```json fences if the model added them.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        scores = [float(s) for s in (data.get("scores") or [])]
        winner = int(data.get("winner", 0))
        reason = str(data.get("reason", ""))
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        log.warning("ToT critic returned malformed JSON: %s", e)
        # Fallback: pick the longest plan (richer = better, naively).
        scores = [float(len(c.text)) for c in candidates]
        winner = max(range(len(candidates)), key=lambda i: scores[i])
        reason = "critic JSON parse failed; fell back to longest-plan heuristic"
    if not 0 <= winner < len(candidates):
        winner = 0
    while len(scores) < len(candidates):
        scores.append(0.0)
    return scores[:len(candidates)], winner, reason


def plan_tree_of_thought(
    llm: LLM,
    goal_text: str,
    *,
    n: int = 3,
    budget: Optional[Budget] = None,
    model: Optional[str] = None,
    per_candidate_max_tokens: int = 1500,
) -> ToTResult:
    """Generate N candidate plans, score them, return the winner.

    ``budget`` is shared across the N+1 calls; the function honors it.
    If budget exhausts mid-flight, we return the best plan generated
    so far (or a synthesized fallback if even the first call failed).
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if budget is None:
        budget = Budget(max_dollars=1.0)
    start_dollars = budget.dollars

    candidates: list[PlanCandidate] = []
    for i in range(n):
        try:
            cand = _draft_candidate(
                llm, goal_text,
                budget=budget, model=model,
                max_tokens=per_candidate_max_tokens,
            )
            if cand.text:
                candidates.append(cand)
        except Exception as e:
            log.warning("ToT candidate %d failed: %s", i, e)
            continue

    if not candidates:
        # No candidates at all — degenerate: return the goal verbatim so
        # the caller has SOMETHING to dispatch on.
        return ToTResult(
            winning_plan=f"(planner failed) {goal_text[:200]}",
            candidates=[], scores=[], winning_index=0,
            critic_reason="all candidates failed",
            total_dollars=budget.dollars - start_dollars,
        )

    if len(candidates) == 1:
        return ToTResult(
            winning_plan=candidates[0].text,
            candidates=candidates, scores=[1.0],
            winning_index=0, critic_reason="single candidate (no critic run)",
            total_dollars=budget.dollars - start_dollars,
        )

    scores, winner_idx, reason = _score_candidates(
        llm, goal_text, candidates, budget=budget, model=model,
    )
    return ToTResult(
        winning_plan=candidates[winner_idx].text,
        candidates=candidates,
        scores=scores,
        winning_index=winner_idx,
        critic_reason=reason,
        total_dollars=budget.dollars - start_dollars,
    )


__all__ = ["plan_tree_of_thought", "ToTResult", "PlanCandidate"]
