# Invention Disclosure 2 — Calibration-Gated Self-Modifying Agent with Snapshot-Replay Learning-Regression Detection

> Not legal advice. Engineering disclosure prepared for patent counsel, 2026-06-19.
> Repo: `Day-AI-Labs/Maverick`. Public disclosure date (conservative): 2026-06-18.

## Administrative

- **Working title:** Calibration-gated self-improvement loop for autonomous
  agents with deterministic, replay-based learning-regression detection and
  atomic rollback.
- **Inventors:** _[TO BE COMPLETED]_
- **Assignee:** _[Day AI Labs, Inc. — confirm]_
- **Public disclosure:** source public since ~2026-06-18.

## 1. Field

Self-improving / self-modifying AI agents; safe online learning; automated
detection of learning regressions; evaluator-reliability gating.

## 2. The problem

An agent that consolidates its own experience into new learned skills/insights and
that **evolves its own configuration** to improve faces three safety failures
that compound over time:

1. **Reward hacking via evaluator drift.** Self-improvement is driven by a
   verifier/evaluator that scores candidate behaviors. If that evaluator becomes
   miscalibrated (assigns high confidence to wrong answers), the loop optimizes
   toward *looking* good — and naive systems either keep learning blindly or shut
   the loop off permanently.
2. **Silent regressions.** A learning update that improves average performance may
   *lose* coverage on specific past situations. Detecting this normally requires
   re-running the agent on many past tasks — expensive, non-reproducible (LLM
   nondeterminism), and slow.
3. **Destructive rollback.** When learning must be reverted, a mid-operation
   failure (disk full, crash) during a naive in-place restore can destroy the
   very known-good state it was trying to restore.

## 3. Summary of the invention

A self-improvement loop with three cooperating safety mechanisms:

### 3.1 Calibration-discrimination interlock that *freezes and resumes* learning
The system continuously samples `(evaluator_confidence, ground_truth)` pairs and
computes a **discrimination** statistic = mean confidence on correct outcomes
minus mean confidence on incorrect outcomes. When discrimination falls below a
threshold over a minimum sample count, a `calibration_frozen()` / `learning_frozen()`
signal goes true. While frozen, the **round-based** self-improvement loop **skips**
each round (recording it as `skipped` with reason) **without discarding the
accumulated search archive**, and rehearsal/donation halt. When calibration
recovers, the loop **resumes from the persisted archive** — a pause, not a reset
and not a permanent shutdown.

Evidence: `packages/maverick-core/maverick/calibration.py` (discrimination
computation + freeze decision); `packages/maverick-evolve/maverick_evolve/loop.py:29-86`
(per-round skip-on-freeze with archive persistence);
`packages/maverick-core/maverick/dreaming.py` (rehearsal refuses while frozen).

### 3.2 Deterministic snapshot-replay regression detector (no agent re-execution)
Before each consolidation pass, the entire learned state (reflexions, insights,
skills) is **snapshotted** with a timestamp. The regression detector then replays
a set of past goals against **two** snapshots (before/after a learning cycle) and
measures **coverage** — whether the learned state *surfaces* a relevant
reflexion/insight/skill for each goal — using the **same deterministic lexical
recall machinery the live agent uses**, with **no LLM calls and no agent
re-execution**. It classifies each goal as *gained*, *regressed*, or *unchanged*,
and emits the regression signal to the audit trail.

Evidence: `packages/maverick-core/maverick/hindsight.py:1-30, 139-214`
(snapshot-coverage replay, before/after comparison, deterministic recall reuse).

### 3.3 Atomic stage-then-swap rollback of the learned-state tree
Rollback stages the chosen snapshot into a temporary sibling
(`<live>.rollbacktmp`), copies the snapshot contents into it, and only on full
success performs an **atomic `os.replace`** swap into the live location. A failure
mid-copy abandons the temp dir and **never touches the live store**, eliminating
the "a restore that destroys the good state" failure mode.

Evidence: `packages/maverick-core/maverick/dreaming.py:1301-1413`
(snapshot creation; staged atomic restore).

### 3.4 (Supporting) Bounded, configuration-only evolutionary search with quality-diversity archive
The self-improvement search mutates only **whitelisted configuration knobs within
schema bounds** (never code), so a candidate can never escape the sandbox; the
archive retains a **quality-diverse** subset via greedy max-min selection on a
normalized config-key distance, preventing collapse onto a local optimum.

