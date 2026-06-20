# Maverick Codebase Improvement Audit — 2026-06-20

Read-only audit. Six parallel passes over the monorepo (core god-files; core
structure/duplication; web/dashboard/MCP layer; supporting packages; CI &
dependencies; testing/dead-code/error-handling/docs). Findings are deduplicated
and grouped by theme. Severity: High/Med/Low. Effort: S/M/L.

No files were changed by this audit other than this report.

---

## 0. Highest-leverage items (start here)

| # | Item | Sev | Effort |
|---|------|-----|--------|
| H1 | **Postgres tenant-isolation leaks** — `recent_goal_events`, `recent_turns`, `open_questions`/`all_questions` read by id with NO tenant scope (siblings are scoped). Cross-tenant read via id enumeration when RLS is off. Prune ops (`prune_goal_events`, `prune_processed_messages`, `prune_conversations`) DELETE across ALL tenants. | High | S |
| H2 | **`tools/__init__._apply_generated_tools` skips the no-shadowing guard** every other loader enforces — a self-learning generated tool named `shell`/`read_file` silently replaces the real built-in. | High | S |
| H3 | **Shield base64 bypass** — `builtin_rules._candidates` runs `_shell_deobfuscate` on the normalized string but not on base64-decoded blobs, so a base64-wrapped quoted `rm -rf "$HOME"/` evades `rm_rf_root`. | High | S |
| H4 | **Three mega-functions dominate maintenance cost**: `agent._run_inner` (~1140 lines), `orchestrator.run_goal` (~1000 lines), `cli.py` (6483 lines, one Click file). Decompose / split into packages. | High | L |
| H5 | **No pip caching in any Python CI job** + unsharded 9000-test suite run `-vvs` across a 3-interpreter matrix. Biggest cost/latency win. | High | S–M |
| H6 | **`paths.data_dir()` (tenant-scoped) bypassed by ~80 modules** that hand-build `Path.home()/".maverick"/...`, silently escaping multi-tenant isolation for per-module state files. | Med-High | M |

---

## 1. Architecture & structure (maverick-core: 354 flat modules)

### 1.1 Module families that should become subpackages
- **`compaction*` (10 modules)** → `maverick/compaction/`. Already a plugin
  architecture spread across flat files (`compaction_plugins` = registry,
  `compaction_strategies` = dispatcher, one strategy per sibling module).
  `compaction.py` and `context_compactor.py` independently reimplement approx
  token counting / message-text extraction. **High / M.**
- **`cost_*` (8 modules)** → `maverick/cost/`. `cost_forecast`/`cost_projection`/
  `cost_curve_fitter` overlap; `cost_report`/`cost_retrospective`/`cost_by_tag`
  are all spend-aggregation views. **Med / M.**
- **`provider_*` (5)** → existing `providers/`. **Med / S.**
- **`grpc_*` (4)** → existing `grpc_api/`. **Med / S.**
- **`tenant_*` (4)** → `maverick/tenant/`. **Low / S.**
- **`marketplace_*` (5) + `donation.py`** → `maverick/marketplace/` (`donation.py`
  overlaps `marketplace_donations.py`). **Low / S.**
- **`replay_*` + trace/trajectory** → `maverick/replay/`. **Low / S.**
- **`skill_*` (6) + `skills.py`** → fold into `skills/`. **Low / M.**
- Proposed top-level grouping for the remaining ~300 modules: `governance/`,
  `compliance/`, `learning/`, `cost/`, `budget/`, `channels/`, `infra/`,
  `security/`, `voice/`. Single highest-leverage navigability change. Keep
  top-level shims; update `docs/FEATURES.md` and `tools/` wrappers on any move.

### 1.2 Cross-module duplicated helpers
- **Retry/backoff/error-classification reimplemented 4×**: `retry.py`,
  `retry_classifier.py`, `provider_failover.py`, `failover_policy.py` — plus
  ~12 modules with ad-hoc `time.sleep()` loops. `retry_classifier` is the most
  complete; make it the single source of truth. Drifting retry semantics across
  providers is a real correctness/cost risk. **High / M.**
- **TTL + LRU cache logic hand-rolled per module**: `llm_cache.py`,
  `learning_cache.py`, `redis_tool_cache.py`, `tool_cache.py`, `file_cache.py` —
  none share a base; `cache.py` is only a stats/purge facade. Extract
  `cache/base.py TTLLRUStore`. **High / M.**
