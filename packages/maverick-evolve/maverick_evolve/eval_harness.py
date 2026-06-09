"""Stage 0: the trusted fitness function.

You cannot safely evolve an agent without a metric you believe. This scores an
agent (any ``async (prompt) -> str``) against a held-out set of cases. A case
either carries its own ``check`` predicate (ground truth — the strongest signal)
or a ``reference`` answer scored by an injected ``scorer`` (default: substring
containment). Keep ground-truth cases where you can; that is what makes the
fitness signal ungameable enough to evolve against.

Pure + dependency-injected (you supply the agent and, optionally, the scorer),
so it runs in tests without a live model. Pair with ``maverick.calibration`` to
freeze evolution when the judge drifts.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class EvalCase:
    prompt: str
    check: Callable[[str], bool] | None = None  # ground-truth predicate (preferred)
    reference: str | None = None                # else scored against this
    weight: float = 1.0


@dataclass
class EvalReport:
    n: int
    passed: float          # weighted sum of per-case scores
    total_weight: float

    @property
    def score(self) -> float:
        """Weighted pass rate in [0,1]."""
        return self.passed / self.total_weight if self.total_weight > 0 else 0.0


def _contains_scorer(output: str, reference: str) -> float:
    """Default reference scorer: 1.0 if the reference appears in the output."""
    if not reference:
        return 0.0
    return 1.0 if reference.strip().lower() in (output or "").lower() else 0.0


async def evaluate(
    agent: Callable[[str], Awaitable[str]],
    cases: list[EvalCase],
    *,
    scorer: Callable[[str, str], float] | None = None,
) -> EvalReport:
    """Run ``agent`` over ``cases`` and return a weighted fitness report.

    A case's ``check`` (ground truth) wins when present; otherwise the output is
    scored against ``reference`` via ``scorer`` (default substring containment).
    An agent that raises on a case scores 0 for that case (robustness counts).
    """
    scorer = scorer or _contains_scorer
    passed = 0.0
    total_weight = 0.0
    for case in cases:
        total_weight += case.weight
        try:
            out = await agent(case.prompt)
        except Exception:
            out = ""
        if case.check is not None:
            score = 1.0 if case.check(out) else 0.0
        elif case.reference is not None:
            score = max(0.0, min(1.0, float(scorer(out, case.reference))))
        else:
            score = 0.0
        passed += case.weight * score
    return EvalReport(n=len(cases), passed=passed, total_weight=total_weight)


__all__ = ["EvalCase", "EvalReport", "evaluate"]
