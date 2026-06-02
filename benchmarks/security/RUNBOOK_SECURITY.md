# RUNBOOK — credible security numbers (v2)

v1 (`detector_score.py`) is an offline, internal dashboard. This runbook is
how a maintainer produces the **publishable** numbers: a held-out detection
score at scale, and an end-to-end attack-success-rate reduction. These steps
need network access and (for end-to-end) an API key + real budget, so they're
documented rather than wired into CI.

## Ground rules

1. **Never vendor harmful payloads.** HarmBench / AdvBench carry live harmful
   content and licensing weight. Pull on demand, pin the revision, and do not
   commit raw payloads (matches the corpus convention in CLAUDE.md).
2. **Guard against leakage.** Before scoring any external prompt set, run it
   through `detector_score.train_overlap(prompts)` and drop the overlaps.
   Report the dropped count. A number measured on phrases the rules were tuned
   on is memorization, not capability.
3. **Report provenance.** Every `RESULTS.md` row gets `source=measured`, the
   dataset name + pinned `revision=<sha>`, the split, the shield backend, and
   the N. Quote TPR/FPR with Wilson CIs.
4. **Don't launder the dashboard into the public claim.** The `docs/safety.md`
   F1 figure may only be updated from a held-out, per-backend measurement —
   never from v1's train-corpus dashboard.

## A. Held-out detection score (no API key; needs network)

Targets the *agentic* surface the shield actually defends, plus a single-turn
reference:

- **AgentDojo** — injection tasks (the real tool-output / indirect-injection
  surface). Use its attack prompts as positives.
- **JailbreakBench (JBB-Behaviors)** — single-turn jailbreaks, as a
  cross-reference only (it tests "will a model comply", not "is the agent
  hijacked").

Sketch:

```python
# pin revisions; pull on demand; do NOT commit the raw data
from datasets import load_dataset
jbb = load_dataset("JailbreakBench/JBB-Behaviors", revision="<sha>", split="harmful")
prompts = [r["Goal"] for r in jbb]

from benchmarks.security import detector_score, corpus
leaks = detector_score.train_overlap(prompts)          # drop trained-on phrases
held = [p for p in prompts if p not in set(leaks)]
# score `held` (positives) + corpus benign (negatives) across BACKENDS,
# including the full SDK: `pip install agent-shield` then add it as a backend.
```

Install the full SDK so the `agent_shield_sdk` backend is no longer
UNAVAILABLE — that's the backend the `0.988` claim refers to, and the only one
that can substantiate it.

## B. End-to-end ASR reduction (needs ANTHROPIC_API_KEY + budget)

Run the **whole agent** through AgentDojo with the shield ON vs OFF and report
the attack-success-rate delta plus the benign task-completion delta (the
over-refusal cost). This is the headline "Maverick blocks N% of AgentDojo
injections" claim.

```bash
pip install agentdojo
python benchmarks/preflight.py                 # validate key + model IDs first
# shield OFF (baseline):  MAVERICK_SHIELD=off  python -m benchmarks.security.agentdojo_e2e --suite injection
# shield ON:                                   python -m benchmarks.security.agentdojo_e2e --suite injection
```

`agentdojo_e2e` is intentionally not implemented offline-untested — wire it
against the installed AgentDojo API when you run it, mirroring the
`cost_tracker` + `RESULTS.md` conventions in `benchmarks/harness.py`. Track
`$`/tokens/wall via `cost_tracker`, and respect `Budget` (CLAUDE.md rule 3).

## Definition of done for v2

- `RESULTS.md` gains a held-out detection table (per backend incl. SDK, with
  revisions + CIs) and an end-to-end ASR table (shield ON/OFF + benign-completion).
- The leakage-dropped count is recorded.
- Only then, if warranted, update the `docs/safety.md` figure — citing this file.
