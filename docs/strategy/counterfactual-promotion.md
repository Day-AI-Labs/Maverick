# Counterfactual promotion — the learning pillar of the Operating Twin

> Status: **Phase A shipped** (offline, confounder-adjusted effect estimation
> wired into the promotion ladder). Phase B (model-based counterfactual
> rollouts) is designed below and not yet built.

## The problem

The self-improvement controller (`maverick.self_improvement`) promotes a change
when its evidence beats baseline:

```python
improvement = cand.candidate_score - cand.baseline_score   # the evidence gate
```

Those scores were **correlational aggregates** — a synthesized tool's raw
success rate (`ToolOutcomeTracker`), a before/after eval mean. In a system that
rewrites **itself**, correlational credit is a *superstition pump*: a change that
merely co-occurs with success — because it was tried on easier sub-goals, or ran
alongside the decision that actually mattered — gets promoted, reinforced, and
compounded. The audit log faithfully signs each ritual as "beat baseline."

The fix is not a new gate. It's changing **what the evidence number means**: a
*causal* effect, not a correlation.

## Phase A — confounder-adjusted effect estimation (shipped)

`maverick.promotion_effect` estimates the effect of a candidate change on task
outcome from the logged trajectory population, adjusting for confounders by
**stratification** (subclassification): within each cell of comparable context
(domain, depth bucket, …) compare treated vs untreated outcomes, then average the
per-cell effects weighted by cell size. Cells with no overlap (only treated, or
only untreated) carry no causal information and are dropped; the comparable
fraction (`overlap`) is reported, never hidden.

Output (`EffectEstimate`): the effect, a 95% CI, `n_used`/`n_total`, `overlap`,
the **naive** (confounded) difference for contrast, a **placebo** effect, and a
`trustworthy` flag.

**Wiring into the ladder (unchanged safety spine):**

- `Candidate.effect_ci_low` — when set, the evidence gate requires the **lower
  confidence bound** of the causal effect to clear the margin (promote only when
  confident the change *caused* the win). Every other gate (capability
  non-escalation, human approval, reversibility, calibration freeze) is
  untouched.
- `si_producers.propose_with_effect(...)` — builds the candidate from an
  `EffectEstimate`, stamps provenance `{effect, ci, naive, adjusted_for, n,
  overlap, placebo}` into the signed `LEARNING_UPDATE`, and **fails closed** on
  an untrustworthy estimate.
- `trajectory_store.TrajectoryStep` gained `parent_step` (decision-DAG edge) and
  `outcome` (terminal task label) so episodes reduce to causal units via
  `promotion_effect.units_from_trajectories`.

**Fail-safe by calibration.** `trustworthy` is False when overlap is too low, or
when a **placebo** — treatment labels permuted *within* strata, which must yield
~0 — leaks a non-zero effect (the estimate is then an artifact, not an effect).
This mirrors the existing "freeze learning when the verifier is mis-calibrated"
interlock, applied to the credit estimator.

**Posture.** OFF by default (`[self_improvement] causal_promotion` /
`MAVERICK_CAUSAL_PROMOTION`). The estimator is a pure, dependency-free function;
nothing changes in a default deployment.

**Distinct from CSCA** (`maverick.credit`): that is *online, per-swarm*
leave-one-out Shapley credit for sub-agents; this is *offline, corpus-level*
effect estimation for **promotion** decisions. They compose — CSCA can weight
which sub-trajectories feed this estimator.

## Why it's a moat

- **Sample efficiency** — learning from a debiased causal effect needs far fewer
  episodes than averaging noisy outcomes; real wins promote sooner, superstitions
  never do.
- **Explainability as a deliverable** — "+0.18 task success, CI [0.07, 0.29],
  adjusted for {domain, depth, prior-tool-success}, n=4,200, placebo 0.004",
  signed into the audit chain. No RLHF pipeline emits that.
- **Unbuyable & compounding** — the propensity/outcome structure (Phase A) and
  the transition model (Phase B) are fit on *that customer's* trajectories. Six
  months of running is a credit model a fresh competitor can't reconstruct.
- **It is the safety story** — a self-modifying system that promotes only
  causally-validated changes is the thing you can actually put in a bank.

## Phase B — model-based counterfactual rollouts (designed, not built)

When confounding is too severe for stratified adjustment (long horizons,
high-dimensional action spaces), fit a transition model `q(s'|s,a)` over the
Operating Record and **re-simulate** the trajectory from a decision node with the
decision perturbed (`do(T=¬x)`), propagating to a terminal outcome via the
verifier head; average over rollouts → a counterfactual outcome. It feeds the
**same** `EffectEstimate(effect, ci, trustworthy)` interface, so the promotion
ladder never changes — only the estimator behind it gets stronger. This is the
learning half of the **Operating Twin**: the per-customer world-model that also
powers pre-execution rehearsal (the governance half). Gated by the same
calibration freeze — an uncertain twin never greenlights a promotion.

## Build status

| Piece | State |
|---|---|
| `promotion_effect` estimator + placebo refutation | ✅ |
| `Candidate.effect_ci_low` + evidence-gate branch | ✅ |
| `propose_with_effect` producer (fail-closed) | ✅ |
| trajectory DAG fields (`parent_step`, `outcome`) | ✅ |
| config knob + wizard step | ✅ |
| richer nuisance models (logistic propensity/outcome, causal forest) | seam |
| model-based counterfactual rollouts (Phase B) | designed |