- **47 modules each hand-roll `def enabled()`** parsing env truthiness against
  the same `{"1","true","yes","on"}` literal set + config fallback. Add one
  `config.feature_enabled(name, env_var, config_path, default)`. **Med / S.**
- **`paths.data_dir()` bypassed by ~80 modules** (see H6). **Med-High / M.**
- **Duplicate `_PRICING` pricing table** in `cost_router.py` and `billing.py`;
  `budget.py` imports from `cost_router`. `llm._provider_api_key` also hard-codes
  a provider→env map that duplicates `config.PROVIDER_KEY_ENV_VARS` (and they
  already disagree: llm adds `GROK_API_KEY`/`GOOGLE_API_KEY`). One canonical
  pricing table + one key-env map. **Med / M.**
- **`_load_config`/`_read_config` reimplemented** in `grpc_plugin_host`,
  `mcp_registry`, `notifications`, `ts_plugin_host`, `webhooks` instead of
  `config.load_config()`. **Low / S.**

### 1.3 Orphaned modules / naming
- **Likely-dead** (0 non-test importers): `relay_reference.py`,
  `behavioral_diff.py`, `speculative_tools.py` (1 ref). Cross-check against
  `test_orphan_wiring.py` allowlist, then wire or delete. **Med / S.**
- **Unwired modules still present** (from FIXES.md, confirmed): `vision_click.py`,
  `prompt_dsl.py`, `computer_calibration.py` (1 ref); `migrate.py:125 REWRITES =
  []` (no-op shell); `maverick-knowledge/store.py:132` pgvector path still
  `raise NotImplementedError`. Wire, cut, or mark `experimental`. **Med / M.**
- **Inconsistent `_v2`/`_v3` suffixes**: `cost_router` (no v1/v2 file but a
  `test_cost_router_v2`) + live `cost_router_v3`; `skill_distillation_local` +
  `_v2` both live; `onboarding_v2`/`push_v2` have no v1 sibling. Pick one rule;
  drop meaningless suffixes. **Med / M.**
- **`AllAttemptsFailed(Exception)` defined twice** (`latency_best_of_n.py:17`,
  `speculative_best_of_n.py:35`) — callers catching one miss the other. **Low / S.**
- **`speculative*` prefix conflates** async racing vs LLM speculative decoding
  vs best-of-n parallel sampling. **Low / S.**
- Inconsistent role suffixes `*_host`/`*_runtime`/`*_runner`/`*_adapter(s)`. **Low.**

---

## 2. God-files (decomposition + per-file cleanups)

### 2.1 cli.py (6483 lines, Click)
- **Split into a `cli/` subcommand package** along the existing 28 Click groups
  (setup/run/runs/governance/privacy/learning/ops/tenant/templates/audit/finance).
  Mechanical because Click registers on import. **High / L.**
- `import json as _json` re-imported inside command bodies **42×** (inconstantly
  aliased) — one module-level import. **Low / S.**
- `if as_json: click.echo(_json.dumps(...))` hand-rolled per command with
  drifting `indent=` — `_shared.emit_json()`. **Med / M.**
- `@click.option("--json"…)` repeated 24×, `--format` 14× — reusable decorators.
  **Low / S.**
- **38 `open_world(...)` opens, only ~7 `world.close()`** — DB-handle/WAL leak;
  `dream` (4538) and others `return` without closing. `@with_world` /
  `world_session(ctx)` decorator. **Med / M.**
- `erase` (4118-4352, 235 lines) inlines a 7-table raw-SQL cascade DELETE that
  belongs in `world_model.erase_conversations(...)` (a `backend_erase` hook
  already exists at 4149). **High / L.**
- `export` command silently **shadows** the GDPR Art.15 `export_user` (Click
  allows duplicate names) — add a startup uniqueness assertion. **Med / S.**
- `_humanize_run_error` (107-152) classifies errors by substring sniffing
  (`"401" in msg`) — fragile; prefer concrete SDK exception types. **Low / M.**
- 21 broad-except sites, several silent `pass` (367-368 discards all config-lint
  output). **Low-Med / S.**

### 2.2 agent.py (3050 lines)
- **`_run_inner` (~1140 lines, `# noqa: C901`)** — extract `_handle_final`,
  `_run_test_driven_verifier`, `_run_llm_verifier`, `_assemble_assistant_content`.
  Single biggest maintainability liability. **High / L.**
- Assistant-content reconstruction (2138-2205) — accreted Anthropic
  thinking-signature rules across ~6 dated "council fix" comments; extract to a
  tested standalone fn. **Med / M.**
