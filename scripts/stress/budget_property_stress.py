"""Budget accounting property test: random call sequences vs an independent oracle.

For thousands of randomized record_tokens sequences, an independent Python
accumulator predicts the exact token counts; the Budget must match to the token.
Also asserts the fail-closed contract: non-finite / negative / unparseable counts
must raise BudgetExceeded (never silently record a paid call as $0).

Determinism without Math.random: a per-iteration LCG seeded by the index.
"""
import math
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))
os.environ.setdefault("MAVERICK_ENCRYPT_AT_REST", "0")

from maverick.budget import Budget, BudgetExceeded  # noqa: E402

fails = []
MODELS = [None, "claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"]


def _lcg(seed):
    x = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    while True:
        x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        yield (x >> 33)


def stress_exact_accounting():
    print("\n== exact token accounting over random sequences ==")
    worst = 0
    for it in range(3000):
        rng = _lcg(it + 1)
        b = Budget(max_input_tokens=10**15, max_output_tokens=10**15,
                   max_dollars=10**12, max_wall_seconds=10**12, max_tool_calls=10**15)
        exp_in = exp_out = exp_cr = exp_cw = 0
        n = next(rng) % 50 + 1
        for _ in range(n):
            i = next(rng) % 5000
            o = next(rng) % 5000
            cr = next(rng) % 2000
            cw = next(rng) % 2000
            m = MODELS[next(rng) % len(MODELS)]
            b.record_tokens(i, o, model=m, cache_read_tok=cr, cache_write_tok=cw)
            exp_in += i
            exp_out += o
            exp_cr += cr
            exp_cw += cw
        if (b.input_tokens, b.output_tokens, b.cache_read_tokens, b.cache_write_tokens) \
                != (exp_in, exp_out, exp_cr, exp_cw):
            fails.append(f"it{it}: counters diverged "
                         f"in={b.input_tokens}/{exp_in} out={b.output_tokens}/{exp_out} "
                         f"cr={b.cache_read_tokens}/{exp_cr} cw={b.cache_write_tokens}/{exp_cw}")
            break
        if b.dollars < 0 or not math.isfinite(b.dollars):
            fails.append(f"it{it}: dollars went non-finite/negative: {b.dollars}")
            break
        worst = max(worst, n)
    print(f"  3000 sequences (up to {worst} calls each) -> "
          f"{'OK (exact)' if not fails else fails[-1]}")


def stress_fail_closed():
    # Per the documented Wave-12 contract: non-finite / negative / unparseable
    # counts must FAIL CLOSED (BudgetExceeded), never silently record a paid
    # call as $0. None is the ONE deliberate exception -- it coerces to 0
    # (Anthropic returns None usage on streaming refusals), so it is NOT a poison.
    print("\n== fail-closed on poisoned usage counts (None excluded by design) ==")
    poisons = [
        (-1, 5), (5, -3), (float("nan"), 5), (5, float("inf")),
        (float("-inf"), 0), ("oops", 5),
    ]
    leaked = []
    for in_tok, out_tok in poisons:
        b = Budget(max_input_tokens=10**12, max_output_tokens=10**12,
                   max_dollars=10**9, max_wall_seconds=10**12, max_tool_calls=10**12)
        try:
            b.record_tokens(in_tok, out_tok, model="claude-sonnet-4-6")
            # If it didn't raise, it must NOT have silently recorded a paid call as 0.
            leaked.append((in_tok, out_tok, b.input_tokens, b.output_tokens, b.dollars))
        except BudgetExceeded:
            pass  # correct: fail closed
        except (TypeError, ValueError):
            pass  # acceptable hard-fail (still not a silent $0 record)
    print(f"  {len(poisons)} poisons -> silent-accept leaks: {leaked or 'none'} "
          f"{'OK' if not leaked else 'LEAK'}")
    if leaked:
        fails.append(f"poisoned counts silently accepted: {leaked}")

    # Intended: None coerces to 0 (does not raise, records the other count).
    b = Budget(max_input_tokens=10**12, max_output_tokens=10**12,
               max_dollars=10**9, max_wall_seconds=10**12, max_tool_calls=10**12)
    b.record_tokens(5, None, model="claude-sonnet-4-6")
    ok = b.input_tokens == 5 and b.output_tokens == 0
    print(f"  None coerces to 0 (intended): in={b.input_tokens} out={b.output_tokens} "
          f"{'OK' if ok else 'UNEXPECTED'}")
    if not ok:
        fails.append("None-coercion contract broke")


if __name__ == "__main__":
    stress_exact_accounting()
    stress_fail_closed()
    print("\n=== SUMMARY ===")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        raise SystemExit(1)
    print("  budget accounting invariants held")
