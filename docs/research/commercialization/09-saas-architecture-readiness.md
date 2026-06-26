# 09 — SaaS Architecture Readiness: Adversarial Teardown

> **Status (June 2026):** counts and plans in this document are historical. The shipped catalog is 2,020 lint-clean agents across 53 suites with a full learning lifecycle — see [`docs/FEATURES.md`](../../FEATURES.md).
>
> **Substrate status — superseded by a code-level re-audit.** This teardown's
> three "structural facts" (no data-plane tenant boundary, controls fail-open,
> single-process isolation) described `main` at the time of writing. A
> file-by-file re-audit since then found the multi-tenant substrate *largely
> built and shipping*: a tenant-aware Postgres backend with fail-closed RLS
> (`world_model_backends/postgres.py`, `pg_rls.py`), per-tenant world-DB isolation
> + KMS/DEK flooring (`tenant/kms.py`), a unified enterprise/REGULATED profile
> that flips the controls **closed** (`deployment.py`, `secure_by_default()`), and
> an out-of-process dispatcher seam (arq + gRPC). The remaining opt-in gaps —
> enterprise-default RLS, session revocation, a secrets-vault seam, a SIEM
> forwarder, residency pinning, budget/cap coordination, gRPC dispatcher startup
> wiring — have since landed, **as have the three formerly-"large" items**:
> per-tenant KMS at fleet scale (BYOK + DEK-cache TTL + a resumable
> `maverick tenant kms-rotate`), Alembic-grade migration governance (a
> checksum-locked CI gate), and a proven control/data-plane split (an
> out-of-process e2e harness + a concurrency soak asserting zero-loss /
> exactly-once, both CI-gated). All of it was then **adversarially hardened**
> (11 verified bugs fixed, incl. a fail-open revocation store and a residency
> bypass), and SCIM deprovision was extended to revoke pairwise-`sub` (Entra)
> sessions. SAML SSO (pysaml2) and SCIM also ship. See
> [`docs/research/lightwork-purchase-blockers.md`](../lightwork-purchase-blockers.md)
> (resolution summary). Read the teardown below as the *original cold-water
> analysis*, not the current state.


> Teardown for the pivot from a **local, single-user kernel** to a **multi-tenant
> hosted control plane for agent governance** (vs. OneTrust). Method: full read
> of the data, isolation, consent, capability, secrets, and auth layers on
> `main`. Every claim is file-cited. Companion to
> `regulated-deployment-and-compliance-platform.md`, which is *optimistic*; this
> doc is the cold-water counterweight.

## Bottom line

Lightwork's governance *primitives* (signed audit, attenuating capabilities,
consent ledger, PII/secret redaction) are genuinely strong and reusable. But the
**runtime substrate underneath them was designed for exactly one trust domain:
one user, one machine, one process, fail-open by default.** Three structural
facts make it unfit to become a multi-tenant governance SaaS *as-is*:

1. **There is no tenant boundary in the data plane.** The tenancy primitive
   (`paths.py`) is wired into *one* consumer — the memory tool. The world model,
   the audit log, the consent ledger, and the Postgres backend are all
   tenant-blind. A hosted deployment would pool every customer's goals,
   conversations, facts, and audit chain into one shared SQLite file or one
   un-partitioned Postgres schema.
2. **Every safety control defaults OPEN.** Shield fail-open, consent
   `auto-approve`, capabilities `enforce=off`, tenancy `off`. Correct for a
   laptop; catastrophic for a product whose entire value proposition is *"we
   enforce governance."* A governance vendor that ships fail-open ships a
   liability.
3. **The execution + isolation model is a single process with a
   `BoundedSemaphore`.** That is a concurrency throttle, not an isolation or
   scaling boundary. One tenant's runaway goal degrades all tenants; one
   poisoned `world.db` corrupts all tenants.

This is a **6–9 month re-platforming of the substrate**, not a feature sprint.
The brain survives; the spine, skin, and locks do not.