- 7 capability-denial methods (1045-1394) share an identical
  `blackboard.post` + audit-record + `return "⚠ DENIED …"` skeleton — extract
  `_deny(...)`. **Med / M.**
- Patch apply/reset + critique-`continue` repeated across require-apply and
  test-driven branches — `_request_patch_revision()`. **Med / M.**

### 2.3 orchestrator.py (1669 lines)
- **`run_goal` (~1000 lines, `# noqa: C901`)** — extract `_assemble_brief`,
  `_build_root_agent`, `_finalize_outcome`. **High / L.**
- 8 near-identical opt-in enrichment blocks (781-944: self_learning, experience,
  role_stats, skill_synthesis, corrections, reflexion, dreaming, ToT) — drive
  from a list and loop. **Med / M.**
- Budget-exceeded message copy-pasted 3× (1042/1167/1213) — `_budget_exceeded_message()`.
  **Low / S.**
- 5 near-duplicate failure-exit branches — `_fail_goal(status, result, ...)`. **Med / M.**

### 2.4 world_model.py (2435) / world_model_backends/postgres.py (1624)
- Postgres tenant-isolation leaks + cross-tenant prune (see **H1**). **High / S.**
- Postgres writes (`append_event`/`append_turn`/`append_message`/`add_attachment`/
  episode ops) take a raw parent id with no tenant-scoped existence check —
  write onto another tenant's goal by id enumeration. **Med / M.**
- `_tenant_scope` append boilerplate copy-pasted ~25× — `_apply_scope(sql, params)`.
  **Med / M.**
- 9-column goal SELECT repeated verbatim 10+× — `_GOAL_COLS` constant. **Low / S.**
- `active_goal`/`inflight_goal` near-identical (both files) — `_one_goal_where()`.
  **Low / S.**
- `WorldModel` god-class (~70 methods): consider splitting SCHEMA+MIGRATIONS into
  `world_schema.py` and CRUD into domain mixins. Well-organized, so debt not
  defect. **Low / L.**
- 5 `_*_from_row` helpers collapse to data-driven `_decode_row(Cls, row, sealed=…)`.
  **Low / S.**
- postgres: redundant local `import os` (300); stale `schema_version` docstring
  (264 — it IS version-stepped now); `total_spend` typed `dict[str,float]` but
  returns ints. **Low / S.**

### 2.5 llm.py (953) / config.py (938)
- `complete` vs `complete_async` are near-total copy-paste (chaos hook,
  observability import-fallback 660-677 vs 771-788, reserve/release, the two
  `finally` blocks byte-identical) — extract `_record_call_telemetry()`. **Med / M.**
- Static catalog data (`MODEL_PRICES` 55 entries, `MODEL_CATALOG`,
  `PROVIDER_LABELS`) has no dependency on the dispatcher — split into
  `model_catalog.py`/`pricing.py`. **Med / M.**
- `MODEL_PRICES` carries "TODO: verify … placeholders" for minimax/deepseek/qwen
  that feed `Budget.record_tokens` (real billing) — gate unverified models out of
  billing. **Med / M.**
- config.py: ~30 near-identical `get_<section>()` accessors → declarative schema
  (section → {key: (default, coercer)}) + one resolver. Numeric-coercion helper
  (`_clamp01`/`_int`/`_num`) reimplemented 15+×. **Med / L.**
- **Shared `config_util` (env_truthy / env_or_config / coerce_int/float / clamp01)**
  would absorb the single most pervasive duplication across config, llm, agent,
  orchestrator, world_model, self_learning, dreaming. **Med / M.**

### 2.6 self_learning.py (992) / dreaming.py (1490)
- self_learning `_validate_import_isolated` writes the success check/raise twice
  (sandbox vs subprocess branch) — collect once, check once. **Med / S.**
- dreaming: god-module → `dreaming/` package (`_lexical`, `insights`,
  `rehearsal`, `governance`, `cycle`). **Med / L.**
- `dream_cycle` (~137 lines) — extract `_replay_phase`/`_consolidate_phase`/
  `_rehearse_phase`; params shadow module functions forcing `globals()[...]`
  lookup. **Med / M.**
- Atomic-write-with-chmod boilerplate duplicated 4× → `_atomic_write_ndjson()`;
  NDJSON parse-skip-bad-line loop copy-pasted 5× → `_iter_ndjson()`. **Med / M.**
- `prune_facts` wraps both age+cap passes in one try → a mid-failure silently
  skips the cap pass. **Low / S.**

---

