# RFC 0001: Lightwork 2.0

- Status: **Draft — open for comment**
- Tracking: roadmap item "2.0 RFC" (2027-H2 Distribution)

## Why a 2.0

1.x grew by accretion: ~170 tools, 15 channels, 12 providers, three config
generations. Nothing is broken, but three kinds of debt now have a cost:

1. **Config drift** — knobs that mean almost the same thing live in different
   sections (`[tools] output_cache*` vs `[memory] backend` vs
   `[context] async_compaction`). New users read four sections to turn on one
   behavior.
2. **Sync/async split** — channels are `async` (base.py), tools are sync-first
   with async support bolted into the registry, the orchestrator bridges with
   `asyncio.to_thread`. Two execution models, one of them load-bearing by
   accident.
3. **Breadth tail** — the settled council decision (*freeze breadth, invest in
   depth*) re-homes the ~47-connector tail to the plugin/registry tier; 2.0 is
   when the in-tree tail actually moves.

## What 2.0 changes (proposed)

### C1. Config schema v2
- One `[cache]` section absorbs `output_cache*`, snapshot, and the Redis tier.
- `[memory]` keeps recall/vector-store only.
- Every rename lands in `maverick.migrate.REWRITES` (the table shipped empty
  in 1.x precisely so `maverick migrate --apply` is the upgrade path; backups
  + atomic writes already in place).

### C2. Async-only channel SDK (channel SDK v2)
- `Channel.send/send_threaded/start/stop` stay; the *handler* contract gains
  a structured reply object (text + attachments + thread ref) instead of bare
  `str`. The 14 in-tree adapters migrate in-tree; plugin adapters get a
  deprecation window (one minor release) via a shim that wraps `str` returns.

### C3. Connector re-homing
- The ~47 SaaS connectors move from `tools/` to a `maverick-connectors`
  distribution installed by the wizard on demand. The registry's deferred
  loading already hides them from the prompt; 2.0 moves the *code*.
- In-tree stays: fs/shell/browser/sql/compute + the safety-relevant tools.

### C4. Tool contract
- `Tool.fn` officially supports the streaming contract (generator/async
  generator chunks — shipped in 1.x as `set_chunk_listener`) and documents
  `parallel_safe` as part of the public plugin API (it already gates caching,
  parallelism, and speculation).

## What 2.0 does NOT change

- The world-model schema (versioned migrations already handle evolution).
- The shield chokepoints, budget caps, sandbox mediation (CLAUDE.md rules).
- The MCP surface — it is the cross-language contract and stays stable.

## Migration story

`maverick migrate` (shipped) carries every mechanical rename; advisories
cover the judgment calls. A 1.x config must run unmodified under 2.0 with at
most WARN-level notices for one minor release before any removal.

## Open questions

1. Does the connector re-homing split PyPI packages per family
   (`maverick-connectors-crm`) or ship one distribution?
2. Is the structured channel reply object worth the plugin-adapter churn, or
   should it be opt-in capability negotiation?
3. Timing relative to the Plugin API v2 rollout (RFC 0002) — one breaking
   window or two?

Comment by PR on this file.
