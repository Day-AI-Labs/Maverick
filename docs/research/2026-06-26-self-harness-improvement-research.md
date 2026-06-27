# Improving a Shipped, Governed Self-Improving Harness Loop: A 2025–2026 Research Map

> Deep-research report (June 26, 2026) on how to improve `maverick.self_harness`.
> Method: fan-out web search → fetch 22 sources → extract 109 claims → 3-vote
> adversarial verification → 21 confirmed / 4 refuted. Sources are primary
> (arXiv / official repos) unless noted. Confidence tags reflect source quality
> and vote margins, not certainty about Maverick-specific transfer.

## Executive summary

The most direct precedent for Maverick's `self_harness` is **Self-Harness**
(arXiv 2606.09498), which validates the core bet: harness-only, model-specific
edits lifted held-out Terminal-Bench-2.0 pass rates by **+14 to +21 points**
across three models, using exactly the mine→propose→validate loop the platform
mirrors. The literature then closes Maverick's named gaps with concrete,
mostly primary-sourced techniques: for **proposer quality**, reflective/
textual-gradient optimizers (GEPA, TextGrad, RPT, ACE) replace generic
deterministic template lines with failure-trace-grounded edits and are
dramatically more sample-efficient than RL (GEPA: +6% avg over GRPO with up to
35× fewer rollouts) — directly relevant to the limited live-A/B budget. For
**mining**, RPT and ACE show how to cluster recurring failure *modes* (not
individual examples) into structured diagnostic reports, upgrading shallow
text-Jaccard clustering. For **granularity**, Continual Harness demonstrates
per-component (prompt/sub-agent/skill/memory) learning beyond a single
addendum, and a comprehensive survey gives a four-component vocabulary plus a
per-component taxonomy. For **validation/gating**, ACE's delta-update
anti-collapse mechanism and a documented reward-hacking result justify
hardening the gate against evaluation gaming. The dominant practical caveat is
sobering: only **9% of surveyed production agents use any automated
optimization** — these loops are brittle, and building a *trustworthy automatic
driver/evaluator* is the hardest, least-solved part.

---

## Finding 1 — The core premise is validated; the platform's three stages are the right structure

**Confidence: high** · **Stages: mine / propose / validate**

Self-Harness (arXiv 2606.09498) is operationalized as exactly the loop Maverick
implements: **Weakness Mining** (model-specific failure patterns from execution
traces), **Harness Proposal** (diverse yet minimal modifications tied to
failures), and **Proposal Validation** (accept edits only after regression
testing; acceptance rule Δ_in≥0, Δ_ho≥0, max>0). Reported within-model gains on
held-out Terminal-Bench-2.0 (traces never used as inputs): MiniMax M2.5
40.5%→61.9% (+21.4), Qwen3.5-35B-A3B 23.8%→38.1% (+14.3), GLM-5 42.9%→57.1%
(+14.2). — https://arxiv.org/abs/2606.09498

**Implication:** the architecture is well-founded. One structural difference:
the paper has **no separate GATE stage** — its acceptance rule *is* validation.
Maverick's gate (evidence floor, calibration-freeze, capability non-escalation,
reversibility, signed audit) is a governance layer *on top of* the published
method, so it must be justified from the safety literature (Finding 6), not
from this paper.

> Caveat: author-self-reported numbers on a ~3-week-old preprint with no
> independent replication. Treat the magnitude as indicative, not load-bearing.

## Finding 2 — Proposer quality: replace deterministic template lines with reflective, trace-grounded optimizers

**Confidence: high** · **Stage: propose** · **Closes: "deterministic fallback lines are generic"**

Four primary methods converge on: read full failure traces, reflect in natural
language, propose targeted minimal edits.

- **GEPA (Genetic-Pareto)** samples trajectories (reasoning, tool calls, tool
  outputs) and reflects in natural language to diagnose problems and
  propose/test prompt updates, merging complementary lessons from a Pareto
  frontier. Reads *full execution traces — error messages, profiling data,
  reasoning logs*. **Outperforms GRPO (RL) by 6% avg, up to 20%, using up to
  35× fewer rollouts** (ICLR 2026 Oral). — https://arxiv.org/abs/2507.19457 ·
  https://github.com/gepa-ai/gepa
- **TextGrad** backpropagates natural-language "textual gradients" to optimize
  components of a compound system, including prompts (published in Nature). —
  https://arxiv.org/abs/2406.07496
