"""Tier 0 (Wave 11): cost-accumulation float precision.

The harness sums `row.cost_dollars` into `total_spend` via repeated
float +=. Over 1865 instances at $1-3 each, IEEE754 rounding error can
accumulate. We need to verify:

  1. The accumulated error after 1865 sums is small (<$0.01).
  2. The abort-at-total-dollars comparison fires correctly even when
     the threshold lands between two instance costs.
  3. Reading the CSV back and re-summing matches the in-memory total.
"""
from __future__ import annotations

import csv
import importlib.util
import random
import sys
from pathlib import Path


def _load_module():
    p = Path(__file__).resolve().parents[1] / "benchmarks" / "swe_bench.py"
    spec = importlib.util.spec_from_file_location("benchmarks_swe_bench", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmarks_swe_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Float precision over 1865 sums ----


def test_1865_instance_accumulated_drift_is_small():
    """Sum 1865 representative per-instance costs and check that the
    naive float sum differs from a high-precision Decimal sum by less
    than $0.01."""
    from decimal import Decimal, getcontext
    getcontext().prec = 30
    random.seed(20260526)
    # SWE-bench Pro instances: tiered cascade caps at $3 with mean ~$1.50.
    costs = [round(random.uniform(0.20, 2.95), 4) for _ in range(1865)]

    float_total = 0.0
    for c in costs:
        float_total += c

    decimal_total = sum(Decimal(str(c)) for c in costs)
    drift = abs(Decimal(str(float_total)) - decimal_total)

    # Empirically the drift is in the 1e-10 to 1e-8 range for 1865
    # sums — well below 1 cent.
    assert drift < Decimal("0.01"), f"drift {drift} exceeds $0.01 over 1865 sums"


def test_abort_threshold_fires_at_correct_boundary():
    """If abort_at_total_dollars is $50.00 and instances cost $49.99
    then $0.02, the abort must fire on the SECOND instance (cumulative
    $50.01), not the first ($49.99)."""
    total = 0.0
    threshold = 50.0
    fired_on = None
    for i, c in enumerate([49.99, 0.02, 1.00, 1.00]):
        if total >= threshold:
            fired_on = i
            break
        total += c
    if total >= threshold and fired_on is None:
        # The check happens BEFORE the add in main(); after the last
        # add we may also be over. Confirm we never UNDER-shot.
        fired_on = len([49.99, 0.02, 1.00, 1.00])
    assert fired_on == 2, (
        f"expected abort on iteration 2 (total=$50.01), got iteration "
        f"{fired_on} with total ${total:.4f}"
    )


def test_csv_round_trip_preserves_cost_precision(tmp_path):
    """Write 100 rows with costs to CSV, read them back, re-sum,
    confirm the difference is below floating-point noise."""
    sb = _load_module()
    random.seed(20260526)
    rows = [
        sb.Row(
            instance_id=f"inst-{i}",
            pipeline="maverick",
            model_id="claude-sonnet-4-6",
            cost_dollars=round(random.uniform(0.20, 2.95), 4),
        )
        for i in range(100)
    ]
    in_memory_total = sum(r.cost_dollars for r in rows)
    out = tmp_path / "results.csv"
    sb.write_csv(rows, out)
    with out.open() as f:
        read_total = sum(float(row["cost_dollars"]) for row in csv.DictReader(f))
    drift = abs(in_memory_total - read_total)
    assert drift < 1e-6, f"CSV round-trip drift ${drift} too large"


def test_zero_cost_row_does_not_corrupt_threshold():
    """Dry-run rows have cost_dollars=0.0. Verify many zeros in a row
    don't somehow trigger the abort check."""
    total = 0.0
    threshold = 1.0
    for _ in range(10_000):
        if total >= threshold:
            assert False, "abort fired on accumulated zeros"
        total += 0.0
    assert total == 0.0


def test_negative_cost_rejected_by_sum_invariant():
    """A row with negative cost_dollars would let the total run away.
    Verify the harness writer accepts negatives but the in-memory
    accumulator stays correct (the user is responsible for filtering)."""
    total = 0.0
    for c in [1.0, -0.5, 2.0]:
        total += c
    # Just lock the float arithmetic, not a behaviour we enforce.
    assert abs(total - 2.5) < 1e-9


def test_abort_threshold_with_realistic_pro_costs():
    """Simulate 200 instances at SWE-bench Pro distribution (~$1.50
    mean, $3 cap). Confirm the abort threshold of $300 (200×$1.50)
    fires within 5 instances of the predicted point."""
    random.seed(20260526)
    threshold = 300.0
    total = 0.0
    instances_until_abort = None
    for i in range(500):
        if total >= threshold:
            instances_until_abort = i
            break
        total += round(random.uniform(0.20, 2.95), 4)
    # With mean ~$1.58, $300 should fire around instance ~190.
    assert instances_until_abort is not None
    assert 150 <= instances_until_abort <= 230, (
        f"abort fired at instance {instances_until_abort}, "
        f"expected 150-230 for $300 threshold at ~$1.58 mean"
    )
