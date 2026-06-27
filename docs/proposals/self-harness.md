# Self-Harness: a governed loop that learns a model-specific harness addendum

**Status:** shipped (opt-in, OFF by default) · **Module:** `maverick.self_harness`
· **Reference:** *Self-Harness: Harnesses That Improve Themselves* (arXiv 2606.09498)

## Motivation

Maverick already learns **behaviors** — skills and dream insights distilled from
experience and recalled as prompt context. But the **harness itself** (the
operating instructions a model runs under) was static and operator-owned: a
model that keeps making the same class of mistake never adjusts how it is
instructed.

The Self-Harness paper shows that treating the harness as a *model-specific,
learnable* artifact — mining a model's own failure traces, proposing minimal
edits, and regression-validating them — is worth double-digit gains
(+14–21pt pass-rate on Terminal-Bench-2.0 across MiniMax/Qwen/GLM, same models,
harness-only change). The companion paper *Understanding the Challenges in
Iterative Generative Optimization with LLMs* (arXiv 2603.23994) explains why so
few systems do this safely: the make-or-break design choices are hidden, and an
edit that overfits its own examples silently regresses unseen cases.

## What ships

A four-stage loop that **reuses Maverick's existing governance spine** rather
than adding a new ungoverned optimizer:

1. **MINE** — `mine_failures(reflexions, model_id=…)` clusters one model's
   failure reflexions into recurring *weakness signatures*. Model-specific by
   construction: a weakness mined for one model can never leak into another's
   harness (the paper's key lever). A `model_id` was added to the reflexion
   record to enable this; older lines load as `None` (backward compatible).
2. **PROPOSE** — `propose_addendum(sig, propose_fn=…)` produces a single
   *minimal* operating-guidance line targeting the signature. The LLM proposer
   is an injected seam: `llm_proposer(llm)` ships a reflective proposer in the
   GEPA/RPT shape (arXiv 2507.19457 / 2605.21781) — read the signature + example
   goals, write one minimal line, **fail open** to the deterministic fallback on
   any provider error. That fallback is **failure-class-grounded** (specific
   per-class guidance, not a generic "slow down" line — arXiv 2603.23994 warns
   the starting artifact bounds what the loop can learn) and runs without a
   provider, so the loop stays testable offline. Either way the line flows
   through `_sanitize_line` + the length gate.
3. **VALIDATE** — `validate_proposal(...)` runs the paper's acceptance test: the
   edit must not regress **either** a held-in split (the mined cases) or a
   **held-out** split (unseen cases — the overfitting guard), and must help at
   least one. Scorers are injected; a live A/B needs a real model, exactly like
   `learning_rollout`'s constraints.
4. **GATE** — each validated proposal becomes a `self_improvement.Candidate` on
   the `prompt` rung and goes through `consider()`. It therefore inherits the
   evidence floor, the calibration-freeze interlock (no learning while the
   verifier is drifting), capability non-escalation, the reversibility
   requirement, and the signed learning audit. **Promotion requires
   `[self_improvement] enable`** — self-harness proposes, the shared gate
   decides.

The accepted addendum is a small per-model block **recalled into the system
prompt** at build time (`recall_addendum(model_id)`, wired into
`Agent._build_system`), keyed on the agent's resolved model so a worker's lesson
never bleeds into the orchestrator's. It is **never a mutation of the kernel
templates** — it is a file entry, and removing it is the rollback handle. This
keeps it inside the same "behavior recalled as context, snapshot + rollback"
safety model as skills and insights.

## Safety properties

- **OFF by default** (`[self_harness] enable` / `MAVERICK_SELF_HARNESS=1`); when
  off, `recall_addendum` returns `""` and the prompt is byte-for-byte unchanged.
- **Trace-poisoning is closed (two layers).** The addendum is recalled into
  every future run of a model across all channels/tenants, so an attacker who
  could plant text in a failure trace could otherwise poison it. (1) `mine_failures`
  only considers **unscoped** failures — no `channel`, no `user_id` — i.e.
  operator-local runs, never remote-user-driven ones (mirrors dreaming's
  unscoped-only guard). (2) Every proposed line — deterministic *or* from an LLM
  proposer — passes through `_sanitize_line`: control chars stripped, all
  whitespace collapsed to single spaces (no multi-line break-out), secrets
  scrubbed, length bounded. A corrupt/tampered store with non-string values is
  rejected by `load_addenda` (no literal `"None"` reaching a prompt). (3) A
  **semantic policy-erosion screen** (`_erodes_policy`) refuses a proposed line
  that tells the model to disable/bypass/ignore its own safety machinery
  (validation, auth, budget, sandbox, audit, ...) — `_sanitize_line` guards
  syntax and the gate guards capability, but neither reads the MEANING of prose
  that rides in every future prompt.
- **Two gates, not one:** self-harness only proposes; promotion needs the
  self-improvement controller. A frozen verifier or a disabled controller leaves
  the store untouched.
- **No overfitting promotion:** the held-out split is mandatory; a pure trade is
  rejected. A live caller can tighten the evidence bar with opt-in floors
  (default off, back-compatible): `require_held_out` (never promote on only the
  mined examples), `min_held_out` (an unseen-sample floor — a 1-of-1 "win" is not
  evidence), and `min_delta` (an effect-size floor — sub-threshold lift on noisy
  agent eval scores is not a durable improvement).
- **Reversible + audited:** every applied line has a rollback handle and a signed
  `LEARNING_UPDATE` audit row.
- **Bounded + non-eroding:** an addendum is capped (`_MAX_LINES_PER_MODEL`,
  `_MAX_ADDENDUM_CHARS`) so it can't bloat every prompt, and `_compose_addendum`
  delta-merges a re-promoted line (normalized-exact: case/whitespace/punctuation)
  rather than spending a second slot on a trivial reword — an ACE-style guard
  against "context collapse"/"brevity bias" (arXiv 2510.04618).
- **Auditable provenance:** every applied line's signed `LEARNING_UPDATE` row
  carries *why* it was learned — the weakness signature + rationale and the
  unseen-split evidence (`held_out_delta`, `samples`) — not just the text, so a
  rollback or compliance review can see the diagnostic behind each edit. The
  same provenance is also kept in a **structured per-line sidecar** (`*.meta.json`,
  keyed by a content-addressed line id) alongside the prompt-bound store — which
  stays byte-stable — reconciled to the block under the same lock, restored on
  rollback, and best-effort (a missing sidecar never affects recall).
- **Retirable (anti-staleness):** prompt guidance goes stale as models, tools,
  and APIs change. `retire_stale(older_than_days=…)` removes lines not refreshed
  (re-promoted) within a TTL — a line that keeps proving useful stays; a line
  with no provenance record (legacy) is never auto-retired since its age is
  unknown. Audited with phase `retire`.

## Operating it

- `maverick self-harness preview [--model M] [--min-support N]` — read-only dry
  run: shows the weaknesses and the lines it *would* propose, writes nothing.
- `maverick self-harness show [--verbose]` — what was learned per model;
  `--verbose` adds each line's provenance (signature, held-out delta, samples,
  learned/updated dates) so an operator can judge the evidence behind it.
- `maverick self-harness retire --older-than-days N` — prune stale guidance.
- `maverick self-harness log` / `forget` — the audit trail and the undo handle.
- Automatic operation: an operator/scheduler calls `run_self_harness(...)` with a
  live held-in/held-out scorer (the A/B over the candidate prompt) and the
  self-improvement controller engaged.

## Addresses paper #2's "hidden design choices"

The loop makes the previously-implicit choices explicit and tunable:
*starting artifact* = the current per-model addendum; *editability scope* = a
single appended guidance line on the `prompt` rung (never code/tools);
*credit horizon* = the failure signature mined from traces; *batching* =
`min_support` (the evidence floor) and the held-in/held-out split sizes.
