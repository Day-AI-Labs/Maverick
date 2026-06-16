# Maverick — Fix Backlog (status board)

> Compiled from a full read-through of the codebase (June 2026). Prioritized for
> two goals: (1) survive technical/security/commercial diligence, (2) convert the
> asset into a fundable/sellable business.
>
> **Legend:** `[x]` done · `[~]` partially done · `[ ]` open.
> **Tags:** `(needs you)` = founder/external act, not code · `(needs key)` =
> requires a provider API key to produce real numbers (never fabricated) ·
> `(open eng)` = a real engineering decision/refactor, deliberately NOT done
> unilaterally (wire-vs-cut and large refactors need a call, not a guess).

## P0 — Correctness & credibility (the cheap diligence-protecting fixes)

- [x] **README schema `v10` → actual `v16`** — fixed in README, `docs/architecture.md`, `docs/specs/durable-execution.md`.
- [x] **Postgres world-model backend now documented** — added to the README repo-layout + architecture lines (was omitted entirely).
- [x] **Pack count reconciled to the true `1,118`** (not `1,019`) across README, FEATURES, CLAUDE.md, press-kit, comparison, index, getting-started, CHANGELOG, and the proposal/research docs. `domains-lint` confirms **1,118 packs, 0 errors, 0 warnings**.
- [x] **channels `__init__.py` docstring** rewritten — 18 wired adapters listed, `whatsapp`/`sms` no longer mislabeled "scaffold".
- [ ] **`benchmarks/RESULTS.md` with real multi-seed numbers** — `(needs key)`. The harnesses exist and run; producing the actual pass@1 numbers requires a provider key. I will NOT fabricate them.
- [~] **Sweep FEATURES.md / AGENTS.md for stale refs** — the schema-version + pack-count refs are fixed; the remaining "sweep" is open-ended (FEATURES `schema v14 domain column` is correct *history*, left as-is).

## P1 — Security & legal (would fail a security review or a buyer's lawyers)

- [~] **Postgres backend stores content PLAINTEXT** while SQLite seals at rest — **the security contradiction is now closed (fail-closed):** `open_world` raises `PostgresAtRestUnsupported` when encryption-at-rest is enabled with the Postgres backend, so regulated/encrypted data can never silently land as plaintext in PG (documented in `docs/encryption.md`; tested in `test_postgres_at_rest_gate.py`). **Follow-up `(open eng)`:** actually *seal* the PG columns so encrypted deployments can use Postgres — a ~16-method change that must mirror SQLite's per-method read-modify-write (e.g. `reclaim_orphan_goals` can't raw-SQL-concat a sealed `result`); needs a PG-equipped env to verify.
- [ ] **In-tree consumer-chat session-providers (ToS risk)** — `(needs you)` product/legal decision: isolate into a separate optional package, harden the gate, or remove. A buyer's counsel will flag it.
- [ ] **Generated-tool `fn` runs in-process at runtime** — `(open eng)` hardening (out-of-process tool runtime); only registration is currently sandboxed.
- [x] **`self_edit` stays unregistered-by-default** — confirmed (`tools/__init__.py:1194` "self_edit intentionally is not registered"), documented in code.
- [ ] **Unsigned installers** (Tauri / MSI) — `(needs you)` code-signing certs (external).

## P2 — Half-built / unwired — `(open eng)`, each a WIRE / CUT / "experimental" call

> These are deliberately **not** done unilaterally — deleting working modules or
> doing the large compaction refactor are judgment calls that need a decision
> (and risk breaking things), not an autonomous guess.

- [ ] `vision_click.py` + `computer_calibration.py` — built, wired into nothing.
- [ ] `prompt_dsl.py` — no live caller.
- [ ] Domain-pack `[[workflow]]` playbooks — parsed/linted/rendered, used by zero packs.
- [ ] Compaction RAG `DigestIndex` — built, not wired.
- [ ] `pgvector` knowledge store — `raise NotImplementedError`.
- [ ] `migrate.py` rewrite engine — `REWRITES = []`.
- [ ] `schema-plan` migration gate — exists, not wired into CI.
- [ ] `training/` RL pipeline — interfaces only; don't overclaim "learning".
- [ ] Consolidate: two budget tuners · four compaction mechanisms / two vocabularies · two `FederationError` classes · `multi_monitor` naming. (Renames/merges touch imports → need a deliberate pass, not a drive-by.)

## P3 — Focus & product debt — `(needs you)` strategic decisions

- [ ] **26 suites / 1,118 packs, zero customers = breadth without validation.** Pick 1–2 wedge verticals (BFSI/finance, tax-prep) and go deep. Founder call.
- [ ] **Open-source "lite edition" decision** — gates the whole distribution motion.
- [ ] Live-service validation gaps (IRC / G2 / LangChain / Redis broker / arq worker) — need real infra to exercise.

## P4 — Productionization for a sale or raise — `(needs you)` except the one code item

- [ ] **2–3 design-partner LOIs / pilots** — `(needs you)`. The single biggest valuation lever.
- [ ] **SOC 2 Type I** — `(needs you)`, external attestation (readiness + evidence collector already exist).
- [ ] **Third-party pen test** — `(needs you)`, external engagement.
- [x] **Dashboard `@app.on_event` → lifespan** — already migrated (`app.py:199` lifespan handler; only a docstring mention of the old name remains). CSP `'unsafe-inline'` nonce migration is the remaining `(open eng)` half.
- [ ] **Multi-tenant hosting story** — `(needs you)` operate-vs-self-host decision (Postgres tenancy + queue dispatch are wired but never run at scale).

---

### Summary
**Done now (this PR):** every P0 item that is code/docs (schema version, Postgres
documentation, the 1,118 pack-count reconciliation, the channels docstring) plus
the two already-satisfied items (`self_edit`, dashboard lifespan).

**Not done, and why:** `RESULTS.md` needs a provider key (no fabricated numbers);
P1/P2 are real engineering decisions (seal-PG, session-provider disposition,
wire-vs-cut, the consolidation refactors) that need a call rather than an
autonomous guess; P3/P4 are founder/external acts (design partners, SOC 2, pen
test, signing certs, the OSS-edition and wedge decisions). The highest-value
remaining items are **not code** — they're traction and validation.
