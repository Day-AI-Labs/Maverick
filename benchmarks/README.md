# Maverick benchmarks

The wedge claim is **long-horizon work + true multi-agent coordination**.
These benchmarks make that measurable.

## Why benchmarks exist

Without numbers, "better at long-horizon" is marketing. Each benchmark
in this directory:

- Has a verifiable success criterion (file produced, tests pass, etc.)
- Records wall-clock, cost (`$`), tokens, tool calls, and depth.
- Is reproducible from a single `maverick start` command.
- Has a baseline number from a single-shot LLM call for comparison.

Results belong in `RESULTS.md` next to each benchmark, with the run
metadata (date, model assignments, total cost) checked in.

## How to run a benchmark

```bash
# Pre-req: maverick init has been run with at least an Anthropic key.
maverick start "$(cat benchmarks/longhorizon/research-report.md)" \
  --max-dollars 5 --max-wall-seconds 1800 --workdir bench-workspace
```

When done, copy the output (and the budget summary line) into the
corresponding `RESULTS.md`.

## Suite

| Benchmark | Class | Expected wall | Expected cost |
|---|---|---|---|
| `longhorizon/research-report.md` | Research synthesis | 10–20 min | $0.50–$2 |
| `longhorizon/code-refactor.md` | Multi-file refactor | 15–30 min | $1–$3 |
| `longhorizon/multi-step-planning.md` | Planning + revision loop | 20–40 min | $1–$4 |

All three are designed to **fail** for single-shot prompting (too
broad, too many steps) and **succeed** for a recursive swarm with
verify + skill distill enabled.

## Does the learning actually help? (the moat)

The differentiator vs. stateless assistants is that Maverick *retains and
recalls* what it learns. These benchmarks make that claim falsifiable
instead of marketing:

| Benchmark | Question | Cost |
|---|---|---|
| `recall_precision.py` | Does relevance-gating cut injected noise without losing the right skill? | **free** (deterministic, lexical path) |
| `moat_rigorous.py` | Holding the task fixed, is a *warm* agent (relevant prior in store) never worse — and ideally cheaper — than a *cold* one? | ~$0.5–0.7/run × 3 runs/observation |
| `moat.py` | Original cold-vs-warm A/B (kept for history; superseded by `moat_rigorous.py`'s same-target protocol) | as above |

`recall_precision.py` runs in CI (no key): it shows the relevance gate drops
the lexical false-positive rate from **88% → 12%** with Recall@1 held at 100%
— precision is what matters, because injecting weakly-relevant memory *regresses*
the agent (hard negatives flip answers; large/noisy memory degrades).

`moat_rigorous.py` is the paid, end-to-end proof. Its headline is the
**defensible** one: *warm is never worse than cold* (the property the gate
buys), reported as a not-worse rate + a **median** (outlier-robust) cost delta,
with success parity. Pure aggregation is unit-tested offline
(`test_moat_rigorous.py`); results land in `MOAT_RIGOROUS_RESULTS.md`.

## Does the governance contain unsafe autonomy? (the control plane)

The other differentiator vs. an ungoverned runtime is that Maverick **contains**
what an autonomous agent is allowed to *do*. `eval_governance.py` makes that
falsifiable instead of marketing -- and, like `eval_smoke.py`, it runs in CI with
**no key**: deterministic, scripted calls into the *real* governance machinery.

| Scenario | Asks | Real control exercised |
|---|---|---|
| `approval-gate` | Is a high-risk actuation ("Pay") gated to a human, while a read isn't? | `safety/action_gate` |
| `egress-lock` | Does enterprise mode refuse a cloud LLM provider and admit a self-hosted one? | `enterprise` |
| `capability-ceiling` | Does an attenuating capability deny an out-of-grant tool but permit a granted one? | `capability` |
| `agent-trust` | Is an inbound-only external agent refused an outbound dial? | `agent_trust` |
| `signed-evidence` | Is a governed action recorded on a chain that verifies clean -- and a one-byte tamper detected? | `audit` (Ed25519 chain) |

It reports a **prevention rate** (unsafe vectors contained) *and* a **utility
rate** (legitimate paths preserved), so it can't be gamed by a control that
blocks everything. This is the CI-runnable half of
[`../docs/strategy/benchmark-plan.md`](../docs/strategy/benchmark-plan.md); the
task-completion / false-positive frontier needs the paid live arm described
there. Run it standalone: `python benchmarks/eval_governance.py`.

## Comparing across providers

Re-run the same benchmark with different `[models]` config blocks:

```toml
# all-anthropic
benchmarks/configs/all-anthropic.toml

# orchestrator on Anthropic, workers on Ollama (local)
benchmarks/configs/mixed-local-cloud.toml
```

The `RESULTS.md` for each benchmark records all configurations tried
and their numbers side by side.

## What we are NOT measuring (yet)

- Raw LLM accuracy (SWE-bench / MMLU / etc.) -- those measure the
  model, not the agent system
- Raw red-team / prompt-injection content scanning -- that's Agent
  Shield's territory and has its own suite. (The *action-governance*
  layer -- block/gate/record unsafe actions -- **is** now measured;
  see "Does the governance contain unsafe autonomy?" above.)

Distillation quality (whether auto-generated SKILL.md files actually help
future runs) **is** now measured — see "Does the learning actually help?"
above (`recall_precision.py` + `moat_rigorous.py`).
