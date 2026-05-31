# State-of-the-art review — May 2026

A frontier-readiness audit of the Maverick agent kernel, with a prioritized,
acquisition-oriented backlog. The goal is honesty: what is already
world-class, what is genuinely behind the 2026 frontier, and where the
highest-leverage moves are.

This doc is a strategic frame, not a contract. The first two items in
"Shipped in this pass" landed with tests; the rest is backlog.

## Verdict

Maverick is a **near-frontier** long-horizon agent kernel. It is not a
prototype: ~95k LOC across six packages, ~1,900 passing tests, a 36-month
roadmap, and a "council" review discipline visible throughout the git
history. Several subsystems are genuinely ahead of most shipping agent
frameworks.

### Already world-class

- **LLM layer (`providers/anthropic_provider.py`).** Three-breakpoint
  prompt caching (system + tool catalog + last stable turn) with
  per-model-family token minimums, byte-stable tool ordering to avoid
  silent cache busts, adaptive-vs-legacy extended-thinking gating that
  correctly handles Opus 4.7's adaptive-only constraint, per-block
  thinking-signature preservation across interleaved turns, and best-of-N
  temperature diversity wired end-to-end.
- **Agent loop (`agent.py`).** Test-driven verification on the
  orchestrator's FINAL, defensive patch validation (grader-fatal-path
  detection), SEARCH/REPLACE editing applied in disposable git worktrees,
  nonce-framed tool output (prompt-injection hardening), and killswitch +
  budget gates at every turn and tool boundary.
- **Breadth.** 12 providers (per-role routable), 11 channels, 7 sandbox
  backends, ~150 tools, an MCP client + server, and a safety shield wired
  at three chokepoints — fail-open, never a hard dependency.

## The real gaps (ranked by leverage)

### 1. No published benchmark numbers — the single biggest credibility gap

`benchmarks/RESULTS.md` contains one dry-run row. The harness
(`benchmarks/swe_bench.py`, `harness.py`) is real and runnable, but there
are **zero** live SWE-bench Verified / SWE-bench Pro / GAIA / τ-bench
results. This is the first question any acquirer or skeptic asks, and the
positioning ("performs at the level of OpenClaw/Hermes") is currently
unbacked.

The fix is not code; it is **spend + discipline**. Run SWE-bench Verified
end-to-end on a tagged release, commit the rows, and gate regressions in
CI against a stored baseline. Fabricated numbers are the one thing that
would actively destroy credibility, so the harness here was hardened and
the pipeline made reproducible rather than faking a result.

### 2. ~2,000 lines of unwired frontier-reasoning shelfware

`reflexion.py`, `prm.py` (process reward model), `tree_of_thought.py`, and
`debate.py` were imported **nowhere** outside their own tests. The
capability was built but never connected to the live loop — pure
aspiration. (`reflexion` is now wired; see below. `prm`, `tree_of_thought`,
and `debate` remain shelfware — wiring or deleting them is backlog item 6.)

### 3. Serial tool execution within a turn

The loop executed parallel tool calls one at a time. Frontier harnesses run
independent calls concurrently — the dominant SWE-bench localization
pattern is "read these 5 files," which was paying N× the latency it should.
(Fixed in this pass; see below.)

### 4. The moat is real but unmeasured

The genuinely differentiated angle vs. OpenAI/Google is the **persistent
world model + skill auto-distillation**: an agent that *compounds* across
runs. This exists (`world_model.py`, `skills.py`, `reflexion.py`) but is
opt-in, off by default, and has no metric proving it improves the next run.
Make "second attempt at a similar task is measurably better/cheaper" a
first-class, demoable benchmark and it becomes the headline.

## Shipped in this pass (with tests)

### Concurrent tool execution

When a single model turn emits 2+ tool calls and **every** one is
`parallel_safe`, the loop now runs them with `asyncio.gather` instead of
awaiting each in sequence. `parallel_safe` is a new, conservative
opt-in flag on `Tool` (default `False`); only pure, idempotent reads carry
it (`read_file`, `list_dir`, `repo_map`, `dep_graph`). A turn containing any
stateful tool (shell, write, spawn, `ask_user`, a rate-limited network
tool) falls back to the serial path, so side-effect ordering and the
block-on-user semantics are unchanged. Toggle with
`MAVERICK_PARALLEL_TOOLS=0`. Covered by `tests/test_parallel_tools.py`.

### Reflexion learning loop, wired in

`reflexion.py` is now connected to `orchestrator.run_goal`: on a failed run
it records a deterministic postmortem (no extra LLM spend on the
already-failing path), and on the next similar goal it recalls and injects
those lessons into the orchestrator brief. Off by default; enable with
`MAVERICK_REFLEXION=1` or `[reflexion] enable = true`. Covered by
`tests/test_reflexion_wiring.py`.

### Self-consistency voting in best-of-N selection

`select_best_candidate` previously broke all-zero-score ties (the common
case when no ground-truth tests are available) by preferring the
last/largest attempt. It now applies majority voting first: among N
independent rollouts, the patch whose changed-file set agrees with the
plurality of other attempts is preferred over a lone outlier. It is a
strict refinement — when every attempt touches a distinct file set the
prior ordering is unchanged. Off-switch: `MAVERICK_BON_CONSENSUS=0`.
Covered by `tests/test_bon_consensus.py`.

## Backlog (highest leverage first)

5. **Publish SWE-bench Verified numbers** on a tagged release; add a CI
   regression gate against a committed baseline (item 1).
6. **Wire or delete the remaining reasoning modules.** Integrate the PRM as
   a step-scorer in best-of-N selection, or remove `prm`/`tree_of_thought`/
   `debate` to stop advertising capability the loop doesn't use (item 2).
7. **Make the compounding moat measurable.** A "repeat-task" benchmark that
   reports cost/quality delta on the second run with world-model + skills +
   reflexion enabled (item 4).
8. **Extend parallelism to network reads.** Per-host concurrency caps would
   let idempotent network tools (arxiv, wikipedia, http_fetch) join the
   parallel path safely (item 3 follow-on).
9. **Speculative verification.** Start the verifier against the
   in-progress FINAL while the proposer is still streaming, to hide
   verification latency on long answers.