Evidence: `packages/maverick-evolve/maverick_evolve/config_space.py`,
`search.py`, `archive.py:35-103` (diverse() greedy selection; config_distance()).

## 4. Why it is novel / non-obvious

- **Freeze-and-resume gated on evaluator *discrimination*** is a specific
  anti-reward-hacking interlock: it ties the *learning system's* permission to
  change itself to a measured property of its *own evaluator*, and preserves
  search progress across the pause. Prior self-improvement work scales generators
  or ensembles verifiers; it does not gate the learning loop on an online
  calibration statistic with persistent-pause semantics.
- **Regression detection by snapshot-coverage replay** answers "did this make us
  worse anywhere?" **deterministically and cheaply** by reusing the live recall
  function over stored snapshots — avoiding LLM re-execution entirely. This is a
  non-obvious substitution (coverage-as-proxy via the production recall path)
  that makes per-cycle regression checking practical.
- **Stage-then-atomic-swap rollback** for a multi-file learned-state *tree*
  specifically defeats destructive-restore failure.
- The three combine into a **closed, safe loop**: drift freezes learning;
  snapshots enable both regression detection and safe rollback; bounded search
  prevents escape.

## 5. Draft claims (sketch for counsel — not final)

**Independent (method).** A method for safely self-modifying an autonomous agent
comprising: maintaining an evaluator that scores candidate agent behaviors;
repeatedly computing a discrimination measure from samples pairing evaluator
confidence with observed correctness; when the discrimination measure is below a
threshold, suspending iterations of a self-improvement loop while retaining an
accumulated archive of candidate configurations, and resuming the loop from the
retained archive when the discrimination measure recovers; periodically
snapshotting a learned state of the agent; and detecting a learning regression by
replaying a set of prior tasks against a first and a second snapshot and
comparing, for each task, whether the snapshot surfaces a relevant learned item
using a deterministic recall procedure that executes without invoking a language
model and without re-executing the agent.

**Independent (rollback).** A method comprising: storing successive snapshots of a
multi-file learned-state tree; and reverting by copying a selected snapshot into a
temporary location adjacent to the live tree and, only upon successful completion
of the copy, atomically replacing the live tree with the temporary location, such
that a failure during the copy leaves the live tree unmodified.

**Dependent (sketch).** ...wherein the self-improvement loop mutates only
configuration parameters constrained to a predefined schema and bounds; ...wherein
suspended iterations are recorded with a freeze reason; ...wherein the regression
detector classifies each task as gained, regressed, or unchanged and emits the
result to a tamper-evident audit trail; ...wherein the discrimination measure is a
difference of mean evaluator confidence on correct versus incorrect outcomes over
at least a minimum sample count; ...wherein the archive is maintained as a
quality-diverse subset selected by greedy maximization of minimum pairwise
configuration distance.

## 6. Alternatives / variations

- Calibration statistic: discrimination → AUC/Brier/ECE; threshold static or adaptive.
- Pause granularity: per-round → per-candidate / per-time-window.
- Coverage proxy: lexical recall → embedding recall, as long as deterministic.
- Snapshot scope: full tree → incremental/diff snapshots.
- Search: evolutionary/QD → bandit/Bayesian over the same bounded config schema.
- Regression action: report-only → auto-rollback on regression beyond a budget.

## 7. Drawings to prepare

1. **Fig. 1** — closed loop: experience → consolidation → snapshot → evolve →
   evaluator → (calibration gate) → apply/rollback.
2. **Fig. 2** — calibration interlock state machine (RUNNING ⇄ FROZEN; archive
   persists across FROZEN).
3. **Fig. 3** — snapshot-replay regression detector (before/after snapshots →
   coverage compare → gained/regressed/unchanged).
4. **Fig. 4** — stage-then-atomic-swap rollback (temp sibling → os.replace).
5. **Fig. 5** — bounded config search + quality-diverse archive selection.

## 8. Evidence index (file:line)

- `packages/maverick-core/maverick/calibration.py` (discrimination + freeze)
- `packages/maverick-evolve/maverick_evolve/loop.py:29-86` (skip-on-freeze, archive persist)
- `packages/maverick-core/maverick/hindsight.py:1-30, 139-214` (regression replay)
- `packages/maverick-core/maverick/dreaming.py:1301-1413` (snapshot + atomic rollback)
- `packages/maverick-evolve/maverick_evolve/archive.py:35-103` (quality-diversity)
- `packages/maverick-evolve/maverick_evolve/config_space.py`, `search.py` (bounded search)