## 3. Web / dashboard / MCP layer

### 3.1 dashboard app.py (4737) / api.py (3027)
- **Split into routers** (`ui_pages`, `webhooks`, `streaming`, `ux`, `settings`,
  `health`); many `/api/v1` routes live on `app` directly instead of the
  `api_router`. **Med / L.**
- **Bidirectional in-function imports** between app.py and api.py (to dodge
  circular imports) — move shared helpers (`check_goal_rate_limit`,
  `safe_audit_day`, SSE helpers) into `_shared.py`. Root cause behind several
  findings. **Med / M.**
- **Duplicated SSE infrastructure**: `_sse_semaphore` defined independently in
  api.py and app.py, so the concurrency cap is **not** shared — real ceiling is
  3×64, not 64. The SSE generator body is duplicated 3× (~200 lines). **Med / M.**
- **"No provider key" 400 block copy-pasted 4+×** with wording drift — one
  `require_provider_or_400()`. **Med / S.**
- **12× tenant-admin route boilerplate** (`require_permission` + local
  `import tenant_registry` + `_get_tenant_or_404`) — sub-router with
  `dependencies=[Depends(require_admin)]`. **Med / M.**
- **Same-origin check repeated inline on ~18 POST handlers**; six `/settings/*`
  POSTs share an identical 4-line preamble — `Depends(require_same_origin)` /
  `require_admin`. **Med / M.**
- **HMAC-webhook preamble duplicated across 5 handlers** — `_verify_webhook()`.
  **Med / M.**
- **`record_outcome` does an O(100k) full episode scan** to validate one id
  (api.py:628) — add `episode_exists()` indexed SELECT. **Med / S.**
- **`WorldModel(DEFAULT_DB)` built ad-hoc and never closed** in several handlers
  (healthz 4542, metrics 4616, tools_page, list_tools) — leaks a connection per
  probe; `/metrics` and `/healthz` are scraped continuously. Standardize on
  `_world()`. **Med / S.**
- `_resolve_theme`/`resolve_density`/`_resolve_font` are the same query→cookie→
  config ladder — `_resolve_pref()`. `public_demo` builds HTML by string concat
  with inline `<style>` (vs Jinja everywhere else; conflicts with strict CSP).
  `/perf` is a 60-line giant handler. `oversight_page` 110 lines. Background-task
  dispatch pattern repeated 5×. **Low / S-M.**
- `/metrics` per-principal spend labels escape `\`,`"`,`\n` but not `\r`/`\t` —
  exposition-format injection surface. **Low / S.**

### 3.2 maverick-mcp server.py (1492)
- `_dispatch_tool` (if/elif ladder) duplicated by a parallel `_structured_result`
  ladder — a tool added to one but not the other is a live drift risk; replace
  with a `_TOOL_DISPATCH` dict. Same for the 15-branch `_dispatch_stdio_message`.
  **Med / S.**
- `handle_tools_call` (~110 lines) does validation + task-aug + dispatch +
  elicitation + **two copy-pasted shield `scan_output` blocks** + structured
  content — extract `_shield_block_or_none()`. Shield `scan_input` boilerplate
  also repeated in 4 tool methods. **Med / S.**
- `_bounded_float` ceiling-from-env pattern repeated 6× with identical literals
  — `_clamp_run_limits(args)`. **Low / S.**

### 3.3 core mcp_client.py (1193)
- `call_tool` byte-for-byte identical in `MCPClient` and
  `StreamableHttpMCPClient` (761-784 vs 1080-1093) — `_finalize_tool_result()`.
  **Med / S.**
- SSE `data:` parsing duplicated between `_read_sse_response_text` and `_extract`
  (which re-parses the full body already streamed) — duplicate work + drift.
  **Med / M.**

---

## 4. Supporting packages

### 4.1 tools/
- `_apply_generated_tools` no-shadowing gap (see **H2**). **High / S.**
- `_rest_connector._config()` duplicated verbatim between REST and GraphQL
  builders; GraphQL builder lacks basic-auth / `extra_headers_env` that REST has
  (latent: malformed `Authorization` for a future basic-auth GraphQL svc). **Med / S.**
- `base_registry` ~650-line fn mixing imports + ~300 sequential `reg.register()`;
  inline "merge dup" comments are scar tissue — a data-driven registration table
  would make drift impossible. **Low / L.**

### 4.2 maverick-channels
- `sms.py`/`whatsapp.py` webhook handlers near-identical (Twilio sig validation +
  allowlist + dedup claim/release) — `TwilioWebhookChannel` base. **Med / M.**
