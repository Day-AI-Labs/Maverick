# Decision: park the learning substrate (keep what's wired, don't close the loop yet)

**Status:** Decided — park, don't close, don't prune · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (C2) · **Date:** June 2026

## The question

Roadmap **C2** was an open decision: **close the eval→reward loop** (train on
donated trajectories; learn the compaction/reflexion gates from outcome reward;
run RLAIF/DPO on the proposer) — **or prune the scaffolds** (`training/`,
`prm.py`, the compaction gate) as speculative complexity?

## What's actually in the tree (verified)

**Real and wired — keep as-is:**

- `prm.py` — the `ProcessRewardModel` *protocol* plus `NullPRM` / `HeuristicPRM`
  / `RemotePRM` / `LearnedPRM`. The agent loop consumes the interface
  (`agent._score_step`), and **`HeuristicPRM` is the shipping default — it needs
  zero training** and works today. `LearnedPRM` lazily loads a trained head and
  **falls back to `HeuristicPRM`** if torch/the head is absent (fail-open).
- `donation.py` — opt-in (`[telemetry] donate_trajectories`, default OFF),
  client-scrubbed, metadata-only, **selective** (only `disagreement_high AND
  success` — the cases the swarm beat a solo agent). Writes to a local outbox;
  does not phone home.
- `training/ingest.py` + `training/prm_train.py` — read donated trajectories,
  label them, train an AgentPRM head. Operator-run; torch is an optional extra,
  imported lazily; the pure helpers are unit-tested.

**Scaffold — not closed:**

- `training/rlaif.py` — a complete DPO trainer, but operator-side (GPU + a real
  base model), never invoked in-kernel; and its text reconstruction is limited
  because Klear rows hash observations for PII.
- The **learned compaction gate** — `compaction.py` keeps the drop/keep boundary
  *hardcoded* (`KEEP_RECENT_TURNS`, `MAX_TOOL_OUTPUT_BYTES`, `DIGEST_EVERY`); the
  "learn the gate from outcome reward" half (which the module docstring itself
  flags as pending) does not exist.
- **Learned reflexion weighting** — `reflexion.py` recall uses a fixed recency
  weight; no outcome-reward feedback.
- The **outcome-reward → gates feedback loop** — the verifier verdict is
  final-only; nothing propagates a per-step reward back to retune compaction or
  reflexion.

## Decision

**Park the substrate. Keep the wired half; do not close the loop now; do not
delete the scaffolds.**

Concretely:

1. **Keep** the PRM interface + `HeuristicPRM` default + the donation/ingest
   data-shaping. These ship value today (step scoring with zero training; a clean
   seam to drop a trained model in later) and cost nothing at runtime.
2. **Do not build** the close-the-loop work (RLAIF in-kernel, learned
   compaction/reflexion gates, the outcome-reward feedback loop) yet.
3. **Do not prune** (delete) the offline scaffolds. They're lazily imported,
   fail-open, and carry zero runtime cost when unused; they document the intended
   architecture and the data they consume is already being shaped correctly.
4. **Label** the offline/experimental pieces as operator-side + experimental
   (the module docstrings already do — `prm.py` "Wave 7c: scaffold",
   `training/__init__` "Real training requires GPU + trajectory volume",
   `compaction.py` "learn the gate … lands when we have outcome reward"). This
   decision formalizes that status.

## Why park (not close, not prune)

- **Closing the loop now is speculative complexity.** The training flywheel is,
  per the Karpathy review the code cites, "the only piece that earns ML
  complexity" — but it earns it **only at trajectory volume**, which a pre-PMF
  project doesn't have. Building a 6–8-week outcome-reward training loop before
  there are trajectories to train on violates "simplicity first / nothing
  speculative" (CLAUDE.md). It's a push where the right move is demand-pull.
- **Pruning throws away correct, tested, free interface code.** The PRM protocol,
  the donation schema, and ingest are the *data-shaping* half. They make
  `HeuristicPRM` useful now and make a future trained model a drop-in. Deleting
  them would have to be re-written verbatim the day volume arrives. Keeping them
  costs nothing (lazy imports, fail-open, off by default).
- **It also matches the commercial reality.** The surviving wedge is the
  self-hostable, provable, regulated agent runtime — not an ML-training product.
  Founder/eng attention belongs on the Governed-Runtime track, not on a training
  loop with no data and no GPU operator.

## The tripwire (when to revisit — close it on demand-pull)

Revisit "close the loop" when **both** hold:

1. **Volume:** a meaningful corpus of donated trajectories has accumulated from
   real usage (order hundreds+), enough that a learned PRM head or DPO pass could
   plausibly beat `HeuristicPRM`; **and**
2. **An operator pull:** someone (a design partner, or Maverick itself with a GPU
   budget) actually wants to run the offline trainer.

At that point, sequence it as the map's "Option A": collect per-episode outcome
metadata → learn the compaction gate first (smallest, reuses the `LearnedPRM`
pattern) → then reflexion weighting → then RLAIF text reconstruction, each behind
a flag defaulting OFF. Until both tripwire conditions hold, this stays parked.

## Code changes implied

**None required.** The fail-open / opt-in posture the decision depends on already
exists: donation is opt-in (default OFF), `LearnedPRM` falls back to
`HeuristicPRM`, `reflexion` and `self_learning` are opt-in, and the heavy
trainers import torch lazily and never run in-kernel. This decision is a
record + a tripwire, not a build. (If a `[learning]` umbrella config section is
later wanted to group the existing flags, that's a cosmetic follow-up, not part
of this decision.)
