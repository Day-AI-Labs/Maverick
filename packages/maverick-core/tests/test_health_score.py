"""Run health score (ROADMAP 2028 H2)."""
from __future__ import annotations

from maverick.health_score import compute_health, render


def test_clean_success_scores_high():
    h = compute_health(success=True)
    assert h.score == 100
    assert h.grade == "A"


def test_failure_starts_low():
    h = compute_health(success=False)
    assert h.score == 40
    assert h.grade == "F"


def test_tool_errors_and_retries_penalise():
    h = compute_health(success=True, tool_errors=2, tool_retries=3)
    # 100 - (2*8 + 3*3) = 100 - 25 = 75
    assert h.score == 75
    assert h.grade == "C"


def test_tool_penalty_is_capped():
    h = compute_health(success=True, tool_errors=100)
    assert h.score == 50  # 100 - 50 (cap)


def test_efficiency_penalty_on_overshoot():
    # used 2x expected -> overshoot 1.0 -> 15-point penalty
    h = compute_health(success=True, in_tok=1000, out_tok=1000,
                       expected_tokens=1000)
    assert h.score == 85


def test_under_budget_not_penalised():
    h = compute_health(success=True, in_tok=100, out_tok=100,
                       expected_tokens=1000)
    assert h.score == 100


def test_score_never_negative():
    h = compute_health(success=False, tool_errors=100, in_tok=10_000,
                       out_tok=0, expected_tokens=10)
    assert h.score == 0
    assert render(h) == "Run health: 0/100 (F)"
