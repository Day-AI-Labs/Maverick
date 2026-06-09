# maverick-evolve

Governed self-evolution for Maverick — the safe rungs of the ladder.

This package builds toward open-ended self-improvement **without** (yet) letting
an agent rewrite its own kernel code. It provides the three foundations every
safe self-evolving system needs first:

- **`eval_harness`** (Stage 0) — a *trusted fitness function*. You cannot evolve
  without a metric you believe; this scores an agent config against a held-out
  set of cases. Pairs with `maverick.calibration` (freeze evolution when the
  judge drifts) and `maverick.credit` (attribute outcomes to components).
- **`archive`** (Stage 2) — a *diverse* archive of high-performing configs. Keeping
  diversity (not just the single best) is the published trick for escaping the
  "plateau"/local-optimum trap that naive self-improvement falls into.
- **`search`** (Stage 1) — **config-only** evolutionary search: propose a mutated
  config, score it on a held-out split, keep it only if it genuinely beats the
  incumbent. Mutations are bounded to configuration (prompts, role roster,
  workflow knobs) — they cannot escape the sandbox, so this rung is safe to run.

## Explicitly out of scope (for now)

Code self-modification (the true Darwin-Gödel step) is **not** in this package.
That rung needs an out-of-process sandbox runtime, hard capability bounds, and
human-gated promotion; it is research-cadence and is intentionally deferred. The
design rationale lives in `docs/research/`.

All of this is opt-in and depends on `maverick-agent`; nothing here runs unless
an operator wires an evolution loop.