- Dedup claim/release lifecycle reimplemented in 5 channels with **subtly
  different fail-open vs fail-closed** semantics — shared `DedupClaim` context
  manager. **Med / M.**
- **`EmailChannel` has no dedup and never marks mail `\Seen`** — a crash after
  send (or two pollers) re-drives the swarm = real LLM spend. Only message-driven
  channel with no double-run protection. **Med / S.**
- **`VoiceChannel` accepts a missing `webhook_token` then 401s every request** —
  silently inert; raise in `__init__` like other channels. **Med / S.**
- `bluesky.py`/`mastodon.py` `except ImportError: return` silently drop a reply
  on missing httpx — log or raise. **Med / S.**
- 3 redundant `_normalize_allowlist` copies (telegram/mastodon/bluesky) identical
  to `base.normalize_allowlist`; `email_v2.py` is wired to nothing (helper lib,
  misleading "v2 of EmailChannel" docstring); deprecated `datetime.utcnow()` in
  bluesky. **Low / S.**

### 4.3 maverick-shield
- Base64 deobfuscation bypass (see **H3**). **High / S.**
- `rm_rf_root` pack has large gaps (`dd of=/dev/sda`, `mkfs.*`, recursive
  `chmod/chown /`, fork bombs, non-root abs-path `rm -rf`; trailing-boundary lets
  `rm -rf /;` through). **Med / M.**
- `guard.from_config` uses unguarded `safety["profile"]`/`["block_threshold"]` —
  a partial config raises `KeyError`, fail-closed crash in an otherwise fail-open
  chokepoint; use `.get(...)`. **Med / S.**
- `detect_system_prompt_regurgitation` is O(n·m) on the latency-gated path. **Med / M.**
- `cascade.scan_tool_call` never runs the deep scanner — tool calls (most
  dangerous sink) get least coverage. **Med / S.**
- LOW dedup: constitutional-scan blocks, invisible/tag char ranges drifting
  between cascade and builtin_rules, severity-normalization reimplemented 4×,
  duplicated JSONL corpus loaders. **Low.**

### 4.4 maverick-evolve / maverick-knowledge
- `knowledge/image.py` re-opens image for OCR with the decompression-bomb pixel
  cap no longer in force (also TOCTOU on a swapped file). **Med / M.**
- `HostedEmbedder`/`CohereEmbedder` never check `len(result) == len(texts)`;
  `base.ingest_text` then `zip(..., strict=False)` — silent index truncation/data
  loss. **Med / S.**
- `evolve/search.py:43` re-scores the seed config (a full live `maverick start`
  run) every continuous round — redundant LLM cost; reuse archive hit. **Med / S.**
- Duplicated TOML scalar serializers (`evolve/agent_adapter._toml_scalar` vs
  `adopt._toml_value`) — divergent escaping is a correctness hazard. **Med / M.**
- `SqliteVectorStore` default `check_same_thread=True` but shared via
  `KnowledgeBase` — breaks under `asyncio.to_thread`/worker pool. **Med / M.**
- LOW: duplicated httpx embedder scaffolding, redundant cosine renorm of
  normalized vectors, persisted `Candidate.id` dropped on load,
  `config_space.in_bounds` ignores float `step`.

### 4.5 apps/installer-cli (the wizard)
- **Config-knob ↔ wizard drift**: `mcp_registries`/`template_registries` are
  emitted config knobs with NO wizard step (only `test_wizard_parity` supplies
  them) — violates "wizard is the UX source of truth." Add a step or drop. **Med / M.**
- `bridge.py` hard-codes consumer-budget literals instead of sharing
  `_consumer_budget`; omits the "custom" budget chip; `_recv()` can't distinguish
  EOF from a blank answer (dead Tauri pipe → all-default config). **Med / S.**
- 5 near-identical `_capture_*_session` fns + 5-arm elif → one data-driven
  `_capture_session(provider, spec)` (~115 LOC). `pick_advanced` ~350-line literal
  of ~50 toggles, 800 lines from its emit branches → `ADVANCED_TOGGLES` table so a
  test asserts every key has an emit branch. **Med / M.**

### 4.6 sdks/plugin-ts & rust
- TS `summarizePageContext` trusts untrusted `counts.elements/landmarks` over
  actual (capped) array lengths — a malicious snapshot prints a lying count;
  prefer `ctx.elements.length`. **Low / S.**
