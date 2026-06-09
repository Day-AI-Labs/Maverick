"""bias_eval: selection rates, disparate-impact ratio, four-fifths rule."""
from __future__ import annotations

from maverick.tools.bias_eval import bias_eval


def _evaluate(outcomes, **kw):
    return bias_eval().fn({"op": "evaluate", "outcomes": outcomes, **kw})


def test_equal_rates_pass():
    out = _evaluate([
        {"group": "A", "favorable": True},
        {"group": "A", "favorable": False},
        {"group": "B", "favorable": True},
        {"group": "B", "favorable": False},
    ])
    assert "disparate-impact ratio (min/max): 1.0000" in out
    assert out.rstrip().endswith("PASS")


def test_adverse_impact_fails_four_fifths():
    # A: 1/1 = 1.0 ; B: 1/2 = 0.5 -> ratio 0.5 < 0.8.
    out = _evaluate([
        {"group": "A", "favorable": True},
        {"group": "B", "favorable": True},
        {"group": "B", "favorable": False},
    ])
    assert "disparate-impact ratio (min/max): 0.5000" in out
    assert "FAIL" in out


def test_selection_rates_reported_per_group():
    out = _evaluate([
        {"group": "A", "favorable": True},
        {"group": "A", "favorable": True},
        {"group": "B", "favorable": False},
        {"group": "B", "favorable": True},
    ])
    assert "- A: 1.0000 (2/2)" in out
    assert "- B: 0.5000 (1/2)" in out


def test_exactly_at_threshold_passes():
    # A: 4/5 = 0.8 ; B: 5/5 = 1.0 -> ratio 0.8 == threshold -> PASS.
    outcomes = (
        [{"group": "A", "favorable": True}] * 4 + [{"group": "A", "favorable": False}]
        + [{"group": "B", "favorable": True}] * 5
    )
    out = _evaluate(outcomes)
    assert "disparate-impact ratio (min/max): 0.8000" in out
    assert out.rstrip().endswith("PASS")


def test_custom_threshold():
    # ratio 0.5; with threshold 0.4 it should PASS.
    outcomes = [
        {"group": "A", "favorable": True},
        {"group": "B", "favorable": True},
        {"group": "B", "favorable": False},
    ]
    assert "FAIL" in _evaluate(outcomes)
    assert _evaluate(outcomes, threshold=0.4).rstrip().endswith("PASS")


def test_no_one_selected_is_consistent_pass():
    out = _evaluate([
        {"group": "A", "favorable": False},
        {"group": "B", "favorable": False},
    ])
    assert "disparate-impact ratio (min/max): 1.0000" in out
    assert out.rstrip().endswith("PASS")


def test_errors():
    t = bias_eval()
    assert t.fn({"op": "evaluate", "outcomes": []}).startswith("ERROR")  # empty
    assert t.fn({"op": "evaluate"}).startswith("ERROR")  # missing
    assert t.fn({"op": "nope", "outcomes": [{"group": "A", "favorable": True}]}).startswith("ERROR")
    assert t.fn({"op": "evaluate",
                 "outcomes": [{"group": "A", "favorable": True}],
                 "threshold": 2}).startswith("ERROR")  # out of range