## Won't survive contact with multi-tenant SaaS (with file pointers)

- **SQLite single-file world model** — `world_model.py:24`
  (`DEFAULT_DB = ~/.maverick/world.db`), opened unconditionally by the background
  runner at `runner.py:85-86` (`open_world(DEFAULT_DB)`) and the channel server
  at `server.py:32,338`. WAL + `busy_timeout` + a process-global `RLock`
  (`world_model.py:382-516`) make the design **explicitly single-writer**: the
  docstring (`world_model.py:5-8`) sells "one writer process + many readers."
  Under SaaS write concurrency this is a hard ceiling — `_writing()` serializes
  *every* mutation across *every* tenant through one lock on one connection. FTS5
  triggers (`world_model.py:177-193`) add write amplification on the same hot
  path. A single file also means a single blast radius: corruption, a `VACUUM`
  stall, or a poisoned row is a whole-fleet outage.
- **Postgres backend is a thin port, not a tenant-ready backend** —
  `world_model_backends/postgres.py`. Real gaps: (a) **no `tenant_id` column on a
  single table** in `SCHEMA` (`postgres.py:46-183`) — zero row-level isolation;
  (b) **one long-lived connection serialized by an `RLock`**
  (`postgres.py:221-260`) — it inherits SQLite's single-writer bottleneck
  *without* SQLite's excuse; no pool, no `psycopg_pool`; (c) schema is a flat
  constant `_PG_SCHEMA_VERSION = 9` (`postgres.py:41`) applied idempotently with
  **no migration framework** — irreconcilable with a versioned, customer-facing
  DB; (d) the docstring itself (`postgres.py:18-23`) admits it only covers
  "hot-path methods" and defers the rest. This is a prototype.
- **Single-process `BoundedSemaphore` runner** — `runner.py:32-33`
  (`MAX_CONCURRENT_GOALS`, `threading.BoundedSemaphore`). Goals run as **threads
  in the API process** (`run_goal_in_thread`), sharing one Python GIL, one
  filesystem, one set of env vars, one `~/.maverick`. There is **no per-tenant
  quota, no isolation, no fairness** — `runner.py:146-150` even flags "reserved
  for future change to a proper task queue (Celery/arq/RQ)," which is an
  admission that the real thing doesn't exist. A noisy/abusive tenant starves the
  3-slot semaphore and blocks everyone (`runner.py:39`, 300s acquire timeout →
  refuse). Budget is **per-run only** (`runner.py:92-99`); there is no aggregate
  per-tenant spend cap, so a hosted tenant can run unlimited concurrent goals.
- **Tenancy that routes nothing load-bearing** — `paths.py` is well-built but
  consumed in exactly **one** place: `grep` for `data_dir(` finds only
  `tools/memory.py:40-41`. The world model (`world_model.py:24`), audit
  (`writer.py:25`), and consent ledger (`consent.py:37`) all hardcode
  `Path.home()/".maverick"/...` and never call `current_tenant()`. Worse,
  `server.py` opens the conversation and goal **outside** the `tenant_scope`
  block (`server.py:81-88` vs. the `with tenant_scope(...)` at lines 95-102) — so
  even the memory routing leaks goal/turn rows into the shared store. The
  module's own docstring concedes "the world model and audit log are migrated in
  follow-on increments" (`paths.py:18-21`). **Those increments are the product.**
- **Secrets at rest in plaintext** — provider API keys live in `~/.maverick/.env`
  protected only by chmod 600 (`health.py:81,99`), interpolated into config
  via `${VAR}`
  (`config.py:61-67`). `secrets.py` is a log *scrubber*, not a vault — there is
  **no envelope encryption, no per-tenant DEK, no KMS**. In a hosted model one
  process holds every tenant's keys in its environment.