- Rust ports (`mvk-scan` secret/pii/canonical) are high-quality CPython-parity
  with fail-safe over-redaction. Minor: `canonical.rs` relies on serde
  `arbitrary_precision` — add a build-time assertion the feature is enabled;
  test-only `had_dangerous_helper` scaffolding. **Low / S.**

---

## 5. CI / build / dependencies

### CI
- **No pip caching in any Python job** (`setup-python` everywhere lacks
  `cache: pip`) — re-resolves ~15 deps ×3 interpreters + audit/eval/postgres/
  redteam/MCP-client jobs. Add `cache: pip` or move to `uv`. **High / S.**
- **9000-test suite run unsharded, single-process, `-vvs --tb=long` ×3 matrix** —
  add `pytest-xdist -n auto`, drop `-vvs` to `-q`, consider sharding. **High / M.**
- **CI uses bare `pytest`** (ci.yml:283/325/360), violating CLAUDE.md's own
  `python -m pytest` rule. **Med / S.**
- **8-line multi-package `pip install -e … --no-deps` block copy-pasted across
  6 files / 10+ jobs**, runtime-dep floor list duplicated in 3 places and already
  disagreeing — extract a composite action `.github/actions/install-maverick`.
  **High / M.**
- No `concurrency: cancel-in-progress` on ci.yml (native.yml/docs.yml have it) —
  rapid pushes run the full expensive matrix in parallel. **Med / S.**
- Docker built in ci.yml with no layer cache while release.yml proves the
  `type=gha` cache pattern. **Med / S.**
- `agent-on-pr.yml` documents pinning to `@main` (with `pull-requests: write`)
  while all third-party actions are SHA-pinned — supply-chain inconsistency.
  **Med / S.**
- 6 custom gates + 4 security scans all run **serially in one `lint` job**, each
  re-installing core; could parallelize + share install. Mixed GitHub-action
  major versions (v4/v5 vs v6/v7/v8). 4 near-identical MCP-client workflows →
  one language matrix. **Low / M.**

### Dependencies
- **`python-multipart` floor skew**: packages pin `>=0.0.27`, CI test/release
  install `>=0.0.9` — CI can validate/ship below the package floor. **Med / S.**
- **`pillow` floor skew**: core `>=12.2.0` (CVE-patched), knowledge `vision`
  extra `>=10.0` — `maverick-knowledge[vision]` can resolve a vulnerable pillow.
  **Med / S.**
- **No shared constraints file** — the same CVE floors (starlette, requests,
  urllib3, python-multipart) are hand-duplicated across ~8 sites; a bump must
  touch all. Adopt `constraints.txt` + uv `constraint-dependencies`. **Med / M.**
- `[scan]` extra (`agent-shield>=14.0`) and niche extras (langchain, ros/i2c/
  serial) have no CI smoke install/import — add an extras-import matrix. **Low / S.**
- Harmless: `httpx>=0.27` redundantly redeclared across ~10 core extras. **Low.**

---

## 6. Cross-cutting

### Error handling (strongest cross-cutting signal)
- **`except Exception` appears ~1,493× in non-test code; 307 `except …: pass`
  blocks swallow with no log/re-raise.** Worst by silent-pass count: `agent.py`
  (16), `cli.py` (10), `world_model.py` (9), `coding_mode.py`/`webhooks.py`/
  `dreaming.py`/`compliance.py`/`audit/signing.py`/`dashboard/app.py` (6 each).
  Many are justified fail-open (kernel rule 1), but at this density a genuine
  silent bug is indistinguishable from intent. Adopt a convention: silent swallow
  must carry `# fail-open: <reason>` or a `logger.debug`; lint for bare
  `except …: pass` without one. Individually review the `webhooks`/`compliance`/
  `audit` spots. **Med / M.** (Only one true bare `except:` exists, in a comment.)

### Testing
- **`test_q*_batchN.py` waves are shallow smoke tests** — rigid 3-tests-per-tool
  template (`requires_op`, `missing_token`, substring `_renders` against a canned
  httpx mock) that never asserts the outbound URL/payload/headers/retries. Assert
  on the mock's call (`assert_called_with`); the better pattern already exists in
  `test_batch7`. **Low / M.**
- **No `pytest-cov` line-coverage gate**, and CLAUDE.md's `test_<module>.py`
  convention is a false coverage signal (286/786 modules lack a same-named file
  but are covered in topically-named files). Add a coverage gate or drop the
  per-module-file claim. **Med / S-M.**
