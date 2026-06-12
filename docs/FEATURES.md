# Maverick — Shipped Features

What Maverick **does today**, grounded in the code on `main`. This is the
catalogue of built features and tools; the forward backlog (what's *not* done
yet) lives in [`ROADMAP.md`](./ROADMAP.md). When a roadmap item ships, it moves
here.

> Conventions: capabilities are grouped by concern. Module paths are relative to
> `packages/maverick-core/maverick/` unless noted. CLI verbs are shown as
> `maverick <verb>`.

## Agent kernel & orchestration

- **Recursive multi-agent swarm** — orchestrator decomposes a goal and spawns
  specialist sub-agents (researcher / coder / writer / verifier / revisor /
  reflector), run in parallel (`orchestrator.py`, `agent.py`, `swarm.py`).
- **Durable, resumable execution** — checkpoint / rewind / `maverick resume`
  (`checkpoint.py`), opt-in via `[durable]`.
- **Kernel lifecycle hooks** — `PreToolUse` / `PostToolUse` / `UserPromptSubmit`
  (`hooks.py`), registrable from plugins.
- **Budget caps** — hard dollar + wall-clock + tool-call ceilings the kernel
  refuses to exceed (`budget.py`).
- **Killswitch** — `~/.maverick/HALT` aborts all running goals (`killswitch.py`).
- **Long-horizon review checkpoint** — opt-in `[safety] review_checkpoint`
  (`review_checkpoint.py`): the root agent fires a human-review heartbeat every
  N dollars / M tool calls / T wall-seconds; a reviewer vote to halt (an armed
  killswitch by default) stops the run cleanly. Distinct from the hard budget
  cap; inert and behavior-identical when unconfigured.
- **Verifier default-on** across goal types (`verifier.py`); **reflexion** retry
  loop with cross-session failure memory (`reflexion.py`); graded **critic** for
  structured accept/revise/reject feedback (`critic.py`).
- **Planning topologies** — tree-of-thought (`tree_of_thought.py`), debate
  (`debate.py`), **plan-execute-reflect** loop (`plan_execute_reflect.py`,
  `maverick plan-reflect GOAL`): a planner decomposes the goal, an executor runs
  each step, a reflector decides done/revise/continue and loops until done, the
  iteration cap, or the budget runs out — speculative decode/finalize
  (`speculative.py`), latency-aware best-of-N that cancels laggards
  (`latency_best_of_n.py`), shared-scratchpad blackboard (`blackboard.py`),
  cross-agent bus (`agent_bus.py`), and a read-only **observation channel**
  (`observation_channel.py`) — a live push/subscribe broadcast of the swarm's
  event stream for an external observer (monitoring agent, dashboard,
  supervisor) that doesn't join the control flow; `blackboard.post` tees into
  it, a slow observer drops its oldest events rather than stalling the swarm,
  and it's a no-op (lock-free subscriber check) when nobody is watching.
- **Context lifecycle** — deferred tool loading + `find_tools`, cross-session
  `memory` tool (`tools/memory.py`), programmatic tool calling
  (`tools/code_exec.py`), structural/retrieval-augmented compaction
  (`compaction.py`, `context_compactor.py`), and a **long-context retrieval
  router** (`long_context_router.py`) that shards an oversized payload (e.g. a
  document pasted into a goal) and keeps only the query-relevant shards instead
  of overflowing the model window — zero-dep lexical ranking by default, an
  injected Chroma/Qdrant store for embedding-quality retrieval; opt-in via
  `[context] retrieval_router`.
- **Compaction plug-in API** (`compaction_plugins.py`) — register a custom
  context-compaction strategy (graph-structured, domain summarizer, a learned
  model) under a name and select it via `[context] compaction_strategy`; the
  shipping heuristic registers as the default `"heuristic"`, and `compact_with`
  **fails safe** to it when a configured strategy is unknown (a typo degrades to
  working compaction, never none) — so the kernel's compaction is extensible
  without a fork. Four strategies ship registered in this one dispatcher (and
  are reachable from `agent.py`'s per-turn compaction): **`learned`** (LLM
  summary with a self-tuning prompt picker scored by an outcome ledger),
  **`multimodal`** (replaces heavy image/audio blocks with text stubs that keep
  the media fact + dimensions), **`streaming`** (an incremental running summary
  with a persisted per-conversation cursor — folds only new turns), and
  **`graph`** (an entity-relation digest); each degrades deterministically
  without an llm and is selected by name via `[context] compaction_strategy`.
- **Local continuous learning** — distill successful run trajectories into a
  reusable, validator-compliant `SKILL.md` under `~/.maverick/learned-skills`
  (`skill_distillation_local.py`), opt-in via `[self_learning] distill_local`.
  **v2** (`skill_distillation_v2.py`) adds two quality gates so the loop stays
  useful: it won't distill from fewer than N successful trajectories (a one-off
  success is noise), and it dedups a candidate against the learned-skills store
  by lexical containment so near-duplicate lessons don't accumulate — the
  orchestrator uses the gated path.
- **Dreaming (offline consolidation)** — `maverick dream` (`dreaming.py`,
  opt-in `[dreaming] enable`) replays recent successes + failure reflexions
  while the swarm is idle, attributes them to departments (domain packs),
  distills recurring wins into learned skills per department (via the gated
  v2 distiller), clusters recurring failures into *dream insights*
  (`~/.maverick/dreams/insights.ndjson`) that the orchestrator recalls on the
  next similar goal — a domain run is boosted toward its own department's
  insights — and prunes stale near-duplicate reflexions. Deterministic and
  LLM-free, so consolidation can't be steered by injected trajectory text.
  Reflexions also carry the recording run's department (`reflexion.py`
  `domain` field), and same-department lessons outrank equally-similar
  generic ones at recall time.
- **Cross-department insight promotion** — a failure pattern recurring in
  ≥2 distinct departments becomes a *shared* insight every department
  recalls (`promote_shared_insights`; `[dreaming] promote_shared`).
  Compartment seals stay intact: only the consolidated lesson crosses the
  boundary, never raw department trajectories.
- **Skill retirement (the forgetting loop)** — a dream phase moves learned
  skills with a decayed track record (`skill_stats.evictable`: enough uses,
  win rate under the floor) to `learned-skills/retired/` with a logged
  reason — out of the recall glob, reversible by moving the file back
  (`[dreaming] retire_skills / retire_min_uses / retire_below`).
- **Dream-time rehearsal** — dream cycles queue the biggest recurring
  failure patterns as practice cases (`[dreaming] rehearse`,
  `~/.maverick/dreams/rehearsals.ndjson`); `maverick dream --rehearse` runs
  them as budgeted `[rehearsal]`-titled goals and reports how many
  previously-failing patterns now complete. Refused while verifier
  calibration is frozen (the same interlock that gates maverick-evolve), so
  the system never practices against a distrusted grader.
- **Department-scoped routing memory** — a domain swarm's counterfactual
  credit is recorded both globally and per department
  (`role_stats.py` `<domain>::<role>` keys); a domain run's routing guidance
  prefers its own department's track record and falls back to the global
  signal when history is thin.
- **Human-override ingestion** — when a human declines an Art-14 approval
  gate, the refusal is persisted as a recallable lesson
  (`reflexion.record_human_override`, failure class `human_override`,
  department-tagged) so the next similar goal proposes an alternative or
  seeks approval earlier — and dreaming consolidates repeated refusals into
  department insights. Opt-in via `[reflexion]`; the audit record is
  unchanged.
- **Signal capture across the run lifecycle** — goal rows persist their
  department (schema v14 `domain` column; resumes inherit it); a stall on a
  user question records WHAT was missing (`blocked_on_user`); a loop-guard
  tool-failure streak persists as `tool_flaky` (and `find_tools` demotes
  repeat offenders at discovery time); an explicit user correction of the
  prior answer becomes a `user_correction` lesson (`corrections.py`,
  deterministic phrase match over the triggering turn only); verifier
  critiques are mined out of donated trajectories into dream fodder.
- **Insight lifecycle management** — a recurring pattern *refreshes* its
  standing insight (ts + evidence) instead of duplicating; insights
  unconfirmed for `[dreaming] insight_ttl_days` age out; a failure insight
  contradicted by newer similar successes retires; opt-in fact pruning
  (`[dreaming] prune_facts`, default off — the only phase touching operator
  data) expires stale facts and caps the table.
- **Per-user preference notes** (`user_notes.py`) — explicit, deterministic
  preference statements ("I prefer tables", "call me Sam") distilled from
  recent conversations into briefing notes injected ONLY for their exact
  (channel, user) scope; the store rewrites every cycle, so deleted
  conversations stop feeding notes.
- **Learned behavior selection** — `[planning] mode = "auto"` picks
  tree-of-thought per task class from a learned outcome record
  (`planning_stats.py`, bandit-lite + deterministic); budget task classes
  scope by department (`finance_sox::reconcile` learns finance-shaped
  caps); the learned compaction ledger scopes by department
  (`scope|kind` rows).
- **Verifier-scored rehearsal + evolve bridge** — `maverick dream
  --rehearse` grades each practiced case with the calibrated verifier, and
  `maverick-evolve --live --rehearsals` consumes the rehearsal queue as
  weighted eval cases so config evolution optimizes against the operator's
  own recurring failures. `maverick-evolve --adopt` overlays the archive's
  best config onto a domain pack (persona/description/models only —
  capability scopes are refused), diff-shown, `--yes`-gated, `.bak`-backed.
- **Learning-side canary** — probation retirement (a new skill that loses
  its first 3 decided uses outright is retired early) and a benchmark gate:
  while `continuous_benchmark` history shows a regression, a dream cycle's
  NEW skills are quarantined (reversibly) instead of going live.
- **Learning governance** — every dream cycle writes one tamper-evident
  `learning_update` audit row; `maverick dream --dry-run` runs the full
  cycle against temp copies and reports exact would-be changes; each CLI
  cycle snapshots all learned stores first (`--list-snapshots`,
  `--rollback latest|<name>` restore wholesale); with an active tenant,
  every learned store resolves under the tenant's data dir so one tenant's
  memory never feeds another's runs.
- **Specialist operating discipline** (`domain_discipline.py`, on by
  default; `[domains] discipline = false` opts out) — every domain pack's
  persona is augmented at spawn with a universal verification/escalation
  discipline plus its suite's professional guardrails (finance
  maker-checker + SoD, legal privilege, HR PII-minimization, IT/GRC
  chain-of-custody, ops safety interlocks, engineering tests-first, GTM
  no-overpromising, strategy source-grounding). One implementation point
  upgrades all 1,000 built-in packs AND operator/intake-generated packs;
  prompts only — hard limits stay with capabilities/governance.
- **Department memory at every spawn depth** — `agent_from_profile` appends
  the department's recalled lessons (same-department reflexions + dream
  insights) to a specialist's brief, so a `spawn_specialist` child starts
  with its department's memory instead of blank (`[domains] memory`;
  no-op unless those loops are enabled).
- **Pack quality gate** — `maverick domains-lint [--ci --warnings]`
  (`domain.lint_profile`): errors for envelope holes (empty tool allowlist
  = ALL tools, missing/unknown `max_risk`), warnings for quality gaps
  (thin persona, allow∩deny overlap, no knowledge sources, no deny list).
  All built-in packs lint clean; every pack now carries at least a
  suite-level `knowledge_sources` grounding fallback.
- **Hindsight engine** (`hindsight.py`, `maverick hindsight [--strict
  --ledger]`) — replays past goals against learned-state snapshots to detect
  when the forgetting loops silently cost coverage: gained / regressed /
  unchanged, deterministically, with no agent re-runs. `--strict` is a
  learning-regression CI gate; `--ledger` appends a tamper-evident row.
- **Workforce value report** (`workforce_value.py`, `maverick proof
  [--fleet]`) — deliverables completed, agent cost vs human baseline →
  cost avoided + ROI, the capability improvement curve from the hindsight
  ledger, and governance evidence, per department (and per external vendor
  with `--fleet`). Read-only; the POC-closing artifact.
- **1,000-agent specialist portfolio across 25 suites** — the original 8
  business suites plus customer experience, marketing, procurement,
  data & analytics, security ops, executive office, facilities/EHS, and 10
  industry verticals (healthcare, insurance, banking, retail,
  manufacturing, construction, logistics, professional services,
  government contracting, education/nonprofit), with jurisdiction packs
  (country employment law, GDPR/CCPA/PIPL/EU-AI-Act regimes, indirect-tax
  regimes). Quality gate: `maverick domains-lint [--ci]` — every pack has
  a bounded persona, least-privilege allow list, explicit deny list, and
  risk ceiling; 0 errors, 0 warnings across all 1,000.
- **Fleet memory — the Learning System of Record** (`fleet_memory.py`,
  opt-in `[fleet_memory] enable`; MCP tools `maverick_fleet_ingest` /
  `maverick_fleet_recall`; CLI `maverick fleet-memory`) — ANY external agent
  (Agentforce, Copilot, custom, OSS runtimes) deposits experience into and
  recalls from Maverick's governed memory: roster-gated (fail-closed),
  Shield-scanned, provenance-tagged (`vendor:agent_id`), tenant-isolated,
  every read audited. Successes/failures consolidate through the dream
  cycle; `maverick proof --fleet` breaks value out per vendor.
- **The Operating Record** (`operating_record.py`, `maverick record
  stats|search|export|verify`) — the firm's decisions as a system of
  record: goals (with departments, outcomes, spend) + human approvals
  (with deciders) threaded into one queryable spine, exportable as an
  Ed25519-signed portable **capsule** (decision spine + learned state)
  verifiable offline; tampering fails verification.
- **Federated insight exchange** (`insight_exchange.py`,
  `maverick insights-export` / `insights-import`) — consolidated lessons
  (never raw trajectories) cross instance boundaries as Ed25519-signed
  bundles; imports are fail-closed against `[dreaming]
  trusted_insight_pubkeys`, Shield-scanned, provenance-tagged, and merged
  through the normal dedup gate. Transport is deliberately operator-managed
  (a file), never a network call. **Fleet aggregation:** a central
  `maverick dream --donations-dir` replays the whole fleet's donated
  trajectory records through the same consolidation.
- **Vector-store cross-run memory** — opt-in `[memory] backend` routes
  cross-run recall through a persistent **Chroma / Qdrant / Weaviate** store
  (`vector_store/`, `semantic_recall.py`) so similarity search is indexed and
  incremental instead of a linear re-embed scan; fail-open and
  dependency-injectable — the kernel never *requires* a vector store. The
  **Weaviate** adapter (`weaviate_store.py`, `[weaviate]` extra) targets a
  local or cloud v4 cluster with a server-side vectorizer (`near_text`). The
  **pgvector** adapter (`pgvector_store.py`, `[postgres]` extra) keeps vectors
  in the same Postgres database as the world-model backend (cosine `<=>`
  search); it takes an injected embedder rather than embedding itself, so
  recall reuses the local fastembed model.

## Tools

100+ built-in tools. Highlights by group (all under `tools/`):

- **Code & files** — `fs`, `str_edit`, `ast_edit` (tree-sitter), `apply_patch`
  (atomic multi-file), `repo_map`, `dep_graph`, `test_impact` (coverage-guided),
  `reviewer` (diff review), `file_watcher`, `notebook_exec` (run a .ipynb's code
  cells in the sandbox), `self_edit` (human-gated, path-confined edits to
  Maverick's own code/config), `html_to_app` (scaffold a starter app from an HTML
  mockup).
