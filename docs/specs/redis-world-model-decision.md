# Decision: no Redis primary world-model backend

**Status:** Decided — decline the primary-store backend; the Redis layers
that fit shipped instead · **Roadmap ref:** 2027-H2 Ecosystem "Redis
world-model" · **Date:** June 2026 · **Precedent:** the DuckDB
transactional-backend decision (declined; analytics layer shipped).

## Question

Should the world model (goals / episodes / turns / conversations / facts /
approvals) support Redis as a primary storage backend, alongside SQLite
(default) and Postgres (shared/hosted)?

## Decision

**No.** The world model is relational and transactional by design:

- **Cross-structure transactions.** Goal cascades (the Art. 17 erase path,
  orphan reclaim, episode lifecycle) rely on multi-table transactions with
  deferred FK checks. Redis offers per-command atomicity and MULTI/EXEC
  batches, not relational integrity; every FK/cascade would be re-implemented
  application-side — precisely the bug surface SQLite/Postgres remove.
- **Query surface.** The dashboard/API/CLI query by joins, ranges, and FTS5
  full-text search. On Redis each becomes a bespoke secondary-index scheme
  maintained by hand, with its own consistency bugs.
- **The deployment need is already covered.** Single box: SQLite + WAL
  (16-writer contention audited in CI). Shared/hosted: the Postgres backend
  (tenant-stamped, migration-ledgered). There is no deployment gap a Redis
  primary store would fill.

## What Redis is actually for here — shipped

The places where Redis's model genuinely fits are already in the tree:

- **Cross-host tool-output cache** — `redis_tool_cache.py`
  (`[tools] output_cache_backend = "redis"`), fail-open.
- **Queue broker** — the arq `QueueDispatcher` (`[queue]`) for out-of-process
  goal execution.

## Revisit trigger

A deployment profile where neither SQLite nor Postgres can serve the world
model (e.g. a mandated Redis-only data plane). None is known; none is
anticipated for a self-hosted enterprise product.