- 59 test functions contain no `assert`/`raises` (e.g. `test_preflight_wiring.py`,
  `test_imports.py`). Thin coverage on `context_compactor.py`, `prm.py`,
  `screenshot_seal.py`; thin packages knowledge (3/8) and evolve (9/11). **Low-Med / M.**

### Config
- `import tomllib` try/except 3.10-compat block duplicated 17× — a single
  `maverick._toml` shim re-exporting `tomllib`. **Low / S.**

### Docs drift
- **Schema version stale**: code is `SCHEMA_VERSION = 20`, but README.md:141,
  docs/architecture.md:34, durable-execution.md:11 say v16; FEATURES.md:152 says
  v14; a research doc says v10. Sync to one source of truth. **Med / S.**
- `docs/FEATURES.md:1443` cites non-existent `eval_adversarial_cost.py` (actual:
  `tools/adversarial_eval.py` / `tools/adversarial_self_test.py`). **Low / S.**
- **`CODE_REVIEW_2026-06.md` / `FIXES.md` are largely historical** — most of
  their High-severity items are already remediated in current code (verified:
  devcontainer `scrub_env`, voice/rcs `compare_digest.encode`, postgres GDPR
  erase rewrite, MCP stdio dict validation, knowledge `store.close()`, etc.). Mark
  resolved items so the docs stop implying open security bugs (itself misleading
  for diligence). Genuinely open: the unwired-module items in §1.3. **Med / S.**

### Clean (non-findings, for the record)
- **vulture is clean** at `min_confidence=80` (1 false-positive: `exc_type` in a
  context-manager signature).
- **print()-vs-logging is a non-issue** — the ~104 library `print()`s are all in
  `__main__`/argparse CLI entrypoints, subprocess-emitted code strings, or
  docstrings; library code uses `logging` (361 modules import it).
- Postgres backend has **no SQL injection** (all dynamic fragments are `%s`
  placeholders; LIKE inputs go through `_like_escape`) and no cursor leaks.
- Webhook signature checks consistently use `hmac.compare_digest` (no `==`).

---

## Remediation status (updated 2026-06-20)

### Fixed (landed on `claude/codebase-improvement-audit-nd1tu3`, PRs #1640 / #1645)

**Security / correctness (High):**
- Postgres tenant-isolation leaks in `recent_goal_events`, `recent_turns`,
  `open_questions`, `all_questions`, and the `prune_*` deletes — now scoped.
- `tools/__init__._apply_generated_tools` no-shadowing guard added.
- Shield base64-deobfuscation bypass closed; added `disk_overwrite`,
  `recursive_chmod_chown_root`, `fork_bomb` rules; broadened `rm_rf_root`;
  `guard.from_config` no longer KeyErrors on a partial config.

**Channels:** email `\Seen` dedup; voice token required at listen; bluesky/
mastodon log instead of silent-drop; 3 duplicate `_normalize_allowlist` removed.

**Knowledge:** embedder length-mismatch guards; OCR pixel-cap kept in force
during decode (`_pixel_cap`); `SqliteVectorStore` thread-safe; `pillow` floor
raised to `>=12.2.0`.

**Dedup / perf:** evolve TOML serializer unified; MCP `_dispatch_tool` dict +
`_shield_block_or_none`; `mcp_client._finalize_tool_result`; REST/GraphQL
connector `_env_config`/`_build_auth_headers` (GraphQL gained basic/extra-header
auth); `WorldModel.episode_exists` (was a 100k-row scan); single canonical
`PROVIDER_KEY_ENV_MAP`; `orchestrator._budget_exceeded_message`; **dashboard SSE
semaphore now process-wide shared** (was 2 independent caps); dashboard
`require_provider_or_400`; dreaming `_atomic_write_lines`; self_learning
`_raise_if_import_check_failed`; assorted redundant-import/`isinstance` tidy-ups.

**Docs:** world-model schema version synced to v20.

All landed with passing tests (full suite: 11,337 passed / 148 skipped / 3 xfailed).

### Deferred — large structural refactors (recommend separate, individually
reviewed PRs; out of scope for a single safe automated pass per kernel rule 7
"surgical diffs / no speculative abstractions")

- Split the god-files: `cli.py` (6483 lines → Click subcommand package),
  `agent._run_inner` (~1140), `orchestrator.run_goal` (~1000).
- Reorganize the 354 flat core modules into subpackages
  (`compaction/`, `cost/`, `providers/`, `grpc_api/`, `tenant/`, …).
