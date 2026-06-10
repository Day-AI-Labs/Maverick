"""Provider migration calculator: repricing arithmetic, unknown-target errors,
unpriceable-row honesty, matrix sorting, the world-model adapter, and the
render caveat. Fully offline against a pinned price table."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick import llm as llm_mod
from maverick import migration_calculator as mc

PRICES = {
    "alpha": (1.0, 2.0),
    "beta":  (10.0, 20.0),
    "gamma": (0.1, 0.2),
}


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(llm_mod, "MODEL_PRICES", dict(PRICES))


ROWS = [
    # priced from its model: 1.0 + 1.0 = $2.0 current
    {"model": "alpha", "in_tokens": 1_000_000, "out_tokens": 500_000},
    # recorded cost wins over any derivation
    {"in_tokens": 2_000_000, "out_tokens": 0, "cost_dollars": 7.5},
]


def test_reprice_arithmetic(pinned):
    est = mc.reprice(ROWS, "beta")
    assert est.target_model == "beta"
    assert est.current_dollars == pytest.approx(2.0 + 7.5)
    # target: 3M in @ $10 + 0.5M out @ $20
    assert est.target_dollars == pytest.approx(30.0 + 10.0)
    assert est.delta_dollars == pytest.approx(40.0 - 9.5)
    assert est.delta_pct == pytest.approx((40.0 - 9.5) / 9.5 * 100.0)
    assert est.unpriceable_rows == 0


def test_provider_prefix_and_object_rows(pinned):
    rows = [SimpleNamespace(model="alpha", input_tokens=1_000_000, output_tokens=500_000)]
    est = mc.reprice(rows, "anthropic:beta")
    assert est.current_dollars == pytest.approx(2.0)
    assert est.target_dollars == pytest.approx(10.0 + 10.0)


def test_unknown_target_raises_listing_known_ids(pinned):
    with pytest.raises(ValueError) as exc:
        mc.reprice(ROWS, "no-such-model")
    msg = str(exc.value)
    assert "no-such-model" in msg
    for known in PRICES:
        assert known in msg


def test_unpriceable_rows_counted_not_crashed(pinned):
    rows = ROWS + [
        {"model": "ghost-model", "in_tokens": 9_000_000, "out_tokens": 9_000_000},
        {"in_tokens": 5_000_000, "out_tokens": 0},  # no cost, no model
    ]
    est = mc.reprice(rows, "beta")
    assert est.unpriceable_rows == 2
    # Excluded from BOTH sides: totals match the priceable-only run.
    baseline = mc.reprice(ROWS, "beta")
    assert est.current_dollars == pytest.approx(baseline.current_dollars)
    assert est.target_dollars == pytest.approx(baseline.target_dollars)


def test_calls_field_is_metadata_only(pinned):
    with_calls = mc.reprice(
        [{"model": "alpha", "in_tokens": 1_000_000, "out_tokens": 0, "calls": 99}], "beta",
    )
    without = mc.reprice(
        [{"model": "alpha", "in_tokens": 1_000_000, "out_tokens": 0}], "beta",
    )
    assert with_calls.target_dollars == pytest.approx(without.target_dollars)


def test_empty_rows_zero_estimate(pinned):
    est = mc.reprice([], "beta")
    assert est.current_dollars == 0.0
    assert est.target_dollars == 0.0
    assert est.delta_pct == 0.0  # no division by zero


def test_compare_matrix_sorted_cheapest_first(pinned):
    estimates = mc.compare_matrix(ROWS, ["beta", "alpha", "gamma"])
    assert [e.target_model for e in estimates] == ["gamma", "alpha", "beta"]
    assert estimates[0].target_dollars <= estimates[-1].target_dollars


def test_gather_from_world(pinned):
    episodes = [
        SimpleNamespace(input_tokens=1_000_000, output_tokens=500_000, cost_dollars=4.2),
        SimpleNamespace(input_tokens=0, output_tokens=0, cost_dollars=0.0),  # skipped
        SimpleNamespace(input_tokens=100, output_tokens=0, cost_dollars=0.0),  # unpriceable
    ]
    seen = {}

    class FakeWorld:
        def list_episodes(self, limit=50):
            seen["limit"] = limit
            return episodes

    rows = mc.gather_from_world(FakeWorld(), limit=7)
    assert seen["limit"] == 7
    assert len(rows) == 2  # the zero-usage episode is dropped
    assert rows[0] == {"in_tokens": 1_000_000, "out_tokens": 500_000, "cost_dollars": 4.2}
    est = mc.reprice(rows, "alpha")
    assert est.current_dollars == pytest.approx(4.2)
    assert est.target_dollars == pytest.approx(1.0 + 1.0)
    assert est.unpriceable_rows == 1  # tokens but no recorded cost: never guessed


def test_render_includes_caveat_and_rows(pinned):
    out = mc.render(mc.compare_matrix(ROWS, ["beta", "alpha"]))
    assert mc.CAVEAT in out
    assert "not a benchmark" in out
    assert "alpha" in out and "beta" in out
    # A single estimate renders too, caveat included.
    single = mc.render(mc.reprice(ROWS, "alpha"))
    assert mc.CAVEAT in single