- **Data** — `sql_query` (read-only by default), `pandas_query`, `spreadsheet`
  (CSV/XLSX, write-capable), `compute` (SymPy), `embeddings`.
- **Web & research** — `web_search` (Tavily/Brave/DDG/SerpAPI), `http_fetch`,
  `browser` (navigate/click/type/`fill_form`), `browser_device` (device-emulation
  presets), `browser_auth_vault` (Fernet-encrypted session store), `websocket`
  (ws/wss connect-send-recv), `dom_diff` (structural before/after HTML diff),
  `arxiv`, `semantic_scholar`, `wikipedia`, `hackernews`, `youtube`.
- **Media** — `view_image`, `view_video`, `pdf_reader`, `ocr`, `voice`
  (transcribe/speak — with **voice persona presets** (`[voice.personas]`:
  named backend+voice bundles selected per call) and **multi-language voice**
  (`[voice.languages]`: per-language voice map, BCP-47 prefix match); explicit
  args always win, unknown presets degrade to defaults — `voice_personas.py`), `ffmpeg_tool`, `imagemagick_tool`, `pandoc_tool`,
  `office_convert` (LibreOffice headless: the binary office formats pandoc
  can't take — Word/Excel/PowerPoint/OpenDocument → PDF/text/HTML/CSV, all
  sandbox-mediated with workdir-confined paths),
  `replicate_tool` (image/video/audio gen), `latex` (math→MathML + document→PDF),
  `diagram` (Graphviz / Mermaid render).
- **Robotics & hardware** — `ros` (drive a ROS stack over **rosbridge** via
  `roslibpy`, `[ros]` extra): publish a command to a topic (e.g. `/cmd_vel`) or
  call a service; auth `ROS_BRIDGE_URL`, no native ROS in the agent process.
  `serial` (embedded device over **UART**/serial via `pyserial`, `[serial]`
  extra): list_ports / write / read / query a microcontroller or board, with a
  device-path guard so it can't be turned into an arbitrary-file opener.
- **Knowledge** — `knowledge_search` (per-domain RAG over collected docs),
  `recall`, `kv_memory`.
- **Productivity & SaaS connectors (~47)** — GitHub Actions, GitLab,
  Bitbucket (issues / PRs / pipelines), Jira, Linear,
  Asana, Trello, ClickUp, Confluence, Notion, Obsidian, Slack, Discord, Gmail,
  Google Drive, Dropbox, Calendar, Salesforce, HubSpot, Stripe, Shopify, Plaid,
  TrueLayer (EU/UK open banking),
  Twilio, Zoom, S3, DynamoDB, MongoDB, Redis, Elasticsearch, Datadog, Sentry,
  PagerDuty, Mixpanel, PostHog, Plausible, GA4, Home Assistant, Cloudflare,
  Vercel, AWS Lambda/SES/SNS, Microsoft Graph, and more.