- `config.py` declarative section schema (~30 near-identical getters).
- Cross-module helper unification carrying real behavior risk: retry/backoff
  classifier (4 modules → `retry_classifier`), TTL/LRU cache base (5 modules),
  `feature_enabled` (47 `enabled()` sites), and routing every state-file path
  through `paths.data_dir()` (~80 modules — a tenant-isolation correctness win,
  but touches where data is stored, so needs migration care).
- Dashboard auth-path consolidations (HMAC webhook preamble ×5, same-origin
  `Depends` ×18, tenant-admin sub-router ×12) — touch CSRF/auth enforcement, so
  warrant focused review rather than a bulk rewrite.

---

## Remediation status — round 2 (deferred items, 2026-06-20)

### Additionally fixed (PR #1648, full suite green at each step)
- **cli.py god-file split** — `cli.py` → `cli/` package + extracted finance/
  compliance/ops command clusters (~1,120 lines out of `__init__.py`).
- **`config.env_flag`** — shared tri-state env parser adopted across 23 `enabled()`
  gates (the `feature_enabled` finding).
- **`_verify_maverick_webhook`** — deduped the `/webhook/start` + `/webhook/run`
  HMAC preamble.
- **agent denial methods** — routed through the existing `_audit_tool_event`
  helper (audit-record scaffold no longer hand-rolled in 5 methods).
- **orchestrator enrichment blocks** — `_enrich(label)` context manager replaces
  the repeated `try/except/log.debug("X skipped")` scaffold in 14 blocks.
- **`_require_same_origin`** — the inline CSRF guard in 20 form handlers.

### Investigated and intentionally NOT bulk-applied (with reasons)
These were examined at the code level; each is a risky rewrite or pure churn, not
a safe mechanical change, and belongs in its own designed/reviewed PR:
- **TTL/LRU cache "base"** — `llm_cache` (SQLite) and `learning_cache` (JSON dict)
  share the *concept*, not literal code; a common base means rewriting two
  different storage engines (eviction/persistence/concurrency behavior risk).
- **retry unification (4 modules)** — `retry`, `retry_classifier`,
  `provider_failover`, `failover_policy` are context-specific classifiers;
  forcing them onto one classifier changes provider-retry decisions (cost/latency
  behavior risk).
- **354-module subpackage reorg** — purely navigational; one family (compaction)
  alone touches ~30 import sites; kernel rule 7 ("no speculative abstractions").
- **`paths.data_dir()` across ~80 modules** — silently relocates persisted state
  in multi-tenant deployments (`~/.maverick/x` → `tenants/<t>/x`); needs a data
  migration, not just a code edit.
- **`run_goal` / `_run_inner` full decomposition** — dense shared local state
  (`brief`, `_planning_mode`, ~10 interdependent locals on the hot path); safe
  extraction needs a class-level refactor + careful review, not a bulk move.

### Update 2 (2026-06-20): god-file decomposition + cache/retry verification

**Decompositions landed (behavior-preserving, full suite green):**
- `orchestrator.run_goal` — extracted the ~300-line brief assembly into
  `_brief_facts_block`, `_apply_brief_enrichments`, and `_build_orchestrator_brief`.
- `agent._run_inner` — extracted `_assemble_assistant_content` (the interleaved
  thinking-block reconstruction). The remaining FINAL-handling block mutates
  `messages` and drives continue/break, so it needs a run-state object, not a
  verbatim lift — left for a dedicated change.

**Cache TTL/LRU "shared base" — evaluated, partially applied:** `cache.llm`
(SQLite rows) and `cache.learning` (JSON-persisted dict) back incompatible
stores with different TTL encodings (relative age vs absolute `expires_at`), so a
single concrete store base would require migrating one's on-disk format. Instead
the shared *policy* is extracted to `cache/eviction.py` (`is_expired`,
`lru_keys_to_evict`), adopted by the dict-based `learning` cache; the SQLite
`llm` cache references it and keeps its SQL eviction. A full store-base merge was
rejected per kernel rule 7 (no speculative/behavior-changing abstraction).

**Retry classifier "single source of truth" — verified already integrated:**
`retry.sync_retry`/`async_retry` already delegate the terminal check to
`retry.classifier.classify`; `provider_failover.should_retry_llm_error` is an
orthogonal control-signal *type* guard (BudgetExceeded/EgressBlocked/
PreflightFailed/ConsentDenied), not transient classification; and
`failover_policy.classify_error` is a deliberately different 7-class failover
taxonomy. Collapsing them onto one classifier would change which errors
retry/failover, so no further unification is safe.
