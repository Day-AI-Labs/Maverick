# Architecture: the governed agent runtime

Lightwork is a **governed agent runtime** — a recursive multi-agent swarm
wrapped in the runtime primitives most agent frameworks skip: hard budgets,
sandboxed execution, signed tamper-evident audit, attenuating capabilities,
and a content shield. The agent loop is the easy part; the governance around it
is the differentiator.

A useful lens for this architecture is the operating system. An OS multiplexes
processes onto hardware under scheduling, isolation, permissions, and resource
limits; Lightwork multiplexes *agents* onto LLMs and tools under the same kinds
of controls. The mapping below makes that lens concrete.

This is a **lens, not a brand.** "Agentic OS" / "Agent OS" became a saturated,
backlash-tainted marketing term across 2026, so Lightwork is *not* branded an
agentic operating system and does not claim to be one. The analogy is an
internal architectural North Star — a way to reason about which primitives the
runtime owns — and nothing more.

## OS primitives → Lightwork

Each row pairs a classic OS primitive with its agent analog and the Lightwork
module(s) that implement it. "In-process" / "opt-in" notes are deliberate; see
the next section for scope.

| OS primitive | Agent analog | Lightwork today (file) |
|---|---|---|
| Kernel / scheduler | dispatch and schedule agents | recursive swarm with shared context, per-call fan-out cap (`MAVERICK_MAX_SWARM_FANOUT`, default 8) and a total-spawn cap (`MAVERICK_MAX_TOTAL_SPAWNS`, default 64), parallel tool execution, plus a cron-style scheduler over a durable job queue (`swarm.py`, `tools/spawn.py`, `scheduler.py`, `job_queue.py`, `worker.py`) |
| Processes / isolation | agents + execution sandboxing | 7 sandbox backends behind one `build_sandbox()` factory and a uniform `.exec()` interface — local subprocess, Docker, Podman, devcontainer, Kubernetes, Firecracker, SSH (`sandbox/`) |
| Syscalls / drivers | tools, providers, channels | 286 built-in tool modules (`tools/`) — incl. 200+ token-authed REST/GraphQL connectors and 37 read-only primary-source data connectors — 12 LLM providers routable per role (`providers/`, `llm.py`), and MCP client over stdio **and** Streamable HTTP (`mcp_client.py`) |
| IPC | inter-agent communication | append-only blackboard, parent↔child spawn handoffs, and a peer message bus — **in-process today** (`blackboard.py`, `tools/spawn.py`, `agent_bus.py`) |
| Memory management | context = RAM, long-term = disk | turn-list compaction (drop/summarize, opt-in digest RAG), a model-curated cross-session memory directory, and per-goal KV memory (`compaction.py`, `tools/memory.py`, `tools/kv_memory.py`) |
| Permissions / capabilities | per-agent access control | tool allow/deny ACLs, per-identity risk ceilings, destructive-action consent gating, plus Ed25519-signable **attenuating** capabilities that can only narrow as they propagate to children (`safety/tool_acl.py`, `safety/tool_risk.py`, `safety/consent.py`, `capability.py`) |
| Filesystem / state | persistent state | persistent world model (SQLite + FTS5, or Postgres; schema v23) and durable single-agent checkpoints for crash-resume (`world_model.py`, `checkpoint.py`) |
| Package manager | installable units | community skills and MCP servers with validated install and **Ed25519 signed-publisher** verification (`skills.py`, `mcp_registry.py`) |
| Budgets / quotas | cost as a managed resource | a hard per-run `Budget.check()` (dollars / wall-clock / tokens) plus opt-in per-principal rolling-window quotas for chargeback (`budget.py`, `quotas.py`) |
| Audit / governance | tamper-evident log | append-only NDJSON with an Ed25519 Merkle-chained signature and offline `verify_chain`, plus GDPR Art.17 erasure (`audit/signing.py`, `audit/erase.py`) |
| Observability | tracing / metrics | opt-in OpenTelemetry spans + Prometheus `/metrics`, wrapping kernel turns, tool calls, and provider dispatches (`observability.py`) |
| Identity | users / agents as principals | OIDC ID-token verification mapping an SSO user to a `user:<sub>` principal that drops into the capability + tenant model; agents carry their own signed capability principals (`oidc.py`, `capability.py`) |

The cryptographic substrate is shared on purpose: the same Ed25519 primitives
sign the audit chain, signed skills, and capability grants, so per-agent
identity is a *reuse* of existing crypto rather than a from-scratch build.

## What's strong, what's deliberately scoped

**Strong.** The primitives a canonical academic agent kernel leaves unowned are
exactly where Lightwork is built out: a hard per-run budget the loop refuses to
exceed (`budget.py`), seven real execution sandboxes (`sandbox/`), tamper-evident
signed audit (`audit/signing.py`), and least-privilege attenuating capabilities
(`capability.py`). Tenancy is namespaced on disk by a context-scoped `tenant_id`
(`paths.py`), and content safety runs at three chokepoints via the shield (see
[safety.md](safety.md)).

**Deliberately scoped — being honest about the edges:**

- **IPC is in-process.** The blackboard, spawn handoffs, and the peer message
  bus are per-process, in-memory structures (`agent_bus.py` is explicit about
  this). Agents coordinate within a single runtime; there is no cross-host
  inter-agent message fabric.
- **Cross-process service supervision is a future increment.** The durable job
  queue and worker (`job_queue.py`, `worker.py`) run scheduled and background
  goals across process restarts, but Lightwork is not yet a long-lived
  supervisor of independent agent *services* (no per-agent process lifecycle,
  health-checked restart, or placement). The kernel runs a swarm per goal.
- **Durable checkpointing is single-agent (Phase 1).** Crash-resume covers a
  linear, non-spawning agent's loop state; resuming a full spawn tree is a
  later phase (`checkpoint.py`).
- **Tenancy is partial.** The cross-session memory store and audit signing keys
  are tenant-scoped; routing the rest of the world model through the same
  partition is an ongoing increment (`paths.py`).
- **Several governance primitives are opt-in and default-open.** Capability
  enforcement, per-principal quotas, OIDC, and OpenTelemetry are all off unless
  configured, so a single-user install behaves exactly as before. Enterprise
  mode flips the relevant defaults to fail-closed (see [safety.md](safety.md)).

The honest summary: Lightwork already implements more of the runtime primitive
set than a typical agent framework — strongest on budgets, sandboxing, signed
audit, and capabilities — while inter-agent IPC stays in-process and
cross-process service supervision remains ahead on the roadmap.