- **Dashboard auth is a single shared static bearer** — `app.py:291-329`
  (`bearer_auth`). One process-wide `MAVERICK_DASHBOARD_TOKEN`,
  `hmac.compare_digest`'d. **No users, no per-tenant tokens, no rotation, no
  sessions, no RBAC, no SSO/OIDC.** Loopback callers are served with **no token
  at all** (`app.py:296-316`), gated only by a same-origin CSRF check. This is a
  laptop trust model; there is literally no principal to scope a tenant to.

## Defaults that MUST flip to fail-closed

A governance product is secure-by-default or it is not a governance product. Each
row is a config knob today; the hosted control plane must invert the default (and
ideally forbid the open value for tenant traffic).

| # | Control | Current default | File:line | Must become (hosted) |
|---|---|---|---|---|
| 1 | Consent mode | `auto-approve` (silent grant) | `consent.py:63` | `dashboard`/`ask`; high-risk → **deny-by-default** |
| 2 | Capability enforcement | off (no-op grant) | `capability.py:146-159` | **on**; unconfigured principal = empty grant, not all-tools |
| 3 | Tenancy isolation | off (shared `~/.maverick`) | `paths.py:97-111` | **on, mandatory**; no-tenant request rejected |
| 4 | Shield | fail-**open** on error/missing | `guard.py:14`, `215,226,260` | fail-**closed** for governed traffic; SDK required, not optional |
| 5 | Audit signing | off | `writer.py:74-92` | **on**; refuse to start if `cryptography` missing |
| 6 | Dashboard token | none → loopback served unauthenticated | `app.py:296-316` | always require identity; no anonymous loopback path in prod |
| 7 | World-model DB perms | best-effort chmod, swallow `OSError` | `world_model.py:365-397` | hard-fail if perms/owner wrong |
| 8 | Tool ACL allow-list | empty == **all tools** | `capability.py:33-34`, `tool_acl.py:54-56` | empty == **none**; explicit allow only |
| 9 | Orphan reclaim / cross-process writes | tolerated, best-effort | `world_model.py:550-587` | per-tenant DB/RLS makes cross-process writes impossible by construction |
| 10 | Dashboard `?token=` removed but loopback CSRF-only | mixed | `app.py:302-316` | uniform authn on every route; no exempt mutating paths |

The deeper problem: these are **independent toggles**. There is no single
"hosted/secure" profile that flips all of them atomically, and several
(`consent`, `tenancy`, `capabilities`) read config lazily and **fail to OFF on
any exception** (`capability.py:158-159`, `paths.py:110-111`) — so a malformed
config silently disables enforcement. For a governance product that is
exactly backwards: a config error must fail **closed**.

## Target architecture (control plane vs. data plane)

- **Tenancy model.** Pick one and enforce it in the database, not in Python.
  Default recommendation: **Postgres with Row-Level Security**, a mandatory
  `tenant_id` on every table, and `SET app.tenant_id` per transaction so a
  missing/forged tenant returns *zero rows* by construction. Largest/regulated
  tenants get **per-tenant databases** (true blast-radius isolation, per-tenant
  encryption, per-tenant residency). The current "one file / one schema / one
  RLock" must be retired for tenant traffic; SQLite stays as the OSS/local
  single-tenant backend only.
- **Control plane vs. data plane split.** Today they are the same FastAPI
  process (`app.py` serves UI, REST, *and* runs goals as threads via
  `runner.py`). Split into: a **control plane** (auth, tenant/identity, policy,
  audit query, quotas — stateless, horizontally scalable) and a **data plane**
  (goal execution workers behind a real queue — Celery/arq/Temporal — with
  per-tenant concurrency + spend quotas replacing the global semaphore). Workers
  must run in **isolated sandboxes per run** (Lightwork already has the sandbox
  abstraction — `sandbox/`), never as threads sharing one host's filesystem/env.