- **RPT (Reflective Prompt Tuning)** has an LLM optimizer call a diagnostic
  function over the *entire* set, summarizing recurring failure modes into a
  **structured diagnostic report**, then revising the prompt from it. —
  https://arxiv.org/abs/2605.21781
- **ACE (Agentic Context Engineering)** treats context as an evolving
  "playbook" refined by a Generator/Reflector/Curator loop (ICLR 2026). —
  https://arxiv.org/abs/2510.04618

**Recommendation:** keep the deterministic template as the *fail-open fallback*
(kernel rule 1) but inject a GEPA/RPT-style reflective proposer as the primary
`propose` seam. The existing injected-seam design makes this low-friction.

## Finding 3 — Mining: cluster recurring failure *modes*, not goal-text Jaccard

**Confidence: high** · **Stage: mine** · **Closes: "greedy text-Jaccard clustering is shallow"**

RPT's mechanism is the cleanest published answer: a diagnostic function
produces response-level critiques across the whole set, then **ClusterFusion
groups semantically similar diagnoses into recurring failure topics** before the
optimizer conditions on the report. The paper explicitly critiques per-example
updates as "sensitive to local rather than recurring failures" — exactly
Maverick's risk with greedy goal-text clustering. ACE corroborates by distilling
Reflector "lessons" into curated strategy bullets rather than raw traces.
— https://arxiv.org/abs/2605.21781 · https://arxiv.org/abs/2510.04618

**Recommendation:** move from Jaccard-on-goal-text to **embedding/semantic
clustering of LLM-generated failure diagnoses** (a failure-mode taxonomy),
keeping the unscoped/model-tagged poison filter. Upgrade *what* gets clustered
(diagnoses) as much as *how*.

## Finding 4 — Granularity: per-component learning beyond a single goal-level addendum

**Confidence: high** · **Stages: mine / propose / operate** · **Closes: "only goal-level orchestrator-model failures are mined"**

**Continual Harness** (arXiv 2605.09998) self-edits **multiple components
simultaneously — its own prompt, sub-agents, skills, and memory** — via an LLM
Refiner that reads a recent trajectory window for failure signatures and emits
per-component CRUD edits (one `evolve_harness` tool). From scratch it cut
button-press cost vs a minimalist baseline and **recovered a majority of the gap
to a hand-engineered expert harness, with capability-dependent gains**. The
**self-evolving-agents survey** (arXiv 2508.07407) gives the taxonomy:
single-agent optimization splits into per-prompt, per-memory, per-tool, unified;
multi-agent covers per-role/per-worker — the axis Maverick is missing.
— https://arxiv.org/abs/2605.09998 · https://github.com/sethkarten/continual-harness
· https://arxiv.org/pdf/2508.07407

**Recommendation:** extend mining/propose to emit **per-role and per-tool**
guidance entries (not just orchestrator goal-level), starting with the
highest-traffic worker roles. The survey's four-component framework (System
Inputs → Agent System → Environment → Optimisers) is a clean vocabulary for
mine/propose/validate/gate.

> Caveat: Continual Harness was demonstrated on embodied game agents (Pokémon
> Red/Emerald), not enterprise coding harnesses; gains were below the capability
> floor on weaker models. "Per-role" maps to its sub-agent CRUD, not a formal
> role taxonomy.

## Finding 5 — Validation robustness: anti-overfitting and anti-collapse mechanisms

**Confidence: high** · **Stages: validate / gate** · **Closes: "small held-in/held-out split; reward hacking of an LLM judge"**

- **Pareto-frontier selection (GEPA)** tracks best-per-instance candidates and
  recombines complementary strategies to "avoid premature convergence to local
  optima" (+6.4–8.2% over greedy selection). An anti-(single-objective)-
  overfitting mechanism for the search itself. — https://arxiv.org/abs/2507.19457
- **Delta-style updates (ACE)** prevent **"context collapse"** (full rewrites
  erode detail) and **"brevity bias"** (dropping insights for concision) via
  structured incremental updates merged deterministically with non-LLM logic —
  the concrete mechanism to stop Maverick's bounded ≤8-line/1500-char addendum
  from eroding across promotions. — https://arxiv.org/abs/2510.04618
- **Reward-hacking is real and measurable:** fine-tuning on high-scoring-but-
  biased responses degrades downstream performance (GPT-Judge 8.86 clean vs 8.46
  biased) — a loop that promotes edits on a biased judge's high scores will
  absorb and propagate that bias. — https://arxiv.org/html/2510.12462v3

