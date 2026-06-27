# Punchlist Resolution

> Companion to `CODE_QUALITY_AUDIT.md`. Records the disposition of **every**
> punchlist item: ✅ done, 🔵 deferred (needs a decision), or 📋 scoped follow-up
> (a real plan, not a blind refactor). Prepared 2026-06-27.

Every code change below was verified in context, lint-clean, and test-covered
where behavior changed. Items that were **not** changed are listed with the
reason — including verified false positives, deliberately-tested designs, and
work too large/risky to do autonomously without review or live infrastructure.

---

## Status at a glance

| Tier | Scope | Status | PR(s) |
|---|---|---|---|
| 0 | Meeting hygiene (ruff, internal numbers, 2 overstated claims) | ✅ done | #1977 (merged) |
| 1 | Remaining product-code medium bugs (~22 fixed) | ✅ done | #1978 (merged), #1979 |
| 4 | Generated-scaffold hardening | ✅ done | #1980 |
| 2 | Deferred / decision items | 🔵 decisions recorded below | — |
| 3 | God-module decomposition | 📋 plan below | — |
| 4 (rest) | Pricing provider, failure-policy, Protocol types | 📋 plan below | — |
| 5 | This doc + stress-test refresh | ✅ / 📋 | — |

Plus the earlier audit + fixes already merged: #1973 (audit + 8 confirmed-high),
#1974, #1975 (mediums), #1976 (pitch-deck number reconciliation).

---

## ✅ Done

### Tier 0 (#1977)
- Fixed the live `ruff check .` drift (6 `I001` errors) — repo-wide gate green again.
- Reconciled `CLAUDE.md` + `docs/user-stories.md` "1,902 packs / 52 suites" → **2,020 / 53**.
- Dropped the fabricated "1,000,000 iterations" fault-injection figure (real loops are 1–5,000).
- Scoped the README egress-lock claim to the application layer (shell egress needs a network firewall).

