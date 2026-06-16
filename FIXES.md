# Maverick — Fix Backlog

> Compiled from a full read-through of the codebase (June 2026). Prioritized for
> two goals: (1) survive technical/security/commercial diligence, (2) convert the
> asset into a fundable/sellable business. P0 = cheap + high-trust-impact, do first.

## P0 — Correctness & credibility (cheap, fixes false claims a diligence team will catch)

- [ ] **README says world-model schema `v10`; actual is `v15`** (`world_model.py:28` vs `README.md:130`). Update.
- [ ] **README/architecture omit the Postgres world-model backend entirely** — it exists (`world_model_backends/postgres.py`, ~1570 lines, with tenant RLS). Document it.
- [ ] **"1,019 packs across 26 suites" vs 1,118 TOMLs on disk.** Reconcile the headline number everywhere it appears (README, FEATURES, marketing). Pick the real, defensible count.
- [ ] **channels `__init__.py` docstring still says "10 channels / whatsapp+sms scaffold"** — 20 adapters are actually built. Update (`maverick_channels/__init__.py:9-20`).
- [ ] **Produce a real `benchmarks/RESULTS.md`** with multi-seed numbers. Today the harnesses are honest "run it yourself" — a buyer/investor wants the numbers, not the harness.
- [ ] Sweep `docs/FEATURES.md` + `AGENTS.md` for stale module-name references (rule: a rename must update FEATURES.md).

## P1 — Security & legal (would fail a security review or a buyer's lawyers)

- [ ] **Postgres backend stores content PLAINTEXT** while SQLite seals sensitive columns at rest (`crypto_at_rest`). This directly contradicts the "regulated / self-host / encryption-at-rest" positioning. Either seal PG columns or document the asymmetry loudly and gate the regulated profile to SQLite.
- [ ] **Session-providers (consumer-chat cookie scraping: ChatGPT/Claude/Gemini/Grok/Kimi) ship in-tree.** This replays login cookies against private web-UI endpoints — explicit ToS violation + account-ban risk. An enterprise buyer's counsel will flag it. Decide: isolate behind a separate optional package, harden the gate, or remove. Right now it's a liability attached to the core repo.
- [ ] **Generated-tool `fn` runs in-process at runtime** (only registration is sandboxed via AST audit + out-of-host import check). Documented as future hardening — make it real before claiming "self-improving in production."
- [ ] Confirm `self_edit` stays unregistered-by-default (it is) and document why.
- [ ] **Unsigned installers** (Tauri `.dmg`/`.exe`/`.AppImage`, MSI). Get code-signing certs before any real distribution; "unknown developer" prompts kill enterprise trust.

## P2 — Half-built / unwired (decide per item: WIRE, CUT, or label "experimental")

Built-and-tested but referenced by nothing in the live path — reads as "unfocused effort" in diligence:
- [ ] `vision_click.py` + `computer_calibration.py` — production-quality, wired into nothing. Wire into the computer-use path or delete.
- [ ] `prompt_dsl.py` (cache-aware prompt builder) — no live caller; `agent.py` still string-concats the system prompt. Wire or delete.
- [ ] Domain-pack `[[workflow]]` playbooks — parsed/linted/rendered, but **zero** of 1,118 packs use them. Author a few exemplars or remove the surface.
- [ ] Compaction RAG `DigestIndex` (`compaction.py`) — built, not wired into the loop.
- [ ] `pgvector` knowledge store (`maverick_knowledge/store.py`) — `raise NotImplementedError`. The only real store is brute-force cosine in SQLite (won't scale).
- [ ] `migrate.py` rewrite engine — `REWRITES = []` (dead until 2.0 renames land).
- [ ] `schema-plan` online/offline migration gate — exists, **not wired into CI**.
- [ ] `training/` RL pipeline — interfaces + lazy-torch; uses a structural stand-in for operator-side text. Not real learning yet; don't overclaim.

Consolidate (footguns):
- [ ] **Two parallel budget tuners** (`budget_tuner.py` advisory vs `self_tuning_budget.py` online; only the latter is wired, divergent constants). Merge or clearly delineate.
- [ ] **Four overlapping compaction selection mechanisms with two disjoint strategy vocabularies** (`compaction_plugins` heuristic/learned/multimodal/streaming/graph vs `compaction_hybrid` truncate/structural/retrieval/summarize), plus two dispatchers. Unify or document the map — this will bite the next contributor.
- [ ] Two unrelated `FederationError` classes / two federation systems (gRPC goal-delegation vs signed-envelope channel/marketplace). Rename for clarity.
- [ ] `multi_monitor.py` is display geometry, not monitoring — rename to avoid confusion.

## P3 — Focus & product debt (the strategic risk)

- [ ] **26 suites / 1,118 packs with zero customers = breadth without validation.** Pick 1–2 wedge verticals (BFSI/finance is the obvious one — it leads governance spend; tax-prep is unusually complete) and go deep with design partners. The long tail reads as unfocused until something is validated in production.
- [ ] **Resolve the open-source "lite edition" decision.** It gates the whole distribution/community motion (and the HF-spotlight item that's currently licensing-blocked).
- [ ] Live-service validation gaps from ROADMAP (IRC server, Even G2 device, a real LangChain install, a Redis broker, the arq worker pool) — protocol-tested but never run against live infra.

## P4 — Productionization for a sale or raise (the value unlocks)

- [ ] **Get 2–3 design-partner LOIs / pilots.** Single biggest valuation lever — moves it from "asset" to "business" tier (see valuation notes).
- [ ] **Start SOC 2 Type I.** Readiness doc + `maverick.soc2` evidence collector exist; the attestation itself is external and is table-stakes for the regulated-enterprise buyer.
- [ ] **Commission a third-party pen test** (readiness/scope doc exists; the engagement doesn't).
- [ ] Dashboard: finish the `@app.on_event` → lifespan migration (one residual); retire CSP `'unsafe-inline'` (nonce migration).
- [ ] Decide the multi-tenant hosting story you actually want to operate vs. ship as self-host-only (Postgres tenancy + queue dispatch are wired but never run at scale).