**Recommendation:** (a) adopt ACE-style **delta merges** for addendum updates
rather than full-rewrite proposals; (b) treat any single live A/B scorer as
gameable — rotate held-out splits and add metamorphic/sanity checks against
judge bias; (c) consider Pareto-style keep-multiple-candidates over
single-winner acceptance.

## Finding 6 — Governance of self-modifying loops is a recognized first-class concern

**Confidence: high (recognition); medium (specific interlock prescriptions)** · **Stage: gate**

The self-evolving-agents survey devotes a **dedicated section to evaluation,
safety, and ethical considerations**, framed as prerequisites "critical to
ensuring their effectiveness and reliability" — i.e., auditability/evaluation-
robustness are prerequisites, not afterthoughts. This *underpins* (doesn't
prescribe in detail) Maverick's gate interlocks. The reward-hacking evidence is
the empirical justification for the **calibration-freeze interlock** (don't
learn while the verifier is drifting) and the **evidence floor**.
— https://arxiv.org/pdf/2508.07407 · https://arxiv.org/html/2510.12462v3

**Recommendation:** keep the gate; tie its calibration-freeze trigger to
measured judge/verifier drift, and log promotions to the signed audit with the
diagnostic report that motivated each edit (provenance for rollback).

## Finding 7 — The hardest gap: building a trustworthy automatic driver/evaluator

**Confidence: high** · **Stages: operate / validate** · **Closes: "no automatic driver; nothing builds a live A/B scorer"**

arXiv 2603.23994: **only 9% of surveyed production agents use any automated
optimization** — these loops "remain brittle" — and three under-specified
"hidden" design choices must be made explicit: **the starting artifact, the
credit horizon for execution traces, and how trials/errors are batched into
learning evidence**. The starting artifact *materially bounds reachable
solutions* (MLAgentBench), implying Maverick's generic deterministic-fallback
line constrains what PROPOSE can ever discover — a reason to seed the addendum
well. Two paths toward cheap evaluators: GEPA's **reference-free reflective
scoring** (35× more rollout-efficient than RL), and **ACE adapts effectively
without labeled supervision, using natural execution feedback**.
— https://arxiv.org/abs/2603.23994 · https://arxiv.org/abs/2507.19457 ·
https://arxiv.org/abs/2510.04618

> Important caveat from ACE itself: label-free adaptation degrades when
> "ground-truth supervision or reliable execution signals are absent" — a
> label-free evaluator is only as good as the execution-feedback signal it can
> extract.

---

## Prioritized, actionable improvements