### Tier 1 (#1978 merged, #1979)
Security / correctness: qdrant cross-tenant read scoping (+test), capability-revocation
"only-via" fixpoint (+tests), consent-ergonomics token matching, snowflake `SNOWFLAKE_TOKEN_TYPE`,
gdrive random multipart boundary, A2A streaming exception scrub (in #1974), grpc trust-plane
logging, marketplace_ratings real `content` hashing.
Reliability / honesty: finance/status tri-state probes, training/ingest pagination + logging,
home_assistant `hours` window, geofence docstring, plugin_isolation timeout doc/warn,
automation/make pagination, cli `cost --model` honest error, compaction/streaming fingerprint,
installer wizard skipped-validation marker, desktop tauri `DASHBOARD_PORT`, agent_adapter +
redis_tool honesty docstrings.

### Tier 4 — generated scaffolds (#1980)
- `test_gen` scaffold `pytest.skip()`s until the invariant is filled (no false-pass coverage).
- `plugin_scaffold` tool stub raises instead of returning a fake greeting.
- `html_to_app` form handler alerts "not connected to a backend" instead of silently dropping data.

### Verified false positives / already-correct (no change, by design)
- `tools/database_tool` "engine never disposed" — it **does** dispose in a `finally`.
- `marketplace/moderation` "gauntlet not wired" — it **is** run on every federated listing import (`federation.py:300`).
- `self_learning` in-process tool — already discloses "runs IN-PROCESS at runtime."
- `vulture` "not installed" — it **is** in `.devcontainer/post-create.sh` (`>=2.11`).
- tgi / openai_compatible placeholder model ids — honestly documented; self-hosted prices at $0.

---

## 🔵 Tier 2 — deferred, needs a decision

These are real but require a maintainer/founder call or live infrastructure; doing
them blind would be worse than flagging them.

1. **`tools/containment_mode` fail-open on unknown actions.** Currently a *deliberate,
   explicitly-tested* design (`test_unknown_action_fails_open`). For a containment tool,
   fail-**closed** at the `full` level is the safer default. **Decision needed:** flip
   `full` (and maybe `network`) to deny unknown actions, or keep + document. *Recommendation:*
   fail-closed at `full`, update the test. ~15-line change once decided.

2. **`tools/office_convert` reports `wrote {dst}` on an unverified path.** A correct
   verify needs **sandbox-type awareness** — the host can't `stat` a container/e2b path, so a
   naïve `dst.exists()` would regress the common container case with false "couldn't confirm"
   warnings. *Plan:* add an `is_host_visible()` capability to the sandbox protocol; verify only
   for local/host-visible sandboxes; otherwise report "submitted to sandbox".

3. **Memory-guard finding #6 to completion (Postgres `facts.trust_tier`).** #1974 made the guard
   read real tiers from `fact_history` when temporal memory is on. Closing the non-temporal
   fallback needs a **governed schema migration** (new `MIGRATIONS` entry + `_PG_SCHEMA_VERSION`
   bump + matching SQLite head + `migrations.lock.json` regen via `migration_governance --regen`)
   validated against a live Postgres. *Plan:* add `trust_tier SMALLINT DEFAULT 3` to `facts`,
   persist it in `upsert_fact`, read it in `get_facts_with_trust`; regen the lock; test on PG.

4. **Compaction-hybrid wiring (finding #8).** The picker is implemented + tested but not in the
   live path, and its strategy vocabulary (`truncate/structural/retrieval/summarize`) must first
   be reconciled with `compaction.strategies` before wiring `pick_strategy` behind `[compaction]
   hybrid`. *Plan:* align the vocab, add one caller in `compaction.plugins.compact_with`, add a
   behavioral test that flipping the flag changes strategy selection.

---

## 📋 Tier 3 — god-module decomposition (engineering roadmap)

This is real maintainability debt (Codex's audit; the line counts are accurate) but **not
slop** and **not** an autonomous-burst task — each is a multi-PR, behavior-preserving refactor
that needs the full agent loop / app to validate (the API key isn't available here). Concrete,
low-risk-first plan:

| Target | Now | Decompose into | First safe step |
|---|---|---|---|
| `agent.py::_run_inner` | 1,092 lines | TurnLoop · PromptBuilder · CheckpointManager · ToolExecutionPipeline · SafetyGate · FinalAnswerExtractor | Extract `PromptBuilder` (pure, easy to unit-test) behind the existing call site |
| `orchestrator.py::run_goal` | 738 lines | GoalLoad · GovernancePreflight · McpLifecycle · SwarmRunner · ResultRenderer · Cleanup | Extract `GoalResultRenderer` (the tail formatting) — no control-flow risk |
| `dashboard/app.py` | ~5,000 lines | `app_factory` + `routers/*` + `services/*` | Move health/metrics endpoints to `routers/health.py` first |
| `installer/wizard.py` | ~4,000 lines | typed `WizardStep` registry + per-section modules + declarative TOML render | Add golden-file tests for current config output, then extract one section |
| `tools/__init__.py::base_registry` | 700 lines | per-tool manifests with `risk/network/tenant/audit` metadata + a registry-validation test | Add the metadata schema + validation test (fails CI on missing metadata) |
| `mcp/server.py` `TOOLS` | inline list | typed `ToolSpec` + **a concurrent-HTTP test** for the ContextVar structured-override path | Write the concurrency stress test first (it's the real hazard) |

**Sequence:** write characterization tests → extract the lowest-risk collaborator → verify →
repeat. One collaborator per PR. Do **not** rewrite a god module in a single pass.

---

## 📋 Tier 4 — large quality-gate work (scoped, not done)

- **Versioned pricing provider.** Replace the flat `{model: (in,out)}` table with a provider
  carrying `source / fetched_at / currency / confidence`; **fail closed** for billing-grade use
  when a rate is unverified, with an explicit "estimate-only" mode. Today's OpenRouter rates are
  already labelled placeholders with a "verify before billing" TODO.
- **Failure-policy classification.** Tag every broad `except` as `fail_closed_{security,billing,
  audit}` / `fail_soft_with_audit` / `best_effort`, then add a lint forbidding unclassified
  handlers in production code. (Note: most current handlers are already intentional fail-open per
  kernel rule 1 — this is labeling for auditability, not a bug hunt.)
- **`Protocol` types** for `sandbox` / `capability` / `world-backend` / `LLM-provider` to replace
  pervasive `Any`, plus pyright/mypy incrementally on leaf modules. (CLAUDE.md notes no checker
  today — this is additive.)

---

## 📋 Tier 5 — docs / proof

- **This document** records the resolution of every item. ✅
- **STRESS_TEST.md refresh** — re-run the harness and update the scoreboard to numbers that
  reproduce (an independent run showed 14 failures, not 10; 6 cosmetic ruff errors). Pending a
  full local run (heavy; some gates need a provider key / Postgres the audit env lacked).
- **Deck claims still needing the founder's call** (from Tier 0): "8 packages on PyPI, installable
  today" (verify live PyPI), the pitch/site egress one-liners (your security voice), the
  confidential-compute "attestation" wording (it's spoofable indicator-detection).

---

*Bottom line for the meeting: the kernel is real, the worst slop is fixed, the docs/deck no longer
contradict the code, and everything that remains is either a recorded decision or a sequenced
engineering roadmap — nothing hidden.*
