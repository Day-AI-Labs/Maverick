# Self-learning harness — proof it works, consistently (2026-06-27)

> Goal: prove the self-learning (self-harness) loop
> (`maverick.self_harness` + the `maverick.self_improvement` gate) works and
> works **consistently** — same inputs, same result, no flakiness, invariants
> hold at scale.

## TL;DR

| Axis | Result |
|------|--------|
| Harness test suite (`self_harness` / `self_learning` / `self_improvement`) | **360 passed, 0 failed** |
| Suite re-run ×5 back-to-back | **360 passed every time** — identical, no flakiness |
| High-round soak (knobs cranked far past defaults) | **187 passed**, ~**2.1M** randomized scenarios, **0 invariant violations** |
| Concurrency battery ×25 repeats | **25/25 clean** — no lost promotions, no store corruption |
| Determinism (real loop) | same inputs → **byte-identical** learned store across 6 independent runs |
| Standalone proof scoreboard (`proof/self_harness_proof.py`) | **7/7 guarantees PROVEN**, reproducible |

Only skips in the whole run were two unrelated optional-dependency modules
(`z3`, `duckdb`) — no self-harness test skipped.

## What the loop is

A governed, model-specific loop that learns an **operating-guidance addendum**
from a model's own failure traces: `MINE` recurring failure signatures →
`PROPOSE` a minimal guidance line → `VALIDATE` on held-in *and* held-out splits
(reject overfit / pure trades) → `GATE` through `self_improvement.consider()`
(evidence floor, calibration-freeze interlock, reversibility, signed audit). The
accepted line is recalled into the system prompt at build time; it is never a
kernel-template mutation, and OFF by default.

## How consistency was proven

### 1. Baseline + repeated full-suite runs

```
python3 -m pytest packages/maverick-core/tests/ -q \
  -k "self_harness or self_learning or self_improvement"
```

Ran 5× consecutively → `360 passed, 2 skipped` each time (the 2 skips are
`z3`/`duckdb`, not harness tests). Stable pass count = no order-dependence, no
flakiness.

### 2. High-round soak (scale proof)

The seeded fuzz/soak batteries were cranked far above their CI defaults:

```
MAVERICK_SELF_HARNESS_FUZZ_ROUNDS=25000 \
MAVERICK_SELF_HARNESS_ADV_ROUNDS=50000 \
MAVERICK_SELF_HARNESS_CHAOS_ROUNDS=20000 \
MAVERICK_SELF_HARNESS_EFFICACY_TRIALS=1000000 \
python3 -m pytest -q \
  packages/maverick-core/tests/test_self_harness_battery.py \
  packages/maverick-core/tests/test_self_harness_adversarial.py \
  packages/maverick-core/tests/test_self_harness_metamorphic.py \
  packages/maverick-core/tests/test_self_harness_fault_injection.py \
  packages/maverick-core/tests/test_self_harness_efficacy_soak.py \
  packages/maverick-core/tests/test_self_harness_efficacy_adversarial_soak.py
```

Result: **187 passed in 5m19s**. Scenario counts exercised this run:

| Battery | Rounds/trials |
|---------|---------------|
| stateful model-based oracle (exact state) | 25,000 |
| invariant fuzz | 25,000 |
| metamorphic | 25,000 |
| fault-injection / chaos | 20,000 |
| adversarial input-fuzz | 50,000 |
| efficacy soak | 1,000,000 |
| adversarial efficacy soak | 1,000,000 |

≈ **2.1 million** randomized scenarios, zero invariant violations. Because the
RNG seeds are fixed (`random.Random(n)`), any failure at any round reproduces
exactly — this is a reproducible campaign, not a flake hunt.

### 3. Concurrency hammer

The store does a load-modify-save under an in-process lock + cross-process
flock — the only genuine thread-race surface. The concurrency battery (plus the
battery's `test_concurrent_passes_keep_store_valid`) was run **25 times**:
**25/25 clean** — every concurrent promotion survived, the store stayed valid
JSON within the line/char caps every time.

### 4. Determinism + standalone scoreboard

`proof/self_harness_proof.py` drives the **real** loop and gate and asserts
seven guarantees, exiting 0 iff all hold:

```
python3 proof/self_harness_proof.py
```

```
  [PASS]  determinism (consistent)    6/6 runs identical (sha256 194ee706fa13...)
  [PASS]  off by default              recall == '' and no store write when off
  [PASS]  governed gate enforced      open gate promotes; frozen verifier writes nothing
  [PASS]  no trace poisoning          secret/scoped/control-char excluded from the recalled prompt
  [PASS]  bounded addendum            <= 8 lines / 1500 chars under overflow
  [PASS]  concurrency safe            8 concurrent promotions, 0 lost, store valid
  [PASS]  reversible + auditable      rollback handle restores exactly; forget() clears guidance
  7 guarantees PROVEN, 0 failed
```

The headline guarantee, **determinism**, runs the loop six times on identical
inputs into fresh stores and confirms a byte-identical result (matching
SHA-256) — "works consistently" made checkable.

## Reproducing

1. Install: `bash .devcontainer/post-create.sh` (if distro `cryptography`
   blocks the upgrade, `pip install --ignore-installed 'cryptography>=44.0.1'`
   first, then re-run).
2. Suite: the pytest command in §1.
3. Soak: the command in §2.
4. Scoreboard: `python3 proof/self_harness_proof.py`.