- **Identity + authz.** Replace the shared bearer with **SSO/OIDC + per-tenant
  RBAC**, mapping a federated principal onto `Capability.principal` and the
  tenant id (the doc's `identity/` module). Every request carries a verified
  tenant; the no-token loopback path (`app.py:296-316`) is removed in prod.
- **Per-tenant keys / KMS.** Envelope encryption with a per-tenant DEK wrapped by
  a KMS-held KEK; provider keys move out of a shared `.env` into a per-tenant
  secret store. `world.db`/Postgres data and audit NDJSON encrypted at rest.
- **Audit becomes tenant-scoped + externally anchored.** The signed chain
  (`signing.py`) is excellent, but per-tenant chains with **externally-held
  pubkeys** (the writer already warns a co-located key only catches accidental
  edits — `writer.py:103-108`) plus WORM export (S3 Object-Lock) and SIEM
  shipping. Audit dir routing must go through `data_dir()` like everything else.
- **Network egress controls.** Multi-tenant agents executing tool calls need
  per-tenant egress allow-lists / proxying so one tenant's agent can't reach
  another tenant's resources or exfiltrate. Today sandboxes support
  `--network=none` but there is no per-tenant policy plane above them.

## What would kill us

These are the findings an enterprise pen-test / security review would surface and
that would lose the deal:

1. **Cross-tenant data leakage — the #1 finding.** With no `tenant_id` in the
   world model or Postgres schema and `data_dir()` unwired
   (`world_model.py:24`, `postgres.py:46-183`, `server.py:81-88`), a single
   IDOR/missing-filter bug exposes *every* tenant's conversations, facts, goals,
   and **audit trail**. For a compliance product, leaking the audit log is fatal
   — it's the evidence you sell.
2. **Fail-open governance is a control failure by definition.** Shield, consent,
   and capabilities all default open and fail open on error
   (`guard.py:215,226`; `consent.py:163-170`; `capability.py:158-159`). A pen-test
   that disables the SDK, malforms config, or throws inside a scanner watches the
   agent execute ungoverned. "Our safety layer fails open" is an automatic finding
   in any SOC 2 / governance audit.
3. **Shared static bearer + unauthenticated loopback.** One token for the whole
   surface, no rotation, no per-tenant scope, and a loopback bypass
   (`app.py:296-316`). In any shared-host or proxy-misconfig scenario this is
   full unauthenticated control-plane access (cancel goals, arm killswitch,
   disable safety tools, read all spend).
4. **Plaintext secrets, single process.** Every tenant's provider keys in one
   process env / one chmod-600 `.env`. One RCE or one
   verbose log (pre-scrub) and it's a multi-tenant key compromise.
5. **No isolation between tenant executions.** Threads in one process sharing GIL,
   FS, env, and one `world.db` (`runner.py:32-136`). No resource fairness, no
   per-tenant quota (`Budget` is per-run, `runner.py:92-99`), no blast-radius
   containment. A poisoned-DB or resource-exhaustion attack is fleet-wide.
6. **No migration story for the hosted DB.** The Postgres backend has a flat
   schema constant and idempotent `CREATE IF NOT EXISTS`
   (`postgres.py:41,262-265`) — no Alembic, no versioned migrations. The first
   schema change against live customer data has no safe path.
7. **Best-effort everything swallows failures.** The codebase pervasively
   `except OSError: pass` on permission hardening (`world_model.py:366-397`,
   `consent.py:80-85`, `writer.py:128-149`). Defensible locally; in a hosted
   governance product, **silently failing to lock down data is itself the
   breach.**

**Net:** the governance *logic* is a real asset and largely portable. The
*substrate it runs on* — single-file DB, single-process runner, fail-open
defaults, shared-token auth, plaintext secrets, unwired tenancy — was correct for
a local kernel and must be re-architected before a single paying multi-tenant
customer touches it. Treat this as the gating, multi-quarter platform investment;
shipping the brain on this spine is how the enterprise pen-test sinks the launch.