| # | Improvement | Stage | Closes gap | Evidence | Cost | Risk (governance-first) |
|---|---|---|---|---|---|---|
| 1 | Inject a **GEPA/RPT-style reflective proposer** (full traces → diagnose → minimal edit); keep deterministic template as fail-open fallback | propose | Generic fallback lines | High (2507.19457, 2605.21781; GEPA ICLR'26 Oral) | Med | Low — behind existing seam; fallback preserved |
| 2 | **Semantic clustering of LLM-generated failure *diagnoses*** (failure-mode taxonomy) replacing goal-text Jaccard; keep poison filter | mine | Shallow clustering | High (2605.21781, 2510.04618) | Med | Low–Med — internal to mine |
| 3 | **ACE-style delta merges** for the bounded addendum (incremental, deterministic non-LLM merge) instead of full-rewrite proposals | validate/gate | Addendum erosion / context collapse | High (2510.04618) | Low | Low — strictly safer; preserves ≤8-line bound |
| 4 | Treat any single live judge as **gameable**: rotate held-out splits, metamorphic/anti-bias checks before promotion | validate | Anti-overfitting / reward hacking | High (2510.12462 + 2507.19457) | Med | Med — new eval infra; reduces gate-bypass risk |
| 5 | **Reference-free / execution-feedback scorer** (GEPA reflective or ACE natural-feedback) to bootstrap the missing live A/B evaluator | operate/validate | No automatic evaluator | High technique, Med fit (2507.19457, 2510.04618) | High | Med–High — judge bias + signal dependence |
| 6 | Extend mining/propose to **per-role and per-tool** guidance, starting with highest-traffic roles | mine/propose | Goal-level-only granularity | High direction, Med transfer (2605.09998, 2508.07407) | High | Med — more surfaces to govern; phase in one role at a time |
| 7 | Build the **automatic driver** (scheduler for mine→promote) — treat as the brittlest piece; explicitly fix starting artifact, credit horizon, batching | operate | No automatic driver | High caution (2603.23994) | High | High — 91% of production agents avoid this; gate + rollback must be airtight first |
| 8 | **Pareto / keep-multiple-candidates** acceptance vs single-winner, to resist single-objective overfitting | validate | Validation robustness | Med (2507.19457 mechanism is search-time) | Med | Low |

**Well-supported vs speculative:** Items 1–5 rest on primary, often
peer-reviewed sources with direct mechanism mapping. Item 6 is well-supported in
*direction* but its strongest evidence (Continual Harness) is from a game
domain; enterprise transfer is an inference. Item 7 is the most
speculative-to-operationalize — the evidence says it's hard and rarely done,
not that a specific recipe works. Item 8's mechanism is solid but its mapping
onto a *regression gate* (vs search-time selection) is the loosest here.

## Refuted claims (killed by adversarial verification — do NOT rely on these)

- **"Effective harness design is *inherently* model-specific"** (1-2 refuted,
  2606.09498). → The per-model keying choice should be justified empirically on
  Maverick's own traces, not assumed.
- **"Continual Harness is reset-free / fully removes the human from the loop"**
  (1-2 refuted, 2605.09998). → Don't cite it as a no-human-in-loop precedent.
- **"LLM judges suffer 5+ point bias swings from authoritative-but-wrong
  references"** (0-3 refuted, 2510.12462). → The *strong* magnitude claim didn't
  hold; the weaker, confirmed reward-hacking result (Finding 5) is what to cite.
- **"TextGrad works out-of-the-box across diverse tasks with no per-task
  tuning"** (0-3 refuted, 2406.07496). → Expect per-task setup if adopting it.

## Caveats

- Self-Harness (2606.09498) is ~3 weeks old, author-self-reported, unreplicated.
- Domain transfer risk: ACE/GEPA/Continual-Harness benchmarks are not enterprise
  governed-coding-harness settings. Mechanisms transfer more reliably than
  magnitudes.
- Label-free evaluation is contingent on a reliable execution signal.
- Judge bias is a live threat to the whole loop; the reward-hacking evidence is
  a fine-tuning study extrapolated to prompt-edit promotion.
- Most sources are 2025–2026 preprints; the field moves monthly — revalidate
  before committing engineering quarters.

## Open questions

1. Can a reference-free / execution-feedback scorer be made trustworthy enough
   to gate promotions, given ACE's warning that it degrades without reliable
   signals — or is a small curated labeled holdout irreducible? (2510.04618)
2. Does per-role/per-tool learning, demonstrated in game agents, transfer to an
   enterprise harness without exploding the governance surface — and how should
   the capability-non-escalation interlock scope per-role edits? (2605.09998,
   2508.07407)
3. What is the right credit horizon and batching for Maverick's traces? They
   silently determine loop behavior; no universal setting exists. (2603.23994)
4. How should the calibration-freeze interlock detect verifier/judge drift in
   production (what metric, what threshold) so the loop pauses before absorbing
   a biased judge's scores? (2510.12462)

## Sources (confirmed, primary unless noted)

- arXiv 2606.09498 — Self-Harness: Harnesses That Improve Themselves
- arXiv 2603.23994 — Understanding the Challenges in Iterative Generative Optimization with LLMs
- arXiv 2605.09998 — Continual Harness (self-editing prompt/sub-agents/skills/memory)
- arXiv 2507.19457 — GEPA: Reflective Prompt Evolution (ICLR 2026 Oral) · github.com/gepa-ai/gepa
- arXiv 2406.07496 — TextGrad: Automatic Differentiation via Text
- arXiv 2605.21781 — RPT: Reflective Prompt Tuning (diagnostic report + ClusterFusion)
- arXiv 2510.04618 — ACE: Agentic Context Engineering (ICLR 2026)
- arXiv 2510.12462 — reward-hacking / biased-judge degradation evidence
- arXiv 2508.07407 — Survey of Self-Evolving Agents (four-component framework + taxonomy)
- genai.owasp.org — OWASP Top 10 for Agentic Applications 2026 (governance context)

_Run stats: 5 angles · 22 sources fetched · 109 claims extracted · 25 verified ·
21 confirmed / 4 killed._
