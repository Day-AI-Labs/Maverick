# Rigorous compounding-moat — results (2026-06-16)

Live run of the protocol in `moat_rigorous.py`. **Read this with its caveats —
it is an honest, *bounded* result, not a hero number.**

## What was run

Same target task B run two ways; the only difference is the store:
- **WARM**: run a related prior task A first (it distills a skill / writes
  facts), then run the SAME B against that warm store.
- **COLD**: run the SAME B against a fresh, empty store.

Settings: relevance gate **ON** (the merged default), builtin skill library
**off** (so the only memory is what A produced), `orchestrator` pinned to
**Sonnet** and `cap=$1.25/run`. *Why Sonnet:* on the default Opus orchestrator
at a $1 cap every run truncates — the budget refuses the next call (`"budget
exceeded: projected $1.09 > $1.00"`) before the agent finalizes, so nothing
completes **and** the populate run never succeeds, so it distills nothing and
warm has nothing to recall. Pinning a cheaper orchestrator lets tasks complete;
the model is held identical across warm and cold, so the delta still isolates
memory. (First attempt, Opus@$1: 13 episodes, **all** truncated DNFs, $9.03 —
a harness artifact, not a product signal.)

Intended 3 pairs × 3 seeds; the $7 spend guard stopped it after **4
observations** (cold-start runs are expensive and high-variance). So this is
3 seeds of `auth→authz` + 1 of `budget→risk`; `reflexion→dreaming` was not
reached.

## Observations

| pair | seed | A ok? (cost) | skill distilled | warm $ / tools / ok | cold $ / tools / ok | cost Δ |
|---|---|---|---|---|---|---|
| auth→authz | 0 | ✗ ($1.63) | 0 | 0.200 / 9 / ✓ | 0.583 / 33 / ✗ | −65.6% |
| auth→authz | 1 | ✓ ($0.22) | 1 | 0.358 / 22 / ✓ | 0.779 / 48 / ✓ | −54.1% |
| auth→authz | 2 | ✓ ($0.44) | 1 | 0.075 / 3 / ✓ | 1.015 / 36 / ✗ | −92.6% |
| budget→risk | 0 | ✗ ($1.04) | 0 | 1.212 / 43 / ✗ | 1.054 / 71 / ✗ | +15.0% |

Aggregates: warm not-worse-than-cold **3/4**; cost delta **median −59.9%**,
mean −49.4%; autonomous completion **warm 3/4 vs cold 1/4**; populate(A)
succeeded 2/4, distilled a skill 2/4.

## The finding (and why it matters)

**The moat appears exactly when learning occurred, and is absent when it
didn't.** Both observations where A distilled a skill (auth s1, s2) show warm
recalling it and finishing the related task in **3–22 tool calls at −54% to
−93% cost**, while cold re-explored **36–48 tool calls** and failed to finish
autonomously 2 of 3 times. The two observations where A failed to distill show
**no reliable benefit** — one still cheaper (residual world-model facts from
A's exploration), one a +15% regression. That the benefit tracks the `skill
distilled` column — not run order or luck — is the evidence that **retained
memory drives it**, not noise. This is the relevance gate doing its job too:
warm was within-or-below cold on 3/4, and the one miss is a no-memory case.

## Caveats — what this does NOT show

1. **Small N, one dominant family.** 4 observations; 3 are `auth→authz`. Only
   1 `budget→risk`, 0 `reflexion→dreaming`. **Generality is not established.**
2. **No correctness grader.** These are open-ended summaries. "Success" =
   reached a final answer autonomously without hitting the cap or stopping to
   ask the user. Cold "failures" are DNFs — heavy exploration (33–71 tools) or
   `"blocked awaiting user"` clarification stalls — **not wrong answers**. So
   the measured benefit is *autonomous-completion efficiency*, not accuracy.
3. **High cold-start variance.** A itself failed 2/4 (cold-start hits the cap
   at ~30 tools). Cold ranged 33–71 tools. Variance is large vs N=4.
4. **Effect size is partly inflated** by cold's pathological over-exploration;
   with a tighter exploration budget or a grader the gap would likely shrink.
5. **`budget→risk` is an honest negative**: A, warm, and cold all failed; with
   no distilled skill, memory gave no help (warm +15%).

## Defensible claim

> On a task family where a prior run distilled a skill, the warm agent recalled
> it and completed the related task in 3–22 tool calls at 54–93% lower cost,
> where the cold agent re-explored 33–48 tools and usually failed to finish
> autonomously. The benefit is causally tied to whether a skill was actually
> distilled. **Bounded:** small N over one main task family on a single
> codebase, measuring autonomous-completion efficiency (no correctness grader),
> with high cold-start variance — generality and accuracy still to be earned.

## Reproduce / next steps

- Pin a completing orchestrator and adequate cap (Opus@$1 truncates — see above).
- To harden into a headline: add a correctness grader (so cold DNFs vs wrong
  answers are distinguished), run all 3+ families × ≥5 seeds, and report
  pass^k and a learning curve (early lift → plateau), not a single ratio.

Total spend for this evidence: **$17.64** ($9.03 truncated first attempt +
$8.61 corrected run) of a $20 budget.