- **System** — `shell` (sandbox-mediated), `wasm_run` (**WASM sandbox**:
  execute a WebAssembly/WASI module under wasmtime — capability-grant
  isolation where the module sees ONLY the preopened dirs/env/args given;
  workdir-confined paths, validated env keys, sandbox-mediated invocation),
  `git_advanced`, `compute`,
  `dns_lookup`, `openapi_runner`, `clipboard`, `notify`, `attachments`,
  `android` / `ios_sim`, `a11y`, `task_graph` (persistent dependency-DAG of
  tasks — add/status/ready/order/list plus **`critical`**: the longest
  dependency chain, weighted by optional per-task cost, that bounds completion
  no matter the parallelism — the tasks a critical-path-aware scheduler runs
  first), `workspace_snapshot` (snapshot/restore a working dir), **S3-backed
  attachments** (`[attachments] s3_bucket`: mirror every stored attachment to
  any S3-compatible bucket + `s3_fetch` pulls it down on another worker host;
  local disk stays the source tools read, mirror is fail-open), `license_scan`
  (classify deps + flag copyleft), `self_capability` (report the run's capability
  grant), `oidc` (OIDC authorization-code client), `oauth_helper` (generic OAuth2 for
  any provider — PKCE authorize URL / code exchange / refresh; token responses
  summarised with a sha fingerprint and never echoed into context, full tokens
  land in a 0600 MAVERICK_OAUTH_OUT file), `cost_curve` (per-provider cost
  model), `bench_track` (record benchmark scores + flag regressions), `teams`
  (Microsoft Teams webhook), `knowledge_graph` (extract/query/render
  subject-relation-object triples; no external graph DB), `cross_repo_deps`
  (cross-repo Python package import graph + cycle detection via `ast`),
  `citation_verifier` (check cited quotes against their source text), `anki`
  (flashcards via the local AnkiConnect add-on — decks/models/find/add_note/
  sync, writes gated by confirm, loopback-only by default), `test_gen`
  (generate a Hypothesis property-test scaffold from a function's signature),
  `semantic_code_search` (rank functions/classes by intent via ast + lexical
  scoring), `lsp_bridge` (cross-language code intelligence over the Language
  Server Protocol — symbols/definition/references/hover/diagnostics against
  host-installed servers: pyright/gopls/rust-analyzer/tsserver/clangd;
  one-shot session per call, deadline-gated stdio), `mutation_test` (plan source mutants a strong suite should catch),
  `constrained_output` (validate/coerce a value to a typed/enum/range/regex
  shape — the guard half of constrained generation), `model3d_inspect`
  (headless 3D-mesh stats — triangle/vertex counts + bounding box for STL/OBJ),
  `synthetic_data` (deterministic synthetic rows from a field spec, json/csv),
  `web_recorder` (generate a runnable Playwright script from a list of browser
  steps — deterministic codegen with escaped literals), `web_archive` (save a
  URL's content locally so research stays reproducible — SSRF-pinned per-hop
  redirect revalidation, 5 MiB cap, sha-dated snapshot ids, list/get over the
  archive), `github_search` (GitHub repos/code/issues search — explicit token
  only, clamped pages, readable rate-limit errors with Retry-After), `a11y_tree` (distill raw
  HTML into a compact accessibility tree — landmarks/headings/links/controls —
  for a 5-10x token cut), `cache_admin` (inspect/purge the
  tool-output cache — stats or targeted purge), `error_patterns` (cluster noisy
  error/log lines into ranked patterns by normalised signature), `container_build` (build a
  container image from a Dockerfile via sandbox-mediated `docker build`), `ai_act_classifier` (EU AI Act
  risk-tier screening for a described AI use-case — prohibited/high/limited/
  minimal + obligations; heuristic, not legal advice), `geofence` (region
  allow/deny policy check — ISO codes or groups EU/EEA/FIVE_EYES, deny-precedence), `two_person_rule` (validate
  dual-control sign-off — distinct approvers, separation of duties, optional roles), `differential_privacy` (Laplace
  mechanism for (epsilon)-DP noisy counts/sums on published stats), `watermark_detector` (find hidden
  text watermarks/steganography — zero-width, tag chars, variation selectors, homoglyphs), `privacy_budget` (account a
  user's differential-privacy budget — remaining epsilon + allow/deny a query),
  `collusion_detector` (flag collusion between independent swarm agents —
  op=scan: echoed reasoning + rubber-stamping in messages; op=detect:
  voting-collusion blocs whose agreement defeats independent-quorum
  guarantees), `coordinated_disclosure` (run a CVD process offline —
  op=status over a record set flags EMBARGOED/DUE_SOON/OVERDUE/PATCHED/
  DISCLOSED per report with per-severity policy, or checks one report's
  OPEN/EXPIRED window; op=advisory renders the advisory block),
  `capability_delegation` (validate a
  delegation graph for privilege escalation — fixpoint from root capabilities),
  `capability_delegation_graph`
  (static analysis over capability delegations — cycles, privilege escalation,
  transitive holders), `agent_identity` (per-agent stable id + HMAC sign/verify),
  `risk_tier` (score an agent goal LOW/MEDIUM/HIGH from operational signals —
  shell/secrets/PII/spend/irreversibility — for gating), `bias_eval` (group-
  fairness metrics — four-fifths rule, demographic-parity and equal-opportunity
  differences from per-group outcome counts), `decision_explainer` (per-factor
  contribution breakdown for an additive/scorecard decision — right-to-explanation),
  `governance_explainer` (explain a governance ALLOW/DENY/REQUIRE_HUMAN decision —
  the rule that fired + plain reason + the counterfactual that would change it;
  GDPR Art. 22 / AI Act Art. 14, re-runs the real policy evaluator),
  `voice_command_grammar` (match a transcribed utterance to an intent + slots
  from a {slot}-template grammar — no model round-trip for high-frequency
  commands), `what_changed_digest` (added/removed/changed digest between two
  snapshots, optional signed numeric deltas), `gui_element_memory` (offline
  store of GUI element locators keyed by app/screen/name for computer-use),
  `adversarial_eval` (score a red-team batch — confusion matrix, recall/
  precision, and the missed-attack list that gates red-team CI),
  `trace_compare` (diff two replay traces step by step — first divergence,
  matched prefix, per-step field diffs), `latency_heatmap` (tool × latency-band
  shaded grid + p50/p95 per tool), `tool_call_inspector` (per-tool call count,
  error rate, avg/max latency, HIGH-ERROR flags from a tool-call log),
  `rectification` (validate/apply GDPR Art. 16 field corrections under a
  mutability policy — auditable diff + corrected record), `anomaly_scan` (flag
  cross-run metric outliers via the robust median/MAD modified z-score),
  `k_anonymity` (check a released dataset for k-anonymity + optional l-diversity
  — quasi-identifier group sizes and sensitive-value diversity), `retention_check`
  (audit records against a data-retention policy — flag over-retained and
  no-policy records by category/age; GDPR storage limitation), `redact`
  (**provable redaction**, `provable_redaction.py`: redact secrets/PII to a
  fixpoint then re-scan to *prove* the output carries none — composes the
  secret + PII detectors, and reports the residual gap instead of a false
  guarantee when a bound is hit), `breach_notification`
  (GDPR Art. 33/34 72h breach-notification timer — DUE/OVERDUE/ON_TIME/LATE +
  Art. 34 high-risk reminder), `data_minimization` (flag fields collected beyond
  a purpose's allowlist + missing required fields; GDPR Art. 5(1)(c)),
  `consent_check` (evaluate consent records for active validity — granted /
  withdrawn / expired per purpose, latest grant governs; GDPR Art. 7),
  `kv_cache_offload` (LRU KV-cache keep/offload plan under a memory budget),
  `otel_semconv` (map span attributes to OpenTelemetry semantic-convention
  keys), `payload_compress` (zlib compress/round-trip ratio helper),
  `compaction_classifier` (rule-based compaction-strategy picker),
  `capability_revocation` (transitive revocation over a delegation graph),
  `memory_safe_parse` (size/depth/item-bounded JSON/CSV parse that never raises
  on hostile input), `misuse_removal` (remove flagged leaderboard entries +
  tombstones), `consent_ergonomics` (minimal plain-language consent prompt +
  risk badge), `skill_distill_v2` (extract a reusable skill spec from a
  successful trace), `observation_channel` (merge multi-agent observations into
  a time-ordered feed), `marketplace_moderation` (APPROVE/REVIEW/REJECT listing
  scan), `channel_autoroute` (pick the best channel for a message by rules),
  `jwt_inspect` (decode + validate a JWT offline — claims, exp/nbf, and
  HS256/384/512 HMAC signature verification; flags alg=none), `rbac_check`
  (evaluate an RBAC authorization decision — role inheritance + '*'/'prefix:*'
  wildcards, ALLOW/DENY with the granting role), `cidr_check` (firewall-style
  ordered CIDR access-control for an IPv4/IPv6 address — first match wins),
  `semver_check` (does a semver version satisfy a constraint — comparator sets,
  caret/tilde ranges, prerelease ordering).
- **Extensibility** — `@tool` decorator (`tools/decorator.py`): turn a typed
  function into a registered Tool with a signature-derived JSON Schema, no
  boilerplate. **TypeScript plugin SDK** (`sdks/plugin-ts/`,
  `@maverick/plugin-sdk`): author a tool in TypeScript with
  `defineTool`/`servePlugin` over a versioned NDJSON stdio protocol
  (`maverick-plugin/1`: `--describe` manifest, `{id,tool,args}` →
  `{id,result|error}`); the host (`ts_plugin_host.py`, `[plugins] ts =
  [["node", "/path/plugin.js"]]`, wizard step included) loads the manifest
  into regular Tools with a persistent scrubbed-env child, per-call timeout,
  one crash-restart, and the no-shadowing rule built-ins enjoy. A **gRPC
  plugin host** (`grpc_plugin_host.py`, proto `grpc_api/plugin_host.proto`,
  `[plugins] grpc = [{target, command}]`) carries the same contract over gRPC
  for any language: Describe → Tools, Call with a deadline, scrubbed-env spawn,
  reconnect/respawn-once.
  **Retrospective generators (time-gated runs)** — the 2-/36-month
  retrospectives ship as period generators the operator runs at the mark:
  `safety_report` (safety), `benchmark_retrospective` (perf), and
  **`ux_retrospective.py`** (`python -m maverick.ux_retrospective`): goal
  volume/outcomes, top task verbs, channel mix, approval friction over a
  window, plus a **reset worksheet** whose questions are answered from the
  data rows (zero-use surfaces to cut, friction concentrations, dominant
  verbs); empty sections say so.
  **AI Act conformance package** (`ai_act_package.py`, `python -m
  maverick.ai_act_package [-o out.md]`): assembles the Art. 11 / Annex IV
  technical-documentation skeleton from the deployment's *recorded* posture —
  the Annex III risk self-assessment, Art. 14 oversight measures (consent
  mode, capability enforcement, delegation, killswitch), Art. 12 logging
  (audit signing, retention, day-files present), Art. 15 evidence (red-team
  gate, shield calibration, reliability cert when present), Art. 50
  transparency wiring — sections without evidence say so, and the items only a
  provider can complete (intended purpose, conformity route) are an explicit
  checklist, not fabricated prose.
  **Adversarial-prompt corpus release** (`maverick_shield/corpus_release.py`,
  `python -m maverick_shield.corpus_release`): turns the CI red-team corpus
  into a versioned, validated, integrity-pinned artifact — content-hash
  version, SHA-256 over canonical rows, license + intended-use ("NOT a
  training set for attack generation"), and a provenance gate that REFUSES a
  release containing secret-shaped content or identity PII (fixture IPs in
  attack samples are allowed and disclosed); writes corpus + MANIFEST +
  README.
  **Security backports + LTS machinery**
  ([`docs/security-backports.md`](../docs/security-backports.md) +
  `backport_tool.py`, `python -m maverick.backport_tool scan|plan|check`):
  the policy (what qualifies, the `lts/<v>` 2-year safety-fix branch, 7-day
  SLA) made executable — `scan` finds security-marked commits, `plan` lists
  the ones not yet on the LTS branch (patch-id matched, so a cherry-picked
  twin isn't re-flagged), and `check` exits non-zero when an eligible fix is
  past the SLA — read-only; cherry-picks/pushes stay maintainer acts.
  **Formal verification of the sandbox interface (TLA+)**
  ([`docs/specs/tla/`](../docs/specs/tla/README.md)): `SandboxInterface.tla`
  models the chokepoint as a state machine and TLC-verifies — for all
  interleavings — no silent downgrade to host exec under a container backend,
  scrubbed child env always, refused-never-ran, bounded execution budget, and
  every command eventually terminal (checking the liveness property surfaced a
  real modelling subtlety: dispatch fairness, now explicit). Verified: 982
  states, no errors; reproduction steps in the README.
  **Sigstore keyless signing** (`sigstore_signing.py`, `[sigstore]` extra,
  `python -m maverick.sigstore_signing sign|verify`): sign skill/plugin
  artifacts with sigstore's keyless flow (OIDC identity) into a
  `.sigstore.json` bundle; verification pins the identity+issuer pair and
  fails CLOSED on a missing bundle, wrong identity, or absent install —
  identity-based signing alongside the key-based skill signing and the
  self-hosted plugin CA.
  **Federated shield rule updates** (`shield_updates.py`, opt-in `[shield]
  federated_updates` + `update_url`/`update_pubkey`, wizard step included):
  pull-based publisher-signed rules bundles (Ed25519 over canonical JSON);
  unsigned, mis-signed, tampered, downgraded, or un-anchored bundles are
  refused, and a verified bundle stages `shield_rules.json` (0600) atomically —
  the kernel never imports the shield itself (rule 1).
  **Annual safety report generator** (`safety_report.py`, `python -m
  maverick.safety_report --since --until`): aggregates what the deployment
  actually recorded — shield blocks, capability denials, killswitch
  activations, consent decisions, erasure requests, red-team/calibration
  results when present — into a markdown report with explicit reporting-period
  and data-available sections; empty sections say so, nothing fabricated.
  **eBPF syscall monitor** (`ebpf_monitor.py`, opt-in `[ebpf_monitor] enable`,
  wizard step included, `python -m maverick.ebpf_monitor program|run`):
  generates a bpftrace program tracing execve/connect/openat for the agent's
  PID tree with a validated suspicious-syscall watchlist, supervises it via an
  injected runner, parses events, and alerts on watchlist hits — generator/
  parser/supervisor fully offline-tested; the live attach needs root +
  bpftrace and refuses politely otherwise.
  **Memory-safe parsing of untrusted bytes** (`parser_isolation.py`, opt-in
  `[security] isolate_parsers`): the parsers fed attacker-controllable bytes
  (PDF via pdfplumber/pypdf, images via Pillow) are C-extension-backed — a
  memory-safety bug there is an in-process foothold. The whitelisted-parser
  inventory (`PARSERS`, the policy in code) routes them through a
  secret-scrubbed child process: a segfault on hostile bytes kills the child,
  never the kernel, and an exploited child holds no provider keys; size caps
  enforced before the child sees data, hard timeout, and on child death the
  consumer REFUSES rather than re-parsing the same bytes in-process (wired
  into `read_pdf`). Off by default — in-process behavior unchanged.
  **Plugin signing CA** (`plugin_ca.py`): a self-hostable Ed25519 certificate
  authority for plugin/skill artifacts — the in-house counterpart to sigstore's
  keyless flow. An org runs its own root (`init_root`, keys 0600 under
  `keys/plugin_ca/`), issues publisher certs (`issue`, expiring, serial'd),
  maintains a CA-signed revocation list, and every install verifies the
  two-link chain offline (artifact sig → publisher key; publisher cert → root)
  **fail-closed**: tampered artifact/cert, wrong root, expired or revoked cert,
  or a missing piece all refuse; an unverifiable CRL never silently
  un-revokes.
  **Plugin compatibility matrix** (`plugin_matrix.py`, `python -m
  maverick.plugin_matrix [--ci]`, wired as a CI lint step): one table per
  installed entry point — dist, declared API major, loadable/deprecated/
  refused, allowlisted, permissions granted — with a CI gate that fails when
  any *enabled* plugin is API-incompatible, so an upgrade dropping an API
  major can't ship silently against plugins still pinned to it. Pure
  inspection (nothing imported or executed).
  **Plugin API v2 (released)** — `MAVERICK_API_VERSION = "2"` with
  `SUPPORTED_API_MAJORS = (1, 2)`: v1 plugins keep loading through a
  deprecation window (warned in manifest validation), declared v3+ is
  refused; release notes in [`docs/plugin-api-v2.md`](./plugin-api-v2.md)
  (structured channel `Reply`, enforced manifest permissions, lockfile,
  isolation, TS plugins).
  **Plugin sandboxing** — opt-in
  `[plugins] isolation = "subprocess" | "subinterpreter"`
  (`plugin_isolation.py`): discovered plugin tools keep their schema but their
  *calls* run in a fresh CPython subinterpreter (fault/state isolation — a
  plugin that pollutes globals or leaks can't touch the host) or a
  secret-scrubbed child process (stronger: separate address space, survives a
  segfaulting plugin, no host env secrets); values pass by baked literals,
  never argv. **Plugin telemetry (opt-in, local-only)** —
  `[plugins] telemetry = true` counts plugin-tool invocations to a local JSON
  tally (nothing leaves the machine); `maverick plugin stats` shows
  calls/last-used per tool for allowlist pruning; composes with isolation so
  isolated calls count too. **Plugin version-pinning lockfile** —
  `maverick plugin lock` records each plugin distribution's version to
  `plugins.lock.json`; discovery verifies against it per `[plugins]
  lock_policy = "off"|"warn"|"enforce"` (`plugin_lock.py`: enforce refuses a
  drifted or unpinned dist — that plugin only — warn logs once per dist;
  `maverick plugin verify` reports drift/missing/unpinned and exits 1 on
  failure). **Hot plugin reload** — `maverick plugin reload <dist>`
  (`plugins.reload_plugin`): drop a plugin distribution's modules from the
  import cache so the next discovery pass re-imports the current code on disk;
  the edit-reload-retry loop for plugin authors, same allowlist/permission
  gates on re-import.

## Channels

17 wired channels (`packages/maverick-channels/`): Telegram, Discord, Slack,
Signal, Email, Matrix, Bluesky, Mastodon, Voice (Twilio), WhatsApp (Twilio),
**WhatsApp Cloud API** (`whatsapp_cloud.py`: Meta's first-party Graph API —
GET verification handshake, constant-time `X-Hub-Signature-256` HMAC,
sender allowlist, atomic message-id dedup claim, chunked outbound; no Twilio
middleman), SMS, iMessage
(macOS), **IRC** (channels + DMs, TLS), **Threads** (`threads.py`: Meta's
Threads API — polling adapter by design since webhooks are partner-gated;
author allowlist, claim-first dedup that fails CLOSED because a polling
adapter re-sees replies, two-step publish with 500-char chunking),
**RCS** (`rcs.py`: Google RCS Business Messaging for approved RBM agents —
Pub/Sub or direct envelopes, constant-time clientToken verify, MSISDN
allowlist, service-account Bearer auth with cached refresh), and a
**glasses/wearable** adapter
(Even Realities G2 "bring your own agent" bridge: the ack-then-run pattern that
answers quick utterances on the HUD within the device deadline and runs long
tasks in the background, delivering the result to a secondary channel). Rich
formatting + dedup + per-channel authz. **Reply threading** — inbound messages
carry their platform `message_id` and adapters expose `send_threaded`
(Slack `thread_ts` behind opt-in `[channels.slack] thread_replies`; Telegram
`reply_to_message_id`; base falls back to a plain send) so long-running
answers land under the message that asked. **Email v2** adds IMAP IDLE (push
instead of poll) + conversation threading from Message-ID/In-Reply-To/References
(`email_v2.py`). **Discord Stages voice v2** (`discord_stages.py`): drive Maverick from a
Stage channel — per-speaker utterance assembly over an injected transcriber,
optional wake-word gating, replies spoken when the bot holds a speaker slot
and degraded to stage-chat text when it doesn't (or TTS fails), and stage
etiquette built in: the bot only *requests* a speaker slot, never
self-promotes (a human moderator approves). Every Discord interaction sits
behind an injected seam so the session logic is fully offline-tested; the
heavy voice binding (discord.py voice + PyNaCl) plugs into the same seam.
**KaTeX/Mermaid rich render** (`rich_render.py`, opt-in
`[channels] rich_render`): replies carrying display math or ```mermaid fences
are rendered into a standalone HTML artifact (KaTeX/Mermaid in-page, escaped
`<pre>` source as the no-JS fallback) under `data_dir("rich_render/")`;
`RichRenderChannel` wraps any adapter — an injectable `deliver` hook ships the
file on platforms that can, otherwise the path is appended — and plain
messages pass through byte-identical. **Channel SDK v2** (RFC 0001 C2,
`base.py`): handlers may return a structured `Reply` (text + attachments +
thread_ref) instead of bare `str` — `as_reply` is the v1 shim (bare `str`
accepted through the deprecation window), `Channel.dispatch`/`dispatch_text`
normalize either contract, and all 18 in-tree adapters route through the
dispatch path so a v2 handler works everywhere unchanged.

## Sandboxes

7 run-to-completion backends (`sandbox/`): local subprocess, Docker, SSH, Podman,
devcontainer, Firecracker microVM, Kubernetes. Selected via `[sandbox] backend`.
**Modal sandbox backend** (`sandbox/modal_backend.py`, `[sandbox] backend =
"modal"`, `[modal]` extra): run agent shell in ephemeral Modal cloud sandboxes
(per-exec container, image/cpu/memory/timeout plumbed, torn down after the
command) — burstable remote compute without running a cluster; infra errors
surface as a failed command, never a kernel crash. The Cloudflare-Workers half
of the roadmap pair was declined for shell semantics (Workers run JS/WASM
request handlers, not processes; the honest Workers story is the self-hosted
relay reference + `wasm_run`).
**Sandbox SDK v2** (`sandbox/sdk.py`, `SDK_VERSION = 2`): the formal backend
contract — a `runtime_checkable` `SandboxV2` protocol (`workdir` +
`exec(cmd, timeout=None)`), declared optional capabilities
(`capabilities()`), a static `conformance()` checker, and **entry-point
loading** (`[sandbox] backend = "ep:<name>"` resolves the
`maverick.sandboxes` group, instantiates with `[sandbox] options`, and
refuses a non-conformant backend rather than falling through to unsandboxed
local exec) — so third parties ship backends without forking. All in-tree
backends conform (the check surfaced and fixed a real gap: devcontainer
lacked `workdir`, crashing path-confined tools).
**gVisor** is offered as a backend (`backend = "gvisor"`): Docker with the
`runsc` runtime (`--runtime=runsc`), interposing a userspace application kernel
between a possibly prompt-injected agent and the host — stronger isolation than
seccomp + dropped capabilities alone. It reuses every Docker knob (image,
network, memory/pids/cpu caps, non-root); `[sandbox] runtime` overrides the
runtime for a custom registration. **Warm-container reuse** (`[sandbox]
reuse_container`, default off): instead of a fresh `docker run --rm` per
command (a cold start each time), keep one container alive and `docker exec`
into it, so the 2nd..Nth command in a run skip container startup; torn down on
`close()`.

## LLM providers & routing

12 providers, routable per role (`llm.py`): Anthropic, OpenAI, OpenRouter,
Ollama, Gemini, DeepSeek, Bedrock, Azure, xAI, Moonshot, TGI, vLLM (generic
OpenAI-compatible via `base_url`). Cost-aware routing (`cost_router.py`) with **per-role
policies** (`[routing.roles.<role>]`: provider allow/deny, cost ceiling, tier
floor) and provider failover (`provider_failover.py`) with a **policy engine**
(`failover_policy.py`: error-class gating — auth fails fast, 429/timeout/5xx
fail over — plus per-model cooldowns), all opt-in. **Local-first routing**
prefers a reachable local model before remote (`provider_local_first.py`);
**energy-aware routing** downgrades to a cheaper model on low battery
(`energy_aware_router.py`); both opt-in and default-OFF. **Cost-aware routing
v3** (`cost_router_v3.py`) layers a contextual **epsilon-greedy bandit** on top
of v2: it learns reward-per-dollar per coarse task class (role + tier) and
reorders *only within* the healthy/affordable arm set v2 already produced —
never routing somewhere v2 rejected, falling back to v2 on a cold context. The
learned table persists atomically (`router_bandit.json`, 0600); opt-in via
`[routing] bandit` and default-OFF.

**Public perf dashboard** (`GET /perf` + `GET /api/v1/perf` on the
dashboard): one page/JSON face for the perf story — the perf-SLA checks
measured live on the host (in a worker thread, against the published
thresholds), recorded benchmark history with short-window regression
verdicts, and the longitudinal era retrospective; sections with no recorded
data say so. **Longitudinal benchmark retrospective** (`benchmark_retrospective.py`,
`python -m maverick.benchmark_retrospective`): the multi-year companion to
continuous benchmarking — slices the FULL recorded score history into calendar-
quarter eras and reports per-era medians, era-over-era movement, best/worst
eras, net first→last change, and a least-squares trend verdict per benchmark;
the report states its actual coverage span (the intended cadence is the 3-year
mark, run over whatever the deployment recorded). **Public performance SLA** ([`docs/perf-sla.md`](./perf-sla.md) +
`perf_sla.py`, `python -m maverick.perf_sla --ci`): the published, measurable
performance properties each release certifies — tool-dispatch overhead,
compaction latency, world-model hot-path read/write p95 — measured against the
REAL code paths and compared to the published thresholds (changing a threshold
is changing the SLA); rows that need concurrency/fault drills delegate to the
reliability cert. **Reliability certification** (`reliability_cert.py`,
`python -m maverick.reliability_cert`): a reproducible, evidence-backed
self-certification composing the shipped drills — chaos game-day, the plugin
reliability drill, a 16-writer WAL contention probe — into a certificate JSON
(environment fingerprint + per-check verdicts), Ed25519-signed with the audit
key when available and only issued for a passing run.
**Deprecation registry + sunset gate** (`deprecations.py`, `python -m
maverick.deprecations [--ci]`, wired into CI): every deprecated path is
declared in one registry (target, replacement, deprecated_in, **remove_in**);
`warn_once` gives call sites a once-per-process DeprecationWarning,
`check_config` lints a loaded config for deprecated keys, and the **sunset
gate** fails CI once the package version reaches an entry's removal version
until the old path and its registry entry are deleted together — so
deprecations can't rot. Seeded with the two live windows (plugin API v1
manifests; bare-`str` channel handlers). **Cache-aware prompt assembly DSL** (`prompt_dsl.py`): a `PromptBuilder` that
tags each segment STABLE (cacheable — system, tool catalog, exemplars) or
VOLATILE (per-request); `assemble()` orders them stable-first and marks the
**cache breakpoint** at the end of the stable prefix so a provider adapter
places `cache_control` correctly by construction (a volatile token early in a
hand-built prompt silently busts the cache for everything after it).
`cache_fingerprint()` hashes only the stable prefix, and `lint_segments` flags
anti-patterns (timestamp/nonce in a "stable" block, volatile-before-stable).
**Critical-path-aware scheduling** (`task_graph.py`):
`remaining_critical_weight()` gives each task its heaviest tail of not-yet-done
work, and `ready_prioritized()` orders the runnable frontier longest-tail-first
(the standard critical-path heuristic — start the work bounding the finish
time before short-tail work); exposed as the `task_graph` tool's `schedule` op.
**Speculative best-of-N with early pruning** (`speculative_best_of_n.py`):
run N attempts but prune at the **first reasoning checkpoint** — each attempt
emits a cheap partial (its plan / first step), an injected scorer ranks the
partials, and only the top `keep` run to completion; the rest are cancelled
before they finish, so the budget concentrates on the strongest candidates
rather than N full runs. Distinct from latency best-of-N (the kill signal is
early *quality*, not time); the scorer only ever sees the cheap partials.
**Fast JSON seam** (`fastjson.py`, opt-in `[perf-fastjson]` extra): a
stdlib-compatible `dumps`/`loads` that prefers **orjson** (~5-10x faster) when
installed and falls back to stdlib `json` otherwise — `dumps` returns `str`,
honors `sort_keys`, and degrades on any value orjson rejects, so it's a safe
drop-in for round-trip/transport paths (wired into the tool-output cache
snapshot). Deliberately NOT used for cache keys/signatures, where exact bytes
must stay backend-stable. **Self-tuning budgets — online auto-apply**
(`self_tuning_budget.py`, opt-in `[budget] self_tuning`; the auto-applying
companion to the advisory `maverick budget tune` / `budget_tuner.py`, which
only *recommends* a cap for a human to set): learns a default spend cap *per
coarse task class*
(e.g. the goal's leading verb) from how much past runs of that class actually
cost — a bounded reservoir per class, a high-quantile × margin suggestion
clamped to [floor, ceiling]. Wired as the **lowest-precedence** layer of
`budget_from_config` (an operator's configured `max_dollars` always wins) and
fed by the orchestrator's per-run cost recording; returns nothing until a
class has enough samples, so it never lowers safety on a guess. Off by
default.

**Local-runtime launcher + autoscaler** (`local_runtime.py`, opt-in
`[local_runtime]`, `maverick local-runtime plan`): composes the correct
engine flags for **vLLM / TGI / llama.cpp** from config — continuous
batching (`max_concurrent`/`max_batch_tokens` → `--max-num-seqs` /
`--max-batch-total-tokens` / `--parallel --cont-batching`), **persistent
KV-cache** (`kv_cache = "persistent"` → `--enable-prefix-caching` /
`PREFIX_CACHING=1` / `--prompt-cache FILE --prompt-cache-all`), **KV offload
to disk** (`kv_offload_dir`; llama.cpp persists, vLLM gets `--swap-space`,
others warned honestly), and **mixed precision** (`precision =
fp16|bf16|int8|int4` → `--dtype`/`--quantization`/quant-GGUF guidance) — plus
a queue-depth **autoscaler** (min/max replicas, hysteresis, injectable
spawn/stop/probe/clock, round-robin `endpoints()` for the router). Default
OFF; the launcher refuses to start until `[local_runtime] enabled = true`
(wizard step included); no model is ever defaulted.

**Per-role reasoning effort** (`effort.py`) — the biggest cost/latency lever on
Opus 4.7/4.8: model-gated `output_config.effort` tiered by role (critical roles
`high`, bulk roles `medium`/`low`), opt-in via `[effort] enabled`.

**Prompt caching** (`providers/anthropic_provider.py`) — frozen system prompt +
name-sorted tool catalog + a stable-history-prefix breakpoint (with a secondary
breakpoint on long turns for the 20-block lookback), 1h TTL; opt-in **cache
pre-warming** (`max_tokens=0` prefill at orchestrator start) and a
`maverick_llm_cache_tokens_total` hit-rate metric.

## MCP & agent interop

- **MCP server** (`packages/maverick-mcp/`) — stdio JSON-RPC **and** Streamable
  HTTP transport; tool `outputSchema`, resource subscriptions.
- **Registry publishing** (`maverick_mcp.publish`, `python -m
  maverick_mcp.publish [--validate]`) — emit the reverse-DNS-namespaced
  `server.json` an operator submits to an MCP registry (name / version /
  source repo / pypi package + stdio transport), built from the server's own
  `SERVER_NAME`/`SERVER_VERSION` with a `validate` lint; tools stay
  runtime-discovered (`tools/list`), never frozen into the manifest.
- **Elicitation** — client inbound (policy + shield); server outbound **form
  mode** and **URL mode** (https-only, shield-screened prompt, action-only
  response so secrets never transit the model).
- **MCP Tasks (2025-11-25)** — task-augmented `tools/call` → `CreateTaskResult`,
  background worker, `tasks/get|result|cancel|list`, status notifications.
- **MCP client** (`mcp_client.py`) — consume remote HTTP servers; **OAuth 2.1
  client-credentials and authorization-code + PKCE** grants (`mcp_oauth.py`).
- **MCP registry** (`mcp_registry.py`) — `maverick mcp-registry browse/add/...`.
- **Federated marketplace indexes** — `[catalogs] indexes` takes any number of
  index base URLs; catalogs merge across them (earlier indexes win on name
  collision, malformed entries skipped per-entry) — run your own index next
  to the community one (`catalog.py`, pinned by test).
- **IDE protocol unification** — one MCP server (stdio + Streamable HTTP) is
  the editor protocol: any MCP-speaking editor (VS Code, JetBrains, Zed,
  Cursor) drives Maverick through it; the editor-specific packages
  (`apps/vscode-extension`, `apps/emacs`, `apps/nvim`) are thin CLI fronts,
  not parallel protocols.
- **A2A** (`a2a.py`, `a2a_tasks.py`) — Agent Card discovery + delegation, with
  the **interop consuming half** (`validate_agent_card` spec-shape lint,
  `parse_remote_card` normalization that refuses a non-conformant card before
  anything delegates against it) proven both ways by interop tests: Maverick's
  own card passes its own validator, and third-party-shaped fixture cards
  (rich + minimal) parse correctly.
- **Swarm federation** (`federation.py` + `grpc_api/federation.proto`,
  protocol `maverick-federation/1`, opt-in `[federation] enabled` + `peers`):
  delegate goals across *sovereign* swarms (each with its own world DB —
  distinct from `RunGoal`'s shared-DB offload). `Hello` exchanges A2A agent
  cards (non-conformant peers refused), `DelegateGoal` carries a correlation
  id + required tools resolved **narrow-only** via capability boot negotiation
  (an ungrantable requirement refuses the delegation), auth is a constant-time
  shared token that *identifies* the caller from local config (wire names
  never trusted; fail-closed), and **both halves record reciprocal audit rows**
  in exactly the convention `audit/federation.py` cross-verifies — a dropped
  half is detectable. The protocol layer runs over any `call(method, payload)`
  transport; the gRPC binding is a thin `[grpc]` adapter (live-smoked).
- **gRPC API v1 — stable** (`grpc_api/maverick.proto`, package `maverick.v1`;
  contract gate `grpc_api/contract.py` + committed golden
  `maverick_v1_contract.json`, wired into CI): additive changes pass; removing/
  renaming a service/rpc/message/field, renumbering or retyping a field,
  changing an rpc's streaming shape, or reusing a removed field number fails
  the gate — a breaking change requires a `maverick.v2` package. The gate is a
  dependency-free proto parser, so it runs in CI without grpcio.
- **gRPC dispatch** (`grpc_dispatcher.py`, opt-in `[grpc_dispatch] target`)
  — execute goals on a remote Maverick worker over gRPC: a `RunGoal` RPC runs
  an existing goal row to completion (API and worker share the Postgres world
  DB, same contract as the arq queue), and `GrpcDispatcher` plugs into the
  runner's Dispatcher seam with no caller changes; queue backend wins when
  both are configured; unreachable worker degrades to could-not-start, never
  an exception.
- **gRPC API** (`grpc_api/`) — typed, streaming surface for driving the runtime
  from any language: `StartGoal` / `StreamEpisode` (server-stream of episode
  events) / `Cancel` / `GetStatus`. Behaviour lives in a transport-agnostic
  `GoalService`; the gRPC shim compiles stubs on demand from the bundled
  `maverick.proto`. Behind the `[grpc]` extra; run via `python -m maverick.grpc_api`.
- **Cross-language quickstarts** — TypeScript, Go, Rust, C#, Java (`docs/clients/`).
- **LangChain / LangGraph interop** (`langchain_adapter.py`, `[langchain]` extra)
  — expose the Maverick swarm as a LangChain `StructuredTool`, and wrap any
  LangChain `BaseTool` as a Maverick tool. **AutoGen + CrewAI adapters**
  (`agent_framework_adapters.py`): the same two directions for both frameworks
  — Maverick as an AutoGen `FunctionTool` (or a dependency-free typed
  callable) and as a CrewAI `BaseTool`; `wrap_autogen_tool` /
  `wrap_crewai_tool` adapt their tools into Maverick `Tool`s (duck-typed,
  lazy imports, actionable install hints).
- **MCP-client language analytics** (`mcp_analytics.py`) — opt-in, consent-gated
  tally of client language (from the User-Agent) that feeds the language-bindings
  decision gate (`non_python_share()`); off by default, consent step in the
  installer wizard (`maverick init` → Analytics).

## Safety & security

- **Shield** at 3 chokepoints (input / tool-call / output); built-in rule set
  fail-open if the SDK isn't installed.
- **Floors** — secret detector, PII detector, jailbreak heuristics, unicode /
  zero-width filter, remote-content scan, output-policy classifier
  (regurgitation + refusal-leak), **phishing-content detector** (credential-harvest
  + deceptive-link heuristics, composed into `Shield.scan_output`),
  **operator-defined constitutional rules** (custom regex policy via `[safety]
  constitution`, `maverick_shield/constitutional.py`),
  Constitutional-Classifier-v2 cascade (`safety/`, `maverick_shield/`),
  **voice safety pass** (`safety/voice_safety.py`): transcript screen for
  wake-word stuffing + spoken role-switch before an utterance drives the
  agent, and redact-before-speak (secrets/PII never read aloud) wired into
  the `speak` tool, **image-content classifier**
  (`tools/image_content_classifier.py`): model-free pixel heuristics — skin-
  tone ratio (NSFW pre-filter routes to human review), brightness extremes,
  photo-vs-graphic, dimension sanity — file decode via Pillow or raw pixels
  with no imaging dep.
- **Confidential-compute detection** (`confidential_compute.py`, `maverick
  confidential-compute`) — detects whether the process runs inside a hardware
  confidential VM (AMD **SEV-SNP** / Intel **TDX**) from the standard guest
  indicators (`/dev/{tdx,sev}-guest`, firmware sysfs, CPU flags), so a regulated
  deployment can verify (and gate on) hardware memory encryption; exits non-zero
  when not confidential.
- **Air-gap preflight** (`air_gap.py`, `maverick airgap check`) — verifies a
  deployment has no outbound path in *Maverick's own config*: a remote model
  provider, a non-deny-all egress policy, or a sandbox with network access — and
  exits non-zero on any finding so it can gate a deployment. (OS-level air-gap
  is the operator's job; this catches the application-layer leaks.)
- **Shield ensemble** (`shield_ensemble.py`) — a **deny-wins detector ensemble
  with explainable reason codes** (the Shield-v3 framework): pluggable members
  screen a blob (injection via the jailbreak heuristics, exfil via the secret
  detector, PII via the PII detector) and any one firing blocks, with a
  structured `reason_codes` list saying *which* detector objected and *why*
  rather than an opaque refusal. A member is a small pluggable unit, so a
  trained small-model classifier drops in behind the same interface later.
- **Access control** — tool ACLs, consent prompts + a persistent **consent
  ledger** (`safety/consent.py`; `MAVERICK_CONSENT_MODE` =
  auto-approve / auto-deny / ask / dashboard), capability tokens
  (`capability.py`), role-based access control over capabilities, the
  `self_capability` self-report tool, **capability boot negotiation**
  (`capability_boot.py`): a spawned child may declare a narrower requested
  scope (tools/max_risk/paths/hosts), and `negotiate_boot` resolves it against
  the parent grant narrow-only (never gaining authority the parent lacked),
  records the handshake, and fails the spawn when a *required* capability
  isn't grantable, **capability revocation**
  (`revocation.py`, `maverick capability revoke/unrevoke/revocations`): kill a
  still-valid grant before its TTL — the tool chokepoint denies a revoked
  principal's next call, and the list is re-read on change so a revoke in
  another process reaches agents already mid-run; `revoke_subtree` walks the
  delegation graph to revoke a principal and every descendant it spawned
  (fail-open, like the opt-in capability layer), **approval delegation rules**
  (risk/scope-based routing, `approval_delegation.py`), per-tool network egress
  policy (`sandbox/network_policy.py`), `maverick whoami`.
- **Out-of-process model proxy** — `model_proxy.py` (`python -m
  maverick.model_proxy`, `[model_proxy] upstream/auth_style`): a separate
  process holds the provider key (from its **own** env, `MAVERICK_PROXY_KEY`)
  and the agent points a provider's `base_url` at it. The agent process never
  holds the credential — a prompt-injected agent can't exfiltrate a key it
  doesn't have. The proxy strips the client's auth + hop-by-hop headers,
  injects the real key in the upstream's scheme (bearer / `x-api-key`), and
  forwards only to its single configured upstream host (an SSRF guard).
- **Audit & compliance** — signed append-only audit log (`maverick audit verify`), **federated
  audit-log verification** (`audit/federation.py`) — over a set of nodes/tenants
  whose signed logs reference each other (delegation, A2A handoff), confirms
  every cross-node reference is *reciprocated* (a node can't drop its half to
  hide an action) on top of each node's own chain/anchor check; an
  unreciprocated or forged link is reported with the missing counterpart,
  date-windowed **SIEM export**, encryption-at-rest (`crypto_at_rest.py`,
  `maverick encryption migrate`), SOC2 readiness (`soc2.py`), DSAR (`dsar.py`),
  **differential erasure verification** (`erasure_verify.py`, `maverick
  erase-verify`) — a right-to-erasure *proof*: reuses the DSAR export (whose
  subject-matching is guaranteed to agree with the erase path) to assert zero
  residual records across every store after `maverick erase`, with a
  before/after `differential` that confirms the erase actually removed data,
  **data-retention enforcement** (`audit/retention.py`, opt-in `[retention]`
  config, `maverick retention enforce [--dry-run]`) — prunes audit files,
  `episodes`/`goal_events` rows, **and the usage-ledger cost buckets**
  (`usage_days`: the per-principal `(principal, day)` chargeback tally accrues
  forever otherwise),
  per-run file-write + tool quotas, `maverick compliance --strict`, CycloneDX
  SBOM in CI.
- **Compliance mode profiles** — `[compliance] profiles = ["hipaa"]` turns on
  a cross-domain runtime posture (`compliance_profiles.py`): **HIPAA mode**
  asserts the 45 CFR Part 164 safeguards, names the protection floors it
  requires (PII redaction, encryption-at-rest, egress lock, audit), and folds
  a require-human-on-high-risk policy into the live governance policy
  (strictest-wins, via the same union the finance regimes use). Inert when
  unset — default behavior is unchanged.
- **Refusal calibration** (`safety/refusal_calibration.py`) — score
  {prompt, should_refuse, refused} samples into over/under-refusal rates with
  configurable ceilings and CALIBRATED/OVER/UNDER verdicts; deterministic
  `is_refusal` completion detector.
- **Shield call rate-limit per goal** (`safety/shield_rate_limit.py`) — opt-in
  `[safety] shield_rate_limit = "100/60"` sliding-window token bucket per goal;
  throttling SKIPS the scan fail-open (the shield never blocks the agent by
  being busy), with once-per-window suppressed-call alerts.
- **Model cards per LLM** (`model_cards.py`) — aggregate the deployment's own
  usage ledger into per-model cards (roles, calls, tokens, dollars) rendered
  as markdown with a no-vendor-claims disclaimer; duck-typed world adapter.
- **Behavioral diff on upgrades** (`behavioral_diff.py`) — replay a fixed probe
  set before/after a model/prompt change; classify per-probe
  unchanged/minor/major/refusal-flip, PASS verdict gated on flips + major-change
  fraction.
- **Goal risk-tier auto-classifier** (`safety/goal_risk.py`) — deterministic
  low/medium/high scoring of a goal before it runs (money/infra/credential/
  bulk-comms/PII/irreversibility signals, read-only de-escalators, documented
  weights), config floor + require-human mapping for the approval path.
- **Containment mode** (`containment.py`, opt-in `[containment]`) — lock a
  run into no-egress + ephemeral 0700 workspace: composes the registry ACL
  (denies the exfil tools; config *extends*, never replaces the default deny
  set), black-holed proxy env for subprocesses (advisory; the load-bearing
  layer is the ACL + container backends' network deny), cleanup handle.
- **Cryptographic budget receipts** (`budget_receipts.py`) — HMAC-signed,
  hash-chained spend receipts per goal (prev-hash inside the signed payload
  so deletion/reorder is unforgeable; append-only 0600 ledger; refuses to
  mint unsigned), verify + chain verification with break index.
- **Quorum approval for config changes** (`quorum.py`) — N-distinct-approver
  gate over protected config keys (fnmatch patterns; self-approval and
  duplicate approvers refused; required count snapshotted per proposal so
  policy edits can't shrink a pending quorum; TTL-pruned proposals).
- **Capability-leak fuzzer** (`capability_fuzzer.py`) — seeded adversarial
  probes (case/homoglyph/prefix/separator/NUL/glob/long-name) against
  Capability.permits; CI `python -m maverick.capability_fuzzer` exits 1 on
  any leak. Run against the real implementation: **0 leaks in ~2000 probes**.
- **Provider-level cost caps** (`provider_cost_cap.py`, `[budget.provider_caps]`)
  — per-provider dollar ceilings across ALL runs per UTC day/month (the
  Budget caps one run; this caps the provider), atomic ledger, enforce()
  raising ProviderCapExceeded for the LLM path.
- **Supply-chain pinning** (`supply_chain.py`) — pin the deployment's Python
  dependency tree (`write_pins` → 0600 JSON), verify drift/missing/unpinned
  (`verify`/`render` PASS-FAIL), opt-in startup warning via
  `[safety] supply_chain_pinning` (never raises).
- **Crash-only logging** (`crash_only_log.py`) — append-only JSONL safe to
  kill -9 at any byte: one fsync'd `os.write` per record, seq resumes after
  reopen, replay tolerates (and counts) the torn tail vs mid-file corruption,
  gap detection; fsync policy knob for test/throughput mode.
- **Right-to-rectification** (`rectification.py`) — GDPR Art. 16 counterpart
  to DSAR/erasure: find a subject's occurrences across goals/turns/facts
  (snippets), rectify with dry-run default inside one write transaction, and
  a subject-digest audit trail (`rectifications.jsonl`) that never carries
  the old or new value.
- **Honeytoken planting** (`safety/honeytokens.py`) — mint decoy credentials
  (AWS-key-shaped, API-key, passphrase), plant a realistic 0600 secrets file,
  and alert (once per fingerprint) when a decoy value appears in text — alerts
  carry sha-fingerprints, never the live decoy.
- **Public safety bulletin RSS** (`safety_bulletins.py`) — render
  frontmattered bulletin markdown into a standards-shaped RSS 2.0 feed
  (newest-first, malformed bulletins skipped loudly); self-host first: the
  feed is a file you serve, not a hosted service.
- **Tamper-evident screenshots** (`screenshot_seal.py`) — every capture is
  sealed into a per-directory hash-chained, HMAC-signed ledger (replace /
  edit / delete / reorder all detectable; re-capture legitimately
  supersedes); wired into the computer tool's screenshot path, opt-in purely
  by key presence (`[safety] screenshot_key`), best-effort so evidence
  capture never breaks the screenshot the model is waiting on.
- **Red-team CI** — a named CI job (`redteam` in `ci.yml`) runs the labelled
  adversarial corpus (`maverick_shield/redteam_corpus.jsonl`, grow-by-PR)
  through the shield's built-in detector via `python -m maverick_shield.redteam`
  and fails the build on any missed attack or over-blocked benign case.
- **Shield calibration dashboard** — the same runner swept across every block
  threshold yields the operating curve (recall/precision/fp-rate per
  threshold) + per-rule hit counts: `--calibrate` CLI and
  `GET /api/v1/shield/calibration` on the dashboard (auth-gated; operator
  corpus via `MAVERICK_REDTEAM_CORPUS`).
- **Sandbox-escape canaries**, per-tool rate limiter, killswitch.

## Governed agent runtime & onboarding

- **Conversational intake** — interviews a user, collects docs, and proposes a
  domain configuration (intake agent + LLM proposer + `run_intake`).
- **Domain packs** — spawn domain agents from profiles (legal / privacy / generic
  packs) on the sector-seal foundation.
- **Finance suite (Office of the CFO)** — 31 domain packs across 7 towers
  (Controllership, FP&A, Treasury, Tax, Assurance, Procurement, Reporting) + a
  Finance Controller, each a sealed read-only/draft-by-default compartment with
  the "never move money without a human" guardrail. The governance wrapper:
  amount-aware authorization (`[governance] deny_above`/`require_human_above`
  dollar tiers), a segregation-of-duties linter (`maverick finance lint-sod`),
  OFAC/SDN sanctions screening (`screen_sanctions`), finance assessment templates
  (sox_control / fraud_risk / itgc / credit_risk / close_readiness),
  compliance-regime packs (SOX/COSO/GAAP/PCI/GLBA/AML/SEC/IRS, strictest-wins),
  and the `maverick finance status` posture report (`maverick/finance/`).
- **maverick-knowledge** — per-domain vector RAG package backing
  `knowledge_search`; config-selected embedders (`embed.py`): hosted **Voyage**
  (or any OpenAI-compatible endpoint), **Cohere** (`/v2/embed`, typed
  `embedding_types`), local, or deterministic — fails loud rather than silently
  degrading.
- **Reverse-proxy SSO** — trusted forwarded-identity header for enterprise auth.
- **Tenant-aware persistence** — workspaces wall each tenant into
  `~/.maverick/tenants/<t>/` (`workspace.py`, `paths.py`), with a per-tenant
  world DB and `data_dir()`-routed audit / quotas / DSAR / fleets. The shared
  **Postgres** backend (`[world_model] backend = "postgres"`) carries a
  **versioned migration runner** (the world-model `MIGRATIONS` ledger), a
  `tenant_id` on every root table (write-stamped, read-scoped), **tenant-aware
  UNIQUE constraints**, a **strict-isolation mode** (`[world_model]
  strict_tenant_isolation`), opt-in **database-native Row-Level Security**
  (`[world_model] rls` / `MAVERICK_PG_RLS`: a FORCE-RLS policy on every
  tenant-scoped table keyed on a transaction-local `maverick.tenant` GUC, so
  the database — not just the app-layer predicate — enforces the boundary;
  applied by the table owner, enforced for non-superuser connections, validated
  against a live Postgres under a non-superuser role), and an opt-in
  **`psycopg_pool` connection pool** (`[world_model] pool_size` /
  `MAVERICK_PG_POOL_SIZE`) that hands each transaction its own pooled
  connection for horizontal scale (default 0 = the original single-connection
  model, unchanged).
- **Online-migration preflight** — `schema_migrations.py` + `maverick
  schema-plan`: the *operations* view over that ledger. It classifies each
  pending statement `online` (cheap/non-blocking: `ADD COLUMN`, `CREATE INDEX IF
  NOT EXISTS`, FTS rebuild) or `offline` (table rewrite / long write lock),
  `plan(current, target)` lists the pending steps, and `online_only()` gates a
  hot deploy — failing **closed** on any unclassifiable statement so an unknown
  migration is reviewed before it runs against a live, high-traffic world.
- **Process table** — `maverick ps` (unified view of runs/workers).
- **Scheduling** — recurring autonomous goals from a prompt; `worker --once`
  cron-friendly drain (`scheduler.py`, `job_queue.py`, `worker.py`).

## Hosted control plane & multi-tenancy

The backend for running Maverick as a governed, multi-tenant platform (each piece
opt-in; single-tenant/self-hosted deployments are unaffected):

- **Tenant lifecycle / provisioning** — `tenant_registry.py` + `maverick tenant
  create/list/suspend/resume/quota/delete`: a roster of tenants with status,
  plan, and per-tenant daily spend quota; `assert_tenant_active` refuses a
  suspended tenant.
- **Metering → billing & entitlements** — `billing.py` + `maverick billing
  invoice/entitlements`: rate the usage ledger (pass-through+markup or
  token-priced) into per-period invoices; plan → feature/limit entitlements
  (`tenant_entitled`).
- **Per-tenant envelope encryption** — `tenant_kms.py`: a DEK per tenant, wrapped
  by a KMS KEK (LocalKMS default; cloud KMS is a drop-in `wrap`/`unwrap`); one
  tenant's DEK can't open another's data; instant KEK rotation.
- **Per-tenant egress plane** — `tenant_egress.py`: a per-tenant allow/deny
  egress policy composed (AND) with the per-tool policy at the egress chokepoint.
- **Multi-tenant `maverick serve`** — the channel server enforces the tenant
  roster at the door: with per-user tenancy on and tenants provisioned, a
  suspended/unknown tenant's message is refused before any goal exists, and a
  tenant over its provisioned `max_daily_dollars` (`maverick tenant quota`;
  `tenant_over_quota` sums today's tenant-scoped usage ledger across
  principals) is refused until the UTC day rolls. No roster = no-op; registry
  read errors fail soft.
- **Out-of-process execution** — a swappable goal **Dispatcher** (`runner.py`)
  with a **QueueDispatcher** (`queue_dispatcher.py`) that enqueues goals for a
  worker pool (arq adapter behind `[queue]`; `install_from_config` wires it).
- **Isolation test suite** — `tests/test_multitenant_isolation.py` proves the
  tenant walls across the primitives that actually carry tenant data: `data_dir`
  path routing (distinct ids never collide onto one segment), `world_for_tenant`
  DB separation (A's goal invisible to B), per-tenant KMS (a DEK wrapped for A
  does not unwrap under B's AEAD context), and clean `set_tenant`/`reset_tenant`
  scope discipline.

## Evaluation & benchmarks

**Long-running plugin reliability drill** (`plugin_reliability.py`, `python -m
maverick.plugin_reliability`): the plugin counterpart to the chaos game-day —
a host-agnostic sustained-load drill (give it any `call(payload) -> str`)
that injects crashes/timeouts/errors at seeded rates over thousands of calls
and asserts the reliability properties a host must hold: **recovery** (a crash
is followed by a later success — no permanent wedge), **isolation** (a faulted
call never poisons the next), bounded **error rate**, and **no monotonic
memory growth** (a leaking plugin, via an injected sampler). Deterministic;
exits non-zero in `--ci` on any property failure. **Chaos game-day drill** (`chaos_gameday.py`,
`python -m maverick.chaos_gameday`): scripted fault scenarios against the
real retry layer — 20% tool flakes must be absorbed (≤5% surfaced), a total
outage must exhaust retries in bounded attempts (backoff virtualized so the
drill runs in milliseconds), plus a no-chaos control; exits 1 when a
resilience property fails. Standalone drill, not for serving processes.

**Cost/perf release canary** (`release_canary.py`, `maverick canary
record/compare`): snapshot a release's cost/latency/success-rate metrics and,
before shipping the next, compare against the recorded baseline — a
**direction-aware** relative check (lower-is-better for cost/latency,
higher-is-better for success-rate/throughput) that exits non-zero on a
regression beyond tolerance, gating a release the way tests do. Deterministic;
the snapshot store is an atomic JSON keyed by release tag.

**Reproducible benchmark v2** (`maverick.benchmarks.reproducible_v2`, `python
-m maverick.benchmarks.reproducible_v2 run|--verify`): runs a suite under
pinned conditions (seed, model id, prompt-template hash, tool-set hash) and
emits an HMAC-signed `{suite, seed, env_fingerprint, results, aggregate}`
manifest; `--verify baseline current` diffs two runs and names the exact
diverged task on non-determinism. **Marketplace moderation**
(`marketplace_moderation.py`, `python -m maverick.marketplace_moderation
<path>`): static pre-publication checks over a submitted skill/plugin —
manifest completeness, permission-escalation (declared vs used), secret scan
(reuses the secret detector), prohibited patterns, license — with a
strictest-wins approve/flag/reject verdict. **Skill search engine**
(`skill_search.py`, `python -m maverick.skill_search`): zero-dep BM25-lite
ranked search over the local skill library with HF-dataset export/import
(`skills.jsonl`, network via an injected fetcher; pulled skills re-validated
through the skill validator). **Self-hosted relay reference**
(`relay_reference.py`, [`docs/self-hosted-relay.md`](./self-hosted-relay.md)):
the self-hostable inbound-webhook relay (quick-vs-ack-then-run classification,
deadline enforcement, secondary-channel delivery) as a framework-agnostic,
fully-injected core that runs as a Worker or a local service.

`benchmarks/`: GAIA, τ²-bench-style stateful harness, terminal-bench-style
harness, SWE-bench harness, moat suite, and an **adversarial-cost suite**
(`eval_adversarial_cost.py`): scripted money-wasting scenarios — tool loops,
token bombs, runaway iterations — each asserted CLAMPED by the cache /
output-cap / Budget ceilings; `main()` exits 1 on any unclamped scenario. All
CI-runnable on shipped fixtures.

## Observability & reliability

OpenTelemetry traces (spans carry the **full OTel GenAI semantic-convention
attribute set** — `gen_ai.operation.name` / `system` / `request.model` /
`request.{max_tokens,temperature,top_p,frequency_penalty,presence_penalty}` /
`response.{model,id,finish_reasons}` / `usage.{input,output}_tokens`, plus the
`execute_tool` tool-span attributes AND the `invoke_agent` agent-span leg
(`gen_ai.agent.name/id` around every `Agent.run`) with semconv `error.type`
stamped on failed spans — so any OTel-native backend reads them
with no custom mapping), Prometheus `/metrics`, and a **Sentry performance
tab** (all opt-in) (`observability.py`): `MAVERICK_SENTRY_DSN` (or
`[observability] sentry_dsn`) initializes Sentry tracing and every existing
`trace_span` call feeds it — a transaction at the root (episodes), child spans
inside (tools) — sample rate via `MAVERICK_SENTRY_TRACES_SAMPLE_RATE`, PII off,
`[sentry]` extra; per-tool latency profiles + extended stats
(`tool_latency.py`); **tail-latency hunting** (`tail_latency.py`, `GET
/api/v1/diag/tail-latency`): flags tools with a fat tail (p99/p50 ≥ ratio) —
usually fast, occasionally terrible — which is where the bug hides, not just
the slowest by p95; opt-in per-tool **latency budget** (`latency_budget.py`) and
cross-span **budget propagation** (`latency_span_budget.py`); **tiered storage**
(`tiered_storage.py`, opt-in `[world_model] cold_dir` + `archive_after_days`):
archive old episodes/goal_events to cold parquet (pyarrow when present, gzip
JSONL always, or **zstd** JSONL via `[world_model] cold_codec = "zstd"` + the
`[zstd]` extra — smaller/faster, with graceful gzip fallback) with
write-before-delete safety, fact-pinned rows kept hot, and `read_cold`
(every codec, mixed dirs OK) so archives stay queryable; **speculative tool execution**
(`speculative_tools.py`, opt-in `[tools] speculative`): pre-execute predicted
read-only (`parallel_safe`) tool calls concurrently into the tool-output cache
— `predict_from_history` warms only calls repeated across turns; **async
compaction** (`async_compaction.py`, opt-in `[context] async_compaction`): the
expensive prefix of a conversation's history is compacted in the background
between turns and the hot path pays only a cheap tail-merge — single daemon
worker, last-write-wins, fingerprint-validated so a changed prefix never mixes
stale summaries; **cost projection at plan time** (`cost_projection.py`): token/dollar
estimates per plan step from the role's model + MODEL_PRICES, iterations
multiplier, OK/TIGHT/OVER budget verdicts; **provider migration calculator**
(`migration_calculator.py`): re-price a usage ledger on target models
(cheapest-first matrix, unpriceable rows excluded from both sides, honest
tokenizer caveat always rendered); **cross-run learning cache**
(`learning_cache.py`, opt-in `[memory] learning_cache`): memoize *verified*
sub-results across runs (required `verified_by` provenance, TTL + LRU cap,
refuses to store anything the secret detector flags); **energy/CO2
accounting** (`energy_accounting.py`): clearly-labeled estimates from
configurable Wh/1k-token + grid-CO2 coefficients (output tokens weighted 3x),
disclaimer always rendered; **Redis tool cache** (`redis_tool_cache.py`,
`[tools] output_cache_backend = "redis"`): cross-process/cross-host tier
reusing the same key canonicalization, namespace-scoped purge, fail-open on
any Redis error; **WAL contention audit** (`test_wal_contention.py`): pins the
16-concurrent-writers / zero-lock-errors promise + the WAL/busy_timeout pragmas
in CI; **cold-start guard** (`test_cli_cold_start.py`): `maverick --help` stays
fast (~0.1s, well under the 300ms target) because importing the CLI defers
every heavy/optional dep — a fresh-interpreter test fails CI if a module-level
`import httpx`/provider-SDK/vector-store/numpy sneaks into the import path; **query-plan regression CI** (`test_query_plans.py`): hot world-model
queries must SEARCH via an index, never full-scan; **cost-attribution API**
(`GET /api/v1/cost/by-tag` on the dashboard): spend bucketed by episode/goal
tag — the JSON face of the tag split for chargeback/BI; **real-time SSE event
stream** (`GET /api/v1/goals/{id}/events/stream`): a `text/event-stream` live
tail of a goal's events that emits each as it lands and ends on terminal status
or disconnect — tails the durable `goal_events` log so it works across the
worker/dashboard process split (the polling `/events` endpoint stays for simple
clients); **streaming tool_result**
(`ToolRegistry.set_chunk_listener`): a tool fn may be an async generator or
return a sync generator of chunks — chunks stream to the registered listener
(dashboard/TUI live view) as they're produced while the model still receives
the joined text, so the model protocol is unchanged; **tool-output cache**
for read-only tools (`tool_cache.py`) with opt-in **warm-on-start** (`[tools]
output_cache_snapshot`: persist entries to a JSONL snapshot, reload the
still-fresh ones on the next run's first lookup); **memory-leak quarantine**
(`leak_quarantine.py`): per-component watchdog that flags sustained monotonic
growth and quarantines the component for recycling (sawtooth never trips it); **network egress accounting**
(`egress_accounting.py`); **run health score** (`health_score.py`); **real-time anomaly detection**
(`realtime_anomaly.py`): the online companion to the batch cross-run
analyzer — feed a metric (latency / per-step cost / tokens) as it happens and
a rolling-window z-score flags a spike *mid-run* (a `StreamMonitor` watches
each stream independently), so a runaway is caught live, not in a post-mortem;
**replayable
trace** format (`replay_trace.py`) with **trace pinning to commit**
(`trace_pin.py`: every run stamps a `trace_meta` event carrying the
workspace's commit/branch/dirty state at start — best-effort, never blocks —
and `trace_commit()` reads it back so replays tie to exact code); **cost split by tag** (`cost_by_tag.py`) and
**provider cost-curve fitter** (`cost_curve_fitter.py`); provider health board
(`provider_health.py`); proactive **provider rate-limit predictor**
(`rate_limit_predictor.py`); shared tool-reliability layer (`tool_reliability.py`,
`retry.py`); circuit breaker (`circuit_breaker.py`); adaptive thinking budget
(`thinking_budget.py`). **Self-tuning budgets** (`budget_tuner.py`, `maverick
budget-tune`): learn a `max_dollars` recommendation from the historical
per-goal spend distribution (a high percentile + margin, so the common case
fits while a runaway still trips it), bucketable by an injected task-class
classifier; read-only — the operator sets the value. **Failure-mode telemetry** (`failure_telemetry.py`, `maverick failures`,
opt-in `[telemetry] failure_modes`): a failed run records a canonical mode
(budget / auth / timeout / shield / sandbox / network / error) to a local JSONL
sink — the orchestrator tees from its budget and generic failure seams,
best-effort and a no-op when the telemetry is off — so an operator sees the
*distribution* of failures and fixes the dominant cause. Local-first, no
mandatory egress. **Continuous profiling daemon** (`profiling_daemon.py`,
`python -m maverick.profiling_daemon`, opt-in `[perf] profiling`): a sampling
profiler that periodically runs `py-spy record` against the live process and
drops speedscope/flame-graph profiles under `data_dir("profiles/")` — py-spy
samples from outside the interpreter (no GIL cost) so it's safe to leave on in
production; default-OFF, with an injectable runner/clock so the schedule is
tested without spawning py-spy.

## UX surfaces

- **i18n community portal** (`maverick_dashboard/i18n_portal.py`): the
  no-Python on-ramp for new dashboard-chrome languages — `scaffold(lang)`
  emits a fill-in catalog (every key seeded with English), `validate_catalog`
  lints a submission against the English reference (lang-code shape, missing/
  unknown keys, blank values, unbalanced `{placeholder}` tokens — a precise
  diff for a translation PR's CI), and `load_external_catalogs` /
  `merged_messages` overlay validated `<lang>.json` files from `[i18n]
  portal_dir` onto the built-ins so an operator drops in a community
  translation and the dashboard speaks it with no rebuild (malformed catalogs
  skipped, never blanking the UI).
- **Computer-use calibration + multi-monitor + vision clicking**
  (`computer_calibration.py`, `multi_monitor.py`, `vision_click.py`):
  per-axis affine calibration fitted by least squares over clicked targets
  (deterministic target grid, residual/drift report, atomic 0600
  persistence) corrects model-space clicks to screen space; a
  `VirtualDesktop` models multi-monitor geometry (negative origins,
  `monitor_at`, global/local transforms, `[computer_use] monitor` pinning)
  over lazily-imported mss; `resolve_click("the blue button")` consults the
  GUI element memory first, falls back to an injected vision seam with a
  confidence floor (`LowConfidenceError` below it, nothing memorized on
  refusal), upserts what it learns, and applies the saved calibration.
- **Hardware sensors tool** (`tools/hardware_sensors.py`, `[sensors]` extra):
  read host temperatures/fans/battery via psutil with a `/sys/class/thermal`
  fallback and an injected reader for tests; unavailable categories say
  "unavailable on this host" — readings are never fabricated.
- **Voice biometric unlock — companion factor only** (`voice_unlock.py`,
  opt-in `[voice] biometric_unlock`): speaker verification over an injected
  embedder with three hard stances — a voice match **never authenticates on
  its own** (`decide()` returns `companion_ok`; callers combine it with an
  existing factor — replay/synthesis is practical), profiles are local
  embedding centroids (never raw audio, 0600) with first-class
  `delete_profile`, and the whole feature is off by default.
- **Onboarding personalization v2** (`onboarding_v2.py`): post-install
  personalization from *actual early usage* — long conversations suggest
  compaction, repeated task verbs point at templates, a high approval-denial
  ratio suggests the supervised director profile, repeated same-class
  failures surface the self-healing remedy, multi-channel use suggests
  channel niceties; every suggestion carries the observation that justifies
  it and the exact action, nothing is applied, and thin usage returns an
  honest "not enough usage yet" instead of generic tips.
- **Self-healing UX** (`self_healing.py`): a failed run is diagnosed into
  its failure class (budget exceeded, provider auth, rate-limited, shield
  block, sandbox missing, timeout, killswitch) and answered with an ordered
  list of concrete remedies — each carrying the exact command or config edit,
  with reversible config suggestions tagged; **nothing is auto-applied** —
  surfacing the fix is the healing, the human stays in charge.
- **Power-user keymap** (`keymap.py`, `[tui.keys]` /
  `MAVERICK_TUI_KEYS`, `python -m maverick.keymap [--validate]`): validated
  TUI keybindings — conflicts, unknown actions, and invalid keys are
  rejected, Ctrl-C is reserved as the unrebindable emergency exit, and a bad
  override set degrades to the stock keymap rather than an unusable one;
  `handle_key` is the pure key→action adapter the monitor/focus model
  consume.
- **Achievements** (`achievements.py`): a local-only milestone ledger
  *derived from recorded history* (never self-reported; nothing leaves the
  machine) — first/10/100 completed goals, a 5+-sub-goal swarm, 3+ channels,
  10 approval decisions — unlocking exactly once into an atomic 0600 store;
  evaluated on view, never per-turn.
- **Share links + device handoff** (`share_link.py`, `[sharing] secret`
  required — no unsigned mode): a share link is a signed, expiring,
  *read-only* token referencing a goal (carries no content; constant-time
  verification, expiry/signature fail closed); a device handoff is a
  *one-time* signed code moving a session between the user's devices —
  `claim()` consumes the nonce so a replayed/stolen-but-used code is dead
  (5-minute default TTL, expired nonces pruned).
- **Director mode** (`director_mode.py`): state an *outcome* and pick the
  autonomy level — `supervised` / `semi` / `autonomous` profiles map to the
  existing controls (consent mode, review-checkpoint intervals, a budget
  multiplier over the configured cap, plan-execute-reflect topology) so one
  choice sets the whole envelope. `direct()` is pure assembly (starts
  nothing; the hard Budget ceiling still applies at run time); profiles are
  config-overridable and unknown profiles are refused — an autonomy level is
  never guessed.
- **Predictive approvals** (`predictive_approvals.py`): learns the operator's
  historical approve/deny rate per (action, risk tier) from approval history and
  *suggests* a default — auto-approve-candidate / auto-deny-candidate /
  always-ask — with a confidence from sample size. A suggestion surfaced to the
  human, never an auto-decision; high/critical actions are never auto-approve
  candidates.
- **Channel auto-routing** (`channel_autorouting.py`, `[channels.routing]`): a
  pure decision function picking the best-fit reply channel/handler from an
  inbound message's signals (length, detected language, urgency, attachment
  types, an injected classifier) against a configurable rule table, with
  `explain()`; passthrough when unconfigured.
- **Provider-side caching analytics** (`provider_cache_analytics.py`): parses
  prompt-cache telemetry into a hit-rate / $-saved report (cache-read vs write
  vs uncached at configured prices), per-role breakdown, and "unstable prefix"
  recommendations for roles with a low hit rate.
- **Consent ergonomics** (`consent_ergonomics.py`): improves the consent UX
  without weakening it — batches related pending prompts into one grouped ask,
  renders a plain-language summary, and remembers "ask once this session" for an
  exact (action, scope) in an injected **session-scoped** store (expiring, NOT a
  persistent grant); composes with `safety.consent`, never bypassing its
  decision.
- **Static accessibility audit** (`a11y_audit.py`, `python -m
  maverick.a11y_audit --ci`, wired as a CI step): an offline structural WCAG
  pass over the shipped dashboard templates — img alt, form-control labels
  (`for`/`id`, wrapping `<label>`, `aria-label`), `<html lang>`, positive
  `tabindex`, empty interactive controls, heading-level skips — with Jinja
  placeholders treated as opaque text. Complements the live `a11y` tool
  (pa11y/axe); the audit pass fixed the two real findings it surfaced (chat
  textarea + fleet-name input now labelled).
- **TUI mouse mode** (`tui_mouse.py`, opt-in `[tui] mouse`): `maverick
  monitor`'s plan tree becomes clickable — SGR (xterm 1006) mouse tracking
  enabled/restored around the Live view, a click hit-tests its row to the
  plan-tree node and focuses/expands it (`NodeHitMap` + `FocusModel`, pure and
  terminal-free so it's unit-tested without a tty). Off by default; degrades
  to keyboard/auto-refresh on terminals that don't report mouse events.
- **CLI** — `maverick init` (wizard — with **branching paths**: a mode picker
  routes consumer users to a tailored short flow (`run_consumer`) while
  advanced users get the full step sequence, and the deployment answer
  (desktop/docker/vps/phone) filters the channel/sandbox questions that
  follow; `--fast` and `--resume` skip/restore branches), `start`, `resume`, `monitor` (Rich plan-tree
  TUI), `status --cost`, `export`, `replay`, `logs`, `ps`, `whoami`,
  `maverick diag` (circuit-breaker states, provider rate-limit counts, per-goal
  health score, cost-by-tag, and replay of a `MAVERICK_TRACE_DIR` run trace),
  `maverick config-lint` (validate `~/.maverick/config.toml` for unknown
  sections/keys + obvious type mistakes with closest-match suggestions;
  `config_lint.py`), and `maverick costs` (cross-run per-day spend from the
  recorded episode ledger; `cost_report.py`).
- **GitHub App** — `/webhook/github` (dashboard): a labeled or `/maverick`-mentioned
  issue drives a swarm that clones the repo, fixes it, and opens a PR
  (`github_app.py`, HMAC-verified). **GitLab Issues** — `/webhook/gitlab`:
  assign an issue to the bot, get a goal (`X-Gitlab-Token` constant-time
  verify, `X-Gitlab-Event-UUID` replay dedup), completing the
  Linear/Jira/GitHub/GitLab issue-trigger family (`issue_webhooks.py`).
- **Web dashboard** — run list, plan-tree, chat at `/chat`, approval queue with
  **collaborative supervision** (claim/release endpoints so two supervisors
  never double-handle a review — atomic claims, 409 on conflicts, claims
  surfaced in the pending list — plus `decided_by` attribution on every
  decision; SQLite migration v13 + Postgres parity, tenant-scoped), and
  an **oversight console** (`/oversight`): live fleet state, the approval queue,
  a per-guardrail intervention roll-up, and an inline **"why this action"
  drill-down** (the reasoning/tool chain + cost for a running agent, owner-scoped)
  (`maverick dashboard`). **Search across runs** — a live search box on the
  goals page over `GET /api/v1/goals/search` (text match on title/description/
  result, owner-scoped, decrypt-then-filter since those fields are encrypted at
  rest). **Pinned watch list** (`/api/v1/pins`, per-principal,
  most-recent-first), **saved dashboard views** (`/api/v1/views`: named
  filter/query-param sets), **annotated traces**
  (`/api/v1/goals/{id}/annotations`: human notes pinned to replay-trace steps),
  **multi-run dashboard** (`/api/v1/runs/compare?ids=…`: side-by-side
  status/events/errors for up to 8 runs), and **plain-language explanations**
  (`/api/v1/goals/{id}/explain`: a deterministic, template-rendered narrative
  of the run — `plain_language.py`, no LLM call, never hallucinates beyond the
  log). Pins/views/annotations persist tenant-aware in `ux_store.py`.
  **Run-events firehose** — `WS /ws/v1/runs/{id}/events`: a goal's events
  stream over WebSocket as they land (resume via `since_id`, terminal status
  closes the stream; auth mirrors the HTTP policy and OIDC applies to WS).
  **Inline cost preview** — `GET /api/v1/goals/{id}/cost-preview`: plan-time
  token/dollar projection + OK/TIGHT/OVER verdict before a goal runs.
  **"Why this cost" drill-down** — `GET /api/v1/goals/{id}/cost-breakdown`:
  spend decomposed by episode outcome (dollars/tokens/counts).
  **Replay export to MP4** — `replay_video.py` +
  `GET /api/v1/goals/{id}/replay-storyboard`: a run rendered to a watchable
  video — the deterministic core builds a captioned frame storyboard with
  per-step durations from the event gaps (secret/PII-scrubbed), then encodes
  via Pillow + the sandbox-mediated ffmpeg tool when present; when the video
  stack is absent it still emits the frame manifest + the exact ffmpeg command
  for out-of-band encoding (no new hard dependency).
  **Run gallery** — `GET/POST/DELETE /api/v1/gallery[/{id}]`:
  deployment-wide curation of exemplary runs (blurb + curator attribution,
  upsert, capped), each entry enriched with live status and links to the
  tutorial/explain exports; access-checked per viewer.
  **Run-as-tutorial export** — `GET /api/v1/goals/{id}/tutorial.md`
  (`tutorial_export.py`): the run rendered as step-by-step markdown (goal →
  approach → steps with preserved code fences → dead ends → outcome),
  deterministic templates over the event log, secret-scrubbed, no LLM call.
  **Cross-run anomaly detection** — `GET /api/v1/goals/{id}/anomalies`
  (`cross_run_anomaly.py`): a run scored against the deployment's behavioral
  baseline — novel event kinds (high), event-volume spikes (runaway-loop
  signal), error-rate spikes — conservative 3σ thresholds, silent on cold
  deployments (<5 baseline runs); signals for a human, not verdicts.
  **Cost anomaly alerts** — `GET /api/v1/cost/anomalies`: per-goal spend
  outliers above mean + Nσ over the recent window (needs ≥3 priced goals).
  **Accessibility + i18n** — a font axis independent of the theme
  (`?font=dyslexic` / cookie: OpenDyslexic-preferring stack with wider
  letter/word spacing, composes with the high-contrast theme) and **chrome
  i18n in en/fr/de/ja/zh** (`maverick_dashboard/i18n.py`: dict catalog +
  `t()` template helper; `?lang=` → cookie → `Accept-Language`; user data is
  never translated; catalog-completeness pinned by test).
- **Cost** — per-run reports, live cost meter, `maverick start --dry-cost`
  forecasting (`cost_forecast.py`).
- **Templates / marketplace v2** — starter-goals library + community template
  registry (`maverick template browse/add`), **hash-verified installs**
  (`catalog.py` sha256 pinning), **ratings**: indexes carry display-only
  `rating`/`ratings_count` aggregates (clamped, malformed-safe), `browse`
  renders ★-bars, and a local ledger (`marketplace_ratings.py`,
  `maverick template rate <name> <1-5>` / `ratings-export`) keeps your own
  ratings ready for an index-PR submission — no hosted ratings service.
- **Marketplace stats** — `GET /api/v1/marketplace/stats` (`marketplace_stats.py`):
  aggregates the local ratings ledger into total / average / 1–5★ distribution /
  per-kind breakdown / top-rated — the JSON face of the stats view. Self-host-first
  (the operator's own ratings; no hosted community service); pure aggregation.
- **Skill validator service** — `POST /api/v1/skills/validate` on the
  dashboard: lint a SKILL.md body (same linter as `maverick skill validate`)
  from CI or an editor against a self-hosted instance; size-capped, nothing
  persisted.
- **Localized money display** — `format_money` tool (`money_format.py`): format
  an amount per a (locale, currency) pair — symbol placement, grouping/decimal
  separators, the currency's decimal places — with an optional operator-supplied
  FX rate (`$1,234.56` → `1.234,56 €` → `¥1,235`). Offline display layer,
  distinct from the live-FX `currency` conversion tool; a curated locale subset.
- **DuckDB analytics** — `maverick analytics` (`duckdb_analytics.py`, `[duckdb]`
  extra): load the world model's goals/episodes into an in-memory DuckDB and run
  OLAP over the history — per-goal cost percentiles, time-bucketed spend, top
  goals, and **ad-hoc read-only SQL** (`--sql`, refuses anything but
  SELECT/WITH). This is the analytical use DuckDB is actually good at; the live
  transactional world model stays SQLite/Postgres (DuckDB is the wrong engine
  for the concurrent write path).
- **Cost retrospective** — `maverick cost-retro` (`cost_retrospective.py`): a
  spend review over the recorded per-goal/episode costs — the costliest goals,
  how much went to **failed** work (effort with no delivered result), how
  concentrated spend is (a Pareto signal), and rule-based observations to act
  on. Deterministic over the world model; read-only.
- **UX cluster (2028-H1)** — **plan-tree minimap** (`plan_minimap.py` +
  `GET /api/v1/goals/{id}/minimap`): a compact glyph-per-node subtree render
  with a depth budget; **multi-tenant overview** (`/tenants/overview`,
  admin-only like `/tenants`): per-tenant goal rollups + today's spend +
  suspended flags; **replay annotation export** (`annotation_export.py`):
  a run's annotations to markdown or SRT-timed cues; **personalized starter
  templates** (`starter_templates.py` + `GET /api/v1/templates/suggested`):
  the catalog ranked from the user's own goal history; **adaptive UI
  density** (comfortable/compact via `?density=`/cookie/config); **pluggable
  themes** (`themes.py`: `[dashboard] themes` rendered as CSS variables,
  strict `#hex` validation so config can't inject CSS); **templates
  marketplace** (`/templates`: catalog + ratings, "use" prefills the chat
  form — no auto-start); **live voice captions** (`live_captions.py` + SSE
  `GET /api/v1/voice/captions`): a rolling caption window over an injected
  transcript source (finalized vs in-flight, word-boundary trimming).
- **Browser extension** (`extensions/browser/`, opt-in `[dashboard]
  allow_extension` — fail-closed CORS scoped to extension origins only): a
  Manifest-V3 WebExtension (no build step, loopback-only host permissions,
  `script-src 'self'`) with popup chat against the existing goals API and a
  "send this page" action shipping title/URL/selection as goal context;
  static tests pin the manifest security properties (no remote code).
- **ARIA-first navigation** (`tools/aria_navigate.py`, registered with the
  browser tool): drive the page via the accessibility tree — `snapshot`
  (stable node ids), `find` (role+name), `activate` (click/focus by node) —
  the live counterpart to the static `a11y_tree` extractor.
- **WebRTC tool** (`tools/webrtc_tool.py`, `[webrtc]` extra): data-channel
  offer/answer/send/close over lazily-imported aiortc (signalling is the
  caller's; media tracks out of scope, stated honestly).
- **Audio understanding** (`tools/audio_understanding.py`, `[clap]` extra):
  zero-shot NON-SPEECH classification — a CLAP model embeds the clip and
  free-text labels ("glass breaking", "dog barking", "fire alarm") into one
  space and ranks them; `op=embed` returns the raw audio embedding. The
  embedders are injected seams (ranking math tested offline); the default
  adapters lazy-load transformers' ClapModel (`MAVERICK_CLAP_MODEL`,
  workspace-confined paths, stdlib-only WAV decode).
- **Conversational supervisor** (`conversational_supervisor.py`): natural-
  language supervision of running work — a deterministic intent grammar
  (reusing the voice-command compiler, with an optional llm seam that
  re-parses paraphrases through the *same* grammar, never a guess that
  mutates) answers reads ("what's running?", "how much today?", "what
  failed?") from cheap indexed passes over the world model + usage ledger,
  and routes mutating intents (pause/resume/reprioritize) through a strict
  `as_bool` confirm gate to world-model methods that actually exist
  (pause = status `blocked` + a supervision event; prioritize = a
  `goal:<id>:priority` fact — stated in the docstring).
- **Voice-only mode** (`voice_only.py`, `[voice] only_mode`, default OFF):
  an all-speech session loop — injected utterance source → handler →
  injected `speak` seam (default routes the TTS path, which redacts) — with
  a tested deterministic speech-shaping pass that turns markdown/code into a
  spoken summary ("I wrote 40 lines to app.py"). Mic capture + playback
  hardware are the operator's adapters behind the seams.
- **Voice macros** (`voice_macros.py`): named multi-step command sequences
  ("morning routine" → status, failures, summary) triggered by one phrase;
  persisted 0600, each step **re-validated against the grammar at trigger
  time** (a smuggled unparseable step is skipped, never dispatched) and
  risky steps keep their confirm gates **individually** — a macro never
  pre-authorizes. Bounded step count.
- **Augmented terminal charts** (`terminal_charts.py`, `maverick charts`):
  inline sparklines (▁▂▃▄▅▆▇█) and bars for spend/day (usage ledger), goal
  throughput (world), and tool-latency percentiles (`tool_latency`) — the
  ASCII renderer is the tested core, `rich` panels a thin lazy wrapper;
  honest empty-state lines when there's no data.
- **Streaming voice channel v2** (`maverick_channels/streaming_voice.py`):
  the protocol layer for streaming ASR + **barge-in** — partial/final
  hypothesis events drive endpointing on an injected clock, and speech onset
  while the bot is talking halts playback immediately (`stop_speaking()`),
  preserving the interrupted reply as partially-delivered. Fully offline-
  tested with scripted event sequences; the real streaming ASR + playback
  engine plug into the seams.
- **Speech-to-action live mic** (`live_mic.py`): a hardware-free loop —
  injected chunk source → injected transcriber → the deterministic
  voice-command grammar → injected action callback, with risky intents
  behind a strict confirm gate (only a real `True` authorises; no confirm
  hook = fail-closed denied; a raising action is logged, not fatal).
  `whisper_transcriber()` builds the real adapter on faster-whisper
  (`[voice]` extra, `MAVERICK_WHISPER_MODEL`); any mic adapter that yields
  bytes plugs in.
- **Image edit tool** (`tools/image_edit.py`): the edit verbs to pair with
  replicate's generation — hosted inpaint/variation/upscale over the same
  Replicate API surface (default models are operator knobs:
  `MAVERICK_{INPAINT,VARIATION,UPSCALE}_MODEL` or per-call `model=`; local
  images inlined as data URIs) and local crop/resize/rotate via Pillow
  (`[computer-use]` extra, no key). Every model-supplied path is
  workspace-confined.
- **ASR meeting listener** (`meeting_listener.py`): consume any
  transcript-segment stream into minutes — rolling timestamped transcript,
  merged speaker turns, action items via a deterministic heuristic
  (assignment patterns, imperative openers, `action item:`/`TODO:` markers)
  with an optional llm seam that falls back to the heuristic on failure;
  `finalize()` writes the session artifact to `data_dir("meetings")` 0600.
  Injected clock, fully reproducible offline.
- **Audio diarization + emotion** (`audio_analysis.py`): honest-scope
  heuristic diarization — cosine-distance thresholding over injected frame
  embeddings with centroid label reuse (S1-S2-S1 exchanges come back
  labelled; no clustering/overlap/VAD, stated plainly) — plus zero-shot
  emotion ranking over the same CLAP seams as audio understanding
  (`[clap]` extra shared, real frame embedder included).
- **Embedded-device tool** (`tools/embedded_device.py`): JTAG + I2C access
  to the **operator's own** devices. JTAG mediates OpenOCD strictly through
  `sandbox.exec()` — halt/resume/reset, bounded memory reads (reads never
  auto-halt, so they can't silently change target state), flash write; the
  destructive ops (flash, reset) stay refused until `[embedded] allow_flash
  = true` (default OFF, wizard-exposed). I2C is a pure protocol layer over
  an injected bus seam (`smbus2` via the `[i2c]` extra). Every op names its
  explicit target — no autodetect-and-flash; failures are `ERROR:` strings.
- **WebGPU local vision + perceptual hashing** (`extensions/webgpu-vision/`
  + `perceptual_hash.py`): a no-CDN WebGPU page running real hand-written
  WGSL compute shaders (grayscale, Sobel) over a user-chosen local file
  that never leaves the browser, plus an 8×8 average-hash specified in
  integer-only arithmetic so the JS and the Python twin
  (`average_hash_from_pixels`/`average_hash_file`, `[computer-use]` Pillow)
  produce a **bit-identical** hash — a cross-language "are these two
  screenshots the same screen?" primitive (Hamming distance). Honest scope:
  GPU image primitives + perceptual hashing, not a trained vision model.
- **Mobile companion v1 + offline cache** (`apps/mobile-companion/` +
  `offline_bundle.py`, `GET /api/v1/offline/bundle`): a read-only Expo
  scaffold (Runs list, Run detail, Glance, Settings) that consumes only
  existing GET endpoints with a bearer token in `expo-secure-store`; zero
  mutating calls. The **offline bundle** is a compact, bounded, versioned
  snapshot (`maverick-offline/1`: glance + goals + recent events, every
  list capped, no secrets — enforced by test) the app caches in
  AsyncStorage and renders behind an "as of N min ago — offline" banner
  when the dashboard is unreachable.
- **Marketplace federation** (`marketplace_federation.py` +
  `federation_envelope.py`): export/import signed listing bundles between
  instances (`maverick-marketplace-fed/1`) — import verifies the Ed25519
  envelope **fail-closed** (bad/missing signature, unknown origin, or a
  missing `cryptography` library all reject the whole envelope), enforces
  the `[federation] marketplace_peers` trust list, namespaces imports as
  `origin/name` so they can never shadow local listings, and re-runs the
  local moderation scan on every import. Ratings do NOT federate — their
  provenance can't be verified, stated plainly.
- **Channel federation** (`channel_federation.py`): forward messages
  between instances' channels over the same envelope discipline — a
  bounded 0600 outbound queue with user ids pseudonymized via per-pair
  HMAC, inbound verify fail-closed against the pinned per-origin key,
  addressed-to-us check, per-peer token-bucket rate limit (injected
  clock), and delivery into the normal handler as `channel="fed:<origin>"`
  so federated traffic hits every existing chokepoint. The HTTP binding is
  deliberately the operator's; the transport is an injected seam.
- **Marketplace donate-direct** (`marketplace_donations.py`): skill authors
  declare a donation link; validation enforces https + an allowlist of
  donation hosts (GitHub Sponsors, Ko-fi, Open Collective, Liberapay, Buy
  Me a Coffee) and the federation import strips invalid ones. Links only —
  no payment processing, no checkout proxying, no referral codes.
- **Benchmark reproducibility audits** (`benchmark_reproducibility.py`):
  every new benchmark run can carry a manifest
  (`maverick-bench-repro/1`: host fingerprint, config + input digests, env
  key presence/absence — never values); `verify_reproduction(a, b)` says
  exactly which digests differ and calls runs "comparable" only when
  config+inputs match; `audit_report()` sweeps the stored history. Two
  runs with differing digests are never claimed comparable.
- **Compaction v6 hybrid** (`compaction_hybrid.py`): the strategy picker
  learned from this deployment's own outcomes — deterministic features
  over the message window, a per-(feature-bucket, strategy) outcome ledger
  (atomic 0600), epsilon-greedy with an injected PRNG, and an optional
  pure-Python logistic `fit()` (no torch) whose versioned weights the
  picker consults when present. Cold start = the existing default
  strategy; every failure falls open like all compaction paths. An
  online-learning heuristic, not a pretrained model — stated in the
  docstring.
- **Sandbox pool: Firecracker-warm + cross-run pooling**
  (`sandbox/firecracker.py` + `sandbox/pool.py`, `[sandbox]
  cross_run_pool` default OFF): Firecracker warm mode keeps one e2b
  microVM alive between execs (the local firectl path can't, and says so
  honestly); the cross-run pool parks a still-healthy docker/podman
  backend at run end (bounded, TTL, injected clock) and hands it to the
  next run under a strict **scrub contract** — workdir re-pointed, env
  scrubbed per exec, and only engines whose `run --rm`-per-exec model
  provably carries no state are eligible (local/firecracker/ssh/k8s/
  devcontainer are excluded with reasons; they always build fresh).
- **Speculative drafting across providers** (`speculative_decode.py`): a
  cheap draft model proposes, the target verifies-or-revises in one call;
  per-(draft,target) accept-rate ledger with a floor below which it falls
  back to plain target calls — application-level drafting, explicitly not
  logit-level decoding; models resolve by role, never hardcoded.
- **Out-of-process model proxy** (`model_proxy.py`): the provider key lives
  in a separate proxy process; the agent's `base_url` points at it with no
  usable credential — the proxy strips whatever the agent sent and injects
  the real key, so a prompt-injected agent process has no key to exfiltrate.
- **Watch glance endpoint** (`GET /api/v1/glance`): the fixed tiny payload
  the watch scaffold renders.
- **Granular redaction UI** (`GET /redact` page + `POST
  /api/v1/redact/preview`): paste text, see every secret/PII finding as a
  kind + span (never the raw value), and pick per-kind what to scrub —
  empty selection runs full provable redaction; a granular selection
  replaces only the chosen kinds' spans and *honestly* reports
  `proven_clean: false` with the residual kinds left behind, instead of a
  false guarantee. Preview-only: nothing is stored server-side.
- **Visual graph editor** (`/graph-editor` + `GET /api/v1/goal-tree` +
  retitle/reparent/add-child endpoints): the goal forest as an interactive
  SVG node graph — server-side layered layout (pure, unit-tested), pan/
  zoom, status colors — with editing that refuses cycles and self-parenting
  (400), access-checks both ends, and creates children **pending, not
  auto-run** (stated in the UI). A keyboard path via labeled selects keeps
  it accessible.
- **Drag-and-drop goal builder** (`/goal-builder`): compose a goal from
  blocks — steps (ordered checklist), budget, channel, priority — native
  HTML5 DnD plus keyboard add/move/remove buttons, live brief preview. The
  budget block is enforced as the runner's real `max_dollars` (clamped to
  the server cap); channel/priority ride in the brief and say so.
- **Embedded analytics web component**
  (`/static/maverick-analytics.js` + `/embed-demo`): a self-contained
  `<maverick-analytics>` custom element (Shadow DOM, no framework, no CDN)
  fetching the real spend + goals endpoints and hand-drawing SVG
  sparklines/bars; same-origin/token limits documented in the JS header and
  on the demo page; errors render as HTTP status, never fake data.
- **Benchmark live dashboard** (`/benchmarks` + `GET /api/v1/benchmarks`):
  per-suite trend sparklines + regression verdicts over the real
  `continuous_benchmark` history (`bench_track`), via the real
  `detect_regression`; honest empty state naming the record command. No
  fabricated competitor numbers — this page is *this deployment's* recorded
  runs.
- **Embedded video walkthroughs** (`/walkthroughs` + `POST
  /api/v1/goals/{id}/walkthrough`): standardizes `~/.maverick/walkthroughs/`,
  drives the real `replay_video.render` (sandbox-mediated ffmpeg; reports
  encoded vs manifest-only honestly with the exact argv), generates a real
  WebVTT captions track from the storyboard frames, and lists MP4s with
  native `<video controls>` + `<track>`; strict name-pattern media serving.
- **3D plan tree** (`/plan-tree-3d`): raw WebGL (no three.js) point-sprite
  nodes + line edges over the same `goal-tree` endpoint, orbit/zoom,
  click-to-focus overlay; the text tree is always present in `<details>`
  as the accessible/no-WebGL representation, and the WebXR "Enter VR"
  button appears only when `navigator.xr` reports support (untested
  without headset hardware — stated on the page).
- **RTL language support** (`i18n.py` `RTL_LANGS` + `dir_for()`):
  `dir="rtl"` driven by the active language (ar/he/fa/ur) through the
  existing lang resolution, logical-property CSS in the base layout, and an
  Arabic community-seed catalog (genuinely translated starter keys, English
  fallback; he/fa/ur activate the moment a catalog lands — they're not
  offered in the picker until one does, to avoid implying support).
- **Live-run IDE extensions** (`apps/vscode-extension/` +
  `apps/jetbrains-plugin/`): the VS Code extension gains "Watch run live" /
  "Stop live watch" — a dependency-free SSE tail of the dashboard's
  per-goal event stream into an output channel (manual SSE parse,
  exponential-backoff reconnect, terminal-control stripping, token header
  honored, settings for URL/token; type-checks clean). The JetBrains
  scaffold mirrors it as a Runs tool window (Kotlin, same SSE endpoint,
  same backoff); building it requires the IntelliJ SDK, stated in its
  README.
- **Apple Watch glance** (`glance.py` + `apps/watch-glance/` SwiftUI
  scaffold): a tiny fixed payload sized for a watch face — active count,
  today's done/failed, today's spend (summed from the usage ledger), and the
  last terminal result (60-char bound) — computed in one cheap pass; the
  watchOS scaffold renders exactly that shape against the dashboard (token
  header honored; building it requires Xcode, documented in its README — the
  integrator wires `GET /api/v1/glance`).
- **Mobile push v2** (`push_v2.py`): a device registry layered on the v1
  notify path — each device registers a backend, a minimum priority floor,
  and optional quiet hours; routing fans out only to eligible devices, with
  `urgent` always breaking through quiet hours (page-me semantics); every
  fan-out lands in a bounded delivery ledger so "did my phone get that?" is
  answerable.
- **Smart notification batching** — opt-in `[notifications]
  batch_window_seconds` (`notification_batcher.py`): coalesces the
  low/normal-priority push stream (ntfy/Pushover/Discord/Slack) into one
  windowed digest ("5 updates" with the lines folded in) so a long run doesn't
  turn a phone into a slot machine; **high/urgent** notifications cut the line
  and deliver immediately (flushing any pending batch first, so order holds). A
  daemon flusher drives the window; unconfigured, `notify()` is unchanged.

## Distribution & install

- **Packaging** — 7 packages on PyPI, GHCR Docker image, PyInstaller binaries,
  native double-click installers (Tauri; `.exe` / `.dmg` / `.AppImage`).
- **Backwards-compat tooling** — `maverick migrate` (`migrate.py`): walks an
  existing config forward — real migration advisories (Twilio WhatsApp → the
  first-party Cloud API adapter), unknown-section lint with did-you-mean
  suggestions (a typo'd section silently no-ops), and a mechanical-rename
  engine that only writes behind a timestamped backup (rename table empty
  today; 2.0 renames land on it). Dry-run default.
- **Deployment blueprints** — reference architectures for **Kubernetes / AWS
  ECS (Fargate) / Fly.io / Railway** (`deploy/reference-architectures/`):
  contract-tested manifests sharing the canonical image, `:8765` dashboard
  surface, `/root/.maverick` state volume, and secrets-from-platform-store
  rule. **Devcontainer + Codespaces template** (`.devcontainer/`) mirrors CI's
  editable install so `maverick --help` and the test suite work on open.
- **Scaffold generators** — `template_generator` tool: emit a validator-clean
  `SKILL.md` (op=skill) or a `Channel`-subclass adapter scaffold with the
  start/send/stop seams (op=channel); deterministic codegen.
- **IDE / CI** — VS Code extension (`apps/vscode-extension/`), **Emacs
  package** (`apps/emacs/maverick.el`: M-x maverick-start/status/monitor/
  logs/halt/unhalt over the CLI, deps-free, Emacs 27.1+), **Neovim plugin**
  (`apps/nvim/`: :MaverickStart/Status/Monitor/Logs/Halt/Unhalt, lazy.nvim-
  ready, terminal-split UX), **Zed extension** (`apps/zed-extension/`:
  registers `maverick mcp` as a context server — Zed extensions run in a
  WASI sandbox and cannot exec, so CLI verbs ship as Zed tasks; compiling
  needs the Zed SDK, stated in its README), GitHub Action wrapper
  (`maverick-action`) — all contract-tested against the real CLI verb set.
- **Native desktop app** (`apps/desktop/`): a Tauri v2 shell for the local
  dashboard — splash polls `127.0.0.1:8765/healthz` and redirects, spawning
  `maverick dashboard` as its own child when the port is closed (kills only
  that child on exit); macOS/Windows/Linux bundle targets, ships unsigned
  (installer-desktop posture), building needs Rust + Tauri CLI.
- **Windows MSI** (`apps/installer-msi/`): WiX v4 authoring set — per-user
  scope, stable UpgradeCode + MajorUpgrade, user-PATH component, a launcher
  that bootstraps the bundled wheel into the console-script target —
  plus `build.ps1` and a dispatch-only `build-msi.yml` workflow; building
  and signing happen on a Windows host (maintainer act), output ships
  unsigned like the Tauri installer.
- **Multi-arch builds** (`deploy/multiarch/`): buildx Dockerfile + script
  for linux/amd64 + arm64 + riscv64 (ARG-gated base with a debian-sid
  CPython fallback for riscv64) — core+shield are pure Python; the README
  carries the honest per-extra wheel-availability table (grpcio/torch/
  pyarrow et al. lack riscv64 wheels) and the QEMU/binfmt CI commands.
- **Hosted demo cluster blueprint**
  (`deploy/reference-architectures/demo-cluster/`): compose + k8s manifests
  for a public read-only demo — the dashboard has no global read-only flag,
  so an nginx deny-proxy (`limit_except GET HEAD`) fronts it with the
  bearer injected upstream; a seeder creates finished demo goals through
  the real world model; DNS/TLS/operating demo.maverick.dev is a
  maintainer act. Contract-tested like the other reference architectures.
- **Mobile skill execution scaffolds** (`apps/mobile-skills/`): a Pyodide
  runner page (vendored-only Pyodide, no CDN; pinned release + fill-on-
  download checksum) executing a verified pure-stdlib repo module in a
  mobile browser, and a Kivy shell + buildozer.spec for Android — store
  builds are maintainer acts; the hard limits (no sandbox/subprocess on
  mobile, relay for network) are documented, not papered over.
- **RFCs** — [RFC 0001: Maverick 2.0](./rfcs/0001-maverick-2.0.md) (config
  schema v2 + async-only channel SDK + connector re-homing, migration story
  riding `maverick migrate`) and [RFC 0002: Plugin API v2](./rfcs/0002-plugin-api-v2.md)
  (static manifests discovered without importing plugin code, lifecycle hooks,
  the wire shape for the gRPC plugin host) — both Draft, open for comment.
- **Embeddable widgets** — two dependency-free `<script>`-tag surfaces,
  both self-hosted: the floating **chat widget**
  (`web/widget/maverick-widget.js`) posting to your own dashboard's
  `/chat/send`, and the read-only **status widget**
  (`extensions/widget/maverick-widget.js`): a Shadow-DOM pill → panel
  polling the real goals API and bucketing counts client-side, with the
  auth posture documented exactly (Bearer header only; same-origin or a
  reverse proxy — the dashboard ships no CORS; the token is the full
  control surface, so embed only where you'd paste the token).
- **Self-hosted relay** — a stdlib edge service (`deploy/relay/relay.py`) that
  HMAC-signs an inbound POST and forwards it to a dashboard's `/webhook/start`
  exactly as `maverick.webhooks` verifies (replay-defended; signature
  round-trip tested) — the self-hostable counterpart to a hosted bridge.
- **Docs** — MkDocs site, [getting started](./getting-started.md), 30-recipe
  [cookbook](./cookbook/), [architecture](./architecture.md),
  [embedding guide](./embedding.md), [security hardening](./security-hardening.md),
  [comparison page](./comparison.md) (Maverick vs the field, claims grounded in
  this catalogue), [press kit](./press-kit.md), [showcase wall](./showcase.md)
  (built-with-Maverick submissions by PR), and a self-serve
  [observability integrations guide](./integrations/observability-partners.md)
  (OpenRouter provider, OTLP-generic tracing incl. LangSmith, Helicone via
  base_url override).
- **Long-form handbook** ([`docs/handbook.md`](./handbook.md)): the front
  door — mental model, guided tour, day-2 operations, safety posture,
  extension points, and a map of every other doc; every cited command and
  module verified against the tree.
- **Localized docs** ([`docs/i18n/`](./i18n/)): real, native-quality human
  translations of the getting-started guide into **9 languages** — Spanish,
  Japanese, German, French, Brazilian Portuguese, Korean, Russian, Italian,
  Hindi — each following its language's software-docs register, with code
  blocks/commands/paths kept byte-identical and a source-commit header so
  staleness is trackable. The **docs MT pipeline** (`docs_i18n.py`, `python
  -m maverick.docs_i18n`) machine-translates the tail under hard quality
  gates (fenced code preserved, glossary + structure verified before
  anything is written, human translations never overwritten); `--check` is
  offline, and the model resolves by the `translator` role.
- **Distribution program kits** ([`docs/programs/`](./programs/)): 24
  runnable playbooks — Summit v1 (virtual) + Summit v2 (hybrid delta) +
  Conference v3 (flagship delta), university outreach, integration
  partnerships (business half), GitHub Stars campaign, office hours,
  sponsorship tiers (incl. the tier-2 gate + renewal terms), conference
  booth, swag, ambassadors, Skill of the Year, community survey,
  foundation exploration, badge program, curriculum kit, community grants,
  regional meetups, hackathon series, localized communities, public
  roadmap voting, skill + channel certification (mechanical bars over the
  real gates), tutorial video seasons 2-4 (per-episode scripts, every
  command verified), and press kit v2 + an evidence-gated case-study
  template. Each kit reuses the shipped machinery (skill validator,
  moderation gauntlet, ratings, plugin matrix CI, sigstore/CA signing,
  retrospective generators) instead of inventing parallel process; founder
  decisions (amounts, dates, license grants) are explicitly marked, never
  invented; executing the programs is a maintainer act.
- **2.0 release machinery** ([`docs/migration-2.0.md`](./migration-2.0.md)
  + [`docs/release-checklist-2.0.md`](./release-checklist-2.0.md)): the
  operator migration playbook (rehearsable today — snapshot, `maverick
  migrate`/`schema-plan`/`config-lint` dry runs, apply, verify, rollback)
  and the release gate the maintainer cut runs through (CI matrix,
  contract checks, deprecation sunsets, migration rehearsal, LTS branch
  cut, signing). **Governance**: the Safety Steering Group charter
  ([`docs/governance/safety-steering-group.md`](./governance/safety-steering-group.md))
  and the elected-TSC charter draft with explicit launch gates
  ([`docs/governance/governance-v2-tsc.md`](./governance/governance-v2-tsc.md)).
  **Strategy**: the five-year vision essay
  ([`docs/strategy/vision-2031.md`](./strategy/vision-2031.md)), every
  backward-looking claim grounded in this catalogue.
- **AR plan tree (visionOS scaffold)** (`apps/visionos-plan-tree/`):
  SwiftUI + RealityKit volumetric window rendering the goal forest from
  `GET /api/v1/goal-tree` — status-colored spheres, parent link bars,
  pinch-to-inspect card; read-only, bearer-token honored. Building/tuning
  needs Xcode + the visionOS SDK (and honest on-device verification is
  flagged in the source), per the watch-glance scaffold posture.
