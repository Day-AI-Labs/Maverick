# Design Spec: Durable & Resumable Execution

**Status:** Draft / proposal · **Roadmap ref:** [`ROADMAP-ADDITIONS.md`](../ROADMAP-ADDITIONS.md) §A1 ([#396](https://github.com/cdayAI/Maverick/issues/396)) · **Date:** May 2026

> This is a proposal for discussion, not an accepted design. It deliberately
> stops at the interface + phasing; implementation waits on sign-off.

## 1. Problem

Maverick's headline promise is *"runs for hours, pause overnight, resume."* The
**world model** (`world_model.py`, SQLite schema v9) durably persists goals,
episodes, facts, questions, messages, and `goal_events`. But the **in-memory
agent-loop state is never serialized**:

- per-agent LLM **message/context history** and current **step index**
  (`agent.py`, loop bounded by `max_steps`, default 25),
- the live **blackboard** (`blackboard.py`; only *mirrored* to `goal_events` as
  human-readable lines, not as resumable state),
- the **sub-agent tree** created by `spawn_subagent` / `spawn_swarm`,
- mid-run **budget counters** (`budget.py`) — tokens/$/tool-calls spent so far,
- in-flight **tool calls** and their results.

### Current "resume" is a warm restart, not state restoration
On crash, `world_model.reclaim_orphan_goals()` flips stuck `active`/`pending`
goals to `blocked`. `maverick resume <id>` then re-invokes
`orchestrator.run_goal()`, reconstructing *context* by threading prior
conversation, answered clarifying questions, and facts back into the
orchestrator's brief (`orchestrator.py:~330-380`). That closes the
human-in-the-loop gap, but the agent **starts over at step 0** with a text
summary of what it knew. A 2-hour run that dies at step 20 redoes all 20 steps
and re-spends the budget. There is also **no rewind/fork** ("go back to step N
and try a different branch") and **no deterministic replay**.

## 2. Goals / non-goals

**Goals**
- G1. **Crash-resume**: after SIGKILL/OOM/host-reboot, resume a run from the last
  committed step instead of from scratch, preserving spent-budget accounting.
- G2. **Rewind/fork**: restart a run from an earlier checkpoint (`--to-step N`),
  optionally as a new forked goal, leaving the original intact.
- G3. **Pluggable, local-first store**: default to the existing SQLite DB; allow a
  different backend (e.g. a durable KV) via config, with a self-host path.
- G4. **Opt-in, fail-open**: off by default; a checkpoint-store error degrades to
  today's warm-restart behavior, never aborts a run (kernel rule 1 posture).

**Non-goals (this spec)**
- N1. Capturing **sandbox filesystem** state. Checkpoints record agent *reasoning*
  state, not the workdir. Filesystem rollback is a *separate* item that pairs with
  sandbox snapshot/restore (docker commit / firecracker snapshot) — noted in §7.
- N2. **Exactly-once** tool side effects. Tools that already executed
  (a `git push`, an email) are not undone by rewind. We target **at-least-once**
  with idempotency guidance (§6).
- N3. Full **deterministic replay** (fixed seeds + mocked tools). It's a Phase 4
  follow-on that builds on the same checkpoint records (§8).

## 3. What gets checkpointed

A **checkpoint** is the minimal state needed to reconstruct a running swarm. Per
**agent node**:

```
AgentCheckpoint:
  agent_id        # Agent.name (role-depth-<hex>), stable across resume
  parent_id       # None for the orchestrator
  role, brief, model, depth, max_steps
  step_index      # next step to execute
  messages        # the LLM context history for this agent (the expensive part)
  status          # running | awaiting_children | awaiting_user | final | error
  verifier_state  # _verifier_revision_used, last verdict
  result          # AgentResult once final
```

Per **run** (swarm-level), keyed by `goal_id`:

```
RunCheckpoint:
  goal_id, schema_version, created_at, step_seq (monotonic)
  budget_snapshot      # tokens/$/tool-calls/wall already consumed (budget.py)
  blackboard_entries   # full structured entries, not just the goal_events mirror
  agent_tree           # list[AgentCheckpoint] + edges
  pending_questions    # question ids the run is blocked on
  config_fingerprint   # provider/model/persona/sandbox hash (see §6 "drift")
```

**Checkpoint boundary = the agent turn boundary.** The loop already has a clean
seam after each LLM turn + tool batch. We commit a checkpoint *after* a step's
tool results are recorded and *before* the next LLM call. This makes the unit of
lost work exactly one step (≤ ~1 LLM turn), which matches the `max_steps` model.

**Storage shape.** Append-only `step_seq`-ordered records (cheap writes, no
rewrite-on-update), in a new `checkpoints` table alongside the world model so it
inherits WAL + `busy_timeout` and the dashboard's concurrent-read safety. Old
checkpoints for a completed goal are pruned on success (keep last N for rewind).

## 4. Resume / rewind flow

```
maverick resume <goal_id>            # G1: continue from latest committed step
maverick rewind <goal_id> --to-step N [--fork]   # G2: restart from step N
```

Resume path:
1. Load the latest `RunCheckpoint` for `goal_id`. If none (legacy goal / store
   disabled) → fall back to **today's warm-restart** path unchanged.
2. Rebuild `SwarmContext` (`swarm.py`): fresh sandbox/shield/mcp_clients, but
   **rehydrate** `Budget` from `budget_snapshot` and the `Blackboard` from
   `blackboard_entries`.
3. Reconstruct the agent tree: instantiate each `Agent` with its saved
   role/brief/model/depth and **inject its saved `messages` + `step_index`** so
   the loop continues mid-trajectory rather than re-running `_build_system` from
   step 0.
4. Re-attach the world model and resume the orchestrator from the saved node
   statuses (a node `awaiting_children` re-awaits; `awaiting_user` re-checks
   answered questions exactly as resume does today).

Rewind/fork: same as resume but load checkpoint at `step_seq ≤ N`; with `--fork`,
`world_model.create_goal(parent_id=<orig>)` and write the restored state under the
new goal id, leaving the original untouched (enables "try a different branch").

## 5. Integration points (existing modules)

- `orchestrator.run_goal()` — add a `resume_from: RunCheckpoint | None` param;
  the existing warm-restart context-threading stays as the fallback path.
- `agent.py` loop — emit a checkpoint at the turn boundary via a
  `ctx.checkpointer` handle; accept injected `messages`/`step_index` on construct.
- `runner.run_goal_in_thread()` — unchanged surface; it already owns the
  process-wide run lifecycle the dashboard/REST/MCP share.
- `budget.py` — add `snapshot()` / `restore()` (it already defines
  `__getstate__`/`__setstate__` for multiprocessing, so the fields are known).
- `blackboard.py` — persist/replay structured entries (today it only mirrors to
  `goal_events`).
- `killswitch` + shield + hooks — checkpoints are written *after* the same
  turn/tool boundary those gates already run at; no new bypass.
- Config: `[durable] enabled = false`, `backend = "sqlite"`, `keep_last = 5`.
  Wizard gets one question (kernel rule 6).

## 6. Hard parts (and how this spec handles them)

- **Concurrency mid-`asyncio.gather`.** `spawn_swarm` fans out parallel children.
  A checkpoint taken while children are in-flight records each child at its own
  last committed step; on resume, completed children restore their `result`,
  in-flight ones resume from their last step. The parent re-enters
  `awaiting_children` and re-gathers. Children must therefore checkpoint
  independently (per-agent records, shared `step_seq`).
- **Tool side effects already applied (N2).** Resume re-enters *before* the next
  LLM call, never re-runs an already-recorded tool result. But a crash *during* a
  tool call is at-least-once: document that mutating tools should be idempotent,
  and record a tool-call "intent" record before execution so resume can detect
  "did this run?" Long-term: capability/intent ledger.
- **Config/model drift.** A checkpoint taken under model X resumed under model Y
  can be incoherent. Store a `config_fingerprint`; on mismatch, **warn and offer
  warm-restart instead of silent resume**.
- **Context-window growth.** Saved `messages` can be large; the checkpoint store
  references the same compaction output the loop already produces rather than
  duplicating raw history (ties into ADDITIONS §A3 context-lifecycle work).
- **Non-determinism.** Resume is *continuation*, not replay, so LLM
  non-determinism is fine; deterministic replay (Phase 4) is the part that needs
  recorded tool outputs + seeds.

## 7. Relationship to sandbox state
Agent-reasoning checkpoints (this spec) and **sandbox filesystem** checkpoints are
orthogonal. A complete "rewind to step N including files" needs both: this spec
for the loop, plus sandbox snapshot/restore (`docker commit` / firecracker
snapshot / a workdir overlay) tracked separately. Phase 1–3 here are useful on
their own (research/analysis goals are mostly reasoning-state); the sandbox piece
lands when the durable loop exists to hang it on.

## 8. Phasing

- **Phase 1 — linear single-agent crash-resume.** ✅ *Shipped.* `checkpoints`
  table (own table, no schema-version migration); checkpoint at the turn
  boundary in `Agent.run()`; depth-0 resume from the last committed step with
  restored budget; `[durable]` config knob (off by default, fail-open);
  `orchestrator` clears checkpoints on normal completion. See
  `maverick/checkpoint.py` + `tests/test_durable_checkpoint.py`.
- **Phase 2 — swarm tree.** Per-agent records + parent re-gather; rewind/fork.
- **Phase 3 — pluggable backend + sandbox-snapshot hook** (interface only).
- **Phase 4 — deterministic replay** (record tool outputs + seeds; `maverick
  replay <id>`), which also serves the audit-log + eval-harness work.

## 9. Test plan
- Kill a run mid-step (inject crash after step k via the existing `chaos` hook);
  resume; assert it continues from k+1 with budget preserved, not from 0.
- Rewind `--to-step N`; assert state matches the step-N checkpoint; `--fork`
  creates a child goal and leaves the original `done`/intact.
- Store-disabled and legacy-goal paths fall back to warm-restart unchanged
  (no behavior change when `[durable] enabled = false`).
- Config-drift fingerprint mismatch warns + offers warm-restart.
- Concurrency: crash during `spawn_swarm`; assert completed children aren't
  re-run and in-flight ones resume.

## 10. Open questions
1. Default `keep_last` for rewind history vs. DB growth on long runs?
2. Should checkpoints be **opt-out** (on by default) once Phase 1 is proven, given
   it's the headline wedge — or stay opt-in through 1.0?
3. Is a separate `~/.maverick/checkpoints.db` better than new tables in the main
   world-model DB (isolation vs. one-file simplicity)?
4. Do we expose rewind in the dashboard/REST now, or CLI-only until Phase 2?
