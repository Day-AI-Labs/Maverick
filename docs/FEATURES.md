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
- **Verifier default-on** across goal types (`verifier.py`); **reflexion** retry
  loop with cross-session failure memory (`reflexion.py`); graded **critic** for
  structured accept/revise/reject feedback (`critic.py`).
- **Planning topologies** — tree-of-thought (`tree_of_thought.py`), debate
  (`debate.py`), speculative decode/finalize (`speculative.py`), latency-aware
  best-of-N that cancels laggards (`latency_best_of_n.py`), shared-scratchpad
  blackboard (`blackboard.py`), cross-agent bus (`agent_bus.py`).
- **Context lifecycle** — deferred tool loading + `find_tools`, cross-session
  `memory` tool (`tools/memory.py`), programmatic tool calling
  (`tools/code_exec.py`), structural/retrieval-augmented compaction
  (`compaction.py`, `context_compactor.py`), and a **long-context retrieval
  router** (`long_context_router.py`) that shards an oversized payload (e.g. a
  document pasted into a goal) and keeps only the query-relevant shards instead
  of overflowing the model window — zero-dep lexical ranking by default, an
  injected Chroma/Qdrant store for embedding-quality retrieval; opt-in via
  `[context] retrieval_router`.
- **Local continuous learning** — distill successful run trajectories into a
  reusable, validator-compliant `SKILL.md` under `~/.maverick/learned-skills`
  (`skill_distillation_local.py`), opt-in via `[self_learning] distill_local`.

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
  (transcribe/speak), `ffmpeg_tool`, `imagemagick_tool`, `pandoc_tool`,
  `replicate_tool` (image/video/audio gen), `latex` (math→MathML + document→PDF),
  `diagram` (Graphviz / Mermaid render).
- **Knowledge** — `knowledge_search` (per-domain RAG over collected docs),
  `recall`, `kv_memory`.
- **Productivity & SaaS connectors (~47)** — GitHub Actions, GitLab, Jira, Linear,
  Asana, Trello, ClickUp, Confluence, Notion, Obsidian, Slack, Discord, Gmail,
  Google Drive, Dropbox, Calendar, Salesforce, HubSpot, Stripe, Shopify, Plaid,
  Twilio, Zoom, S3, DynamoDB, MongoDB, Redis, Elasticsearch, Datadog, Sentry,
  PagerDuty, Mixpanel, PostHog, Plausible, GA4, Home Assistant, Cloudflare,
  Vercel, AWS Lambda/SES/SNS, Microsoft Graph, and more.
- **System** — `shell` (sandbox-mediated), `git_advanced`, `compute`,
  `dns_lookup`, `openapi_runner`, `clipboard`, `notify`, `attachments`,
  `android` / `ios_sim`, `a11y`, `task_graph` (persistent dependency-DAG of
  tasks), `workspace_snapshot` (snapshot/restore a working dir), `license_scan`
  (classify deps + flag copyleft), `self_capability` (report the run's capability
  grant), `oidc` (OIDC authorization-code client), `cost_curve` (per-provider cost
  model), `bench_track` (record benchmark scores + flag regressions), `teams`
  (Microsoft Teams webhook), `knowledge_graph` (extract/query/render
  subject-relation-object triples; no external graph DB), `cross_repo_deps`
  (cross-repo Python package import graph + cycle detection via `ast`),
  `citation_verifier` (check cited quotes against their source text), `test_gen`
  (generate a Hypothesis property-test scaffold from a function's signature),
  `semantic_code_search` (rank functions/classes by intent via ast + lexical
  scoring), `mutation_test` (plan source mutants a strong suite should catch),
  `constrained_output` (validate/coerce a value to a typed/enum/range/regex
  shape — the guard half of constrained generation), `model3d_inspect`
  (headless 3D-mesh stats — triangle/vertex counts + bounding box for STL/OBJ),
  `synthetic_data` (deterministic synthetic rows from a field spec, json/csv),
  `web_recorder` (generate a runnable Playwright script from a list of browser
  steps — deterministic codegen with escaped literals), `a11y_tree` (distill raw
  HTML into a compact accessibility tree — landmarks/headings/links/controls —
  for a 5-10x token cut), `cache_admin` (inspect/purge the
  tool-output cache — stats or targeted purge), `error_patterns` (cluster noisy
  error/log lines into ranked patterns by normalised signature), `container_build` (build a
  container image from a Dockerfile via sandbox-mediated `docker build`).
- **Extensibility** — `@tool` decorator (`tools/decorator.py`): turn a typed
  function into a registered Tool with a signature-derived JSON Schema, no
  boilerplate.

## Channels

14 wired channels (`packages/maverick-channels/`): Telegram, Discord, Slack,
Signal, Email, Matrix, Bluesky, Mastodon, Voice (Twilio), WhatsApp, SMS, iMessage
(macOS), **IRC** (channels + DMs, TLS), and a **glasses/wearable** adapter
(Even Realities G2 "bring your own agent" bridge: the ack-then-run pattern that
answers quick utterances on the HUD within the device deadline and runs long
tasks in the background, delivering the result to a secondary channel). Rich
formatting + dedup + per-channel authz. **Email v2** adds IMAP IDLE (push
instead of poll) + conversation threading from Message-ID/In-Reply-To/References
(`email_v2.py`).

## Sandboxes

7 run-to-completion backends (`sandbox/`): local subprocess, Docker, SSH, Podman,
devcontainer, Firecracker microVM, Kubernetes. Selected via `[sandbox] backend`.

## LLM providers & routing

12 providers, routable per role (`llm.py`): Anthropic, OpenAI, OpenRouter,
Ollama, Gemini, DeepSeek, Bedrock, Azure, xAI, Moonshot, TGI, vLLM (generic
OpenAI-compatible via `base_url`). Cost-aware routing (`cost_router.py`) and
provider failover (`provider_failover.py`), both opt-in. **Local-first routing**
prefers a reachable local model before remote (`provider_local_first.py`);
**energy-aware routing** downgrades to a cheaper model on low battery
(`energy_aware_router.py`); both opt-in and default-OFF.

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
- **Elicitation** — client inbound (policy + shield) and server outbound form
  mode.
- **MCP Tasks (2025-11-25)** — task-augmented `tools/call` → `CreateTaskResult`,
  background worker, `tasks/get|result|cancel|list`, status notifications.
- **MCP client** (`mcp_client.py`) — consume remote HTTP servers; **OAuth 2.1
  client-credentials and authorization-code + PKCE** grants (`mcp_oauth.py`).
- **MCP registry** (`mcp_registry.py`) — `maverick mcp-registry browse/add/...`.
- **A2A** (`a2a.py`, `a2a_tasks.py`) — Agent Card discovery + delegation.
- **gRPC API** (`grpc_api/`) — typed, streaming surface for driving the runtime
  from any language: `StartGoal` / `StreamEpisode` (server-stream of episode
  events) / `Cancel` / `GetStatus`. Behaviour lives in a transport-agnostic
  `GoalService`; the gRPC shim compiles stubs on demand from the bundled
  `maverick.proto`. Behind the `[grpc]` extra; run via `python -m maverick.grpc_api`.
- **Cross-language quickstarts** — TypeScript, Go, Rust, C#, Java (`docs/clients/`).
- **LangChain / LangGraph interop** (`langchain_adapter.py`, `[langchain]` extra)
  — expose the Maverick swarm as a LangChain `StructuredTool`, and wrap any
  LangChain `BaseTool` as a Maverick tool.
- **MCP-client language analytics** (`mcp_analytics.py`) — opt-in, consent-gated
  tally of client language (from the User-Agent) that feeds the language-bindings
  decision gate (`non_python_share()`); off by default.

## Safety & security

- **Shield** at 3 chokepoints (input / tool-call / output); built-in rule set
  fail-open if the SDK isn't installed.
- **Floors** — secret detector, PII detector, jailbreak heuristics, unicode /
  zero-width filter, remote-content scan, output-policy classifier
  (regurgitation + refusal-leak), **phishing-content detector** (credential-harvest
  + deceptive-link heuristics, composed into `Shield.scan_output`),
  **operator-defined constitutional rules** (custom regex policy via `[safety]
  constitution`, `maverick_shield/constitutional.py`),
  Constitutional-Classifier-v2 cascade (`safety/`, `maverick_shield/`).
- **Access control** — tool ACLs, consent prompts, capability tokens
  (`capability.py`), role-based access control over capabilities, the
  `self_capability` self-report tool, **approval delegation rules**
  (risk/scope-based routing, `approval_delegation.py`), per-tool network egress
  policy (`sandbox/network_policy.py`), `maverick whoami`.
- **Audit & compliance** — signed append-only audit log (`maverick audit verify`),
  date-windowed **SIEM export**, encryption-at-rest (`crypto_at_rest.py`,
  `maverick encryption migrate`), SOC2 readiness (`soc2.py`), DSAR (`dsar.py`),
  per-run file-write + tool quotas, `maverick compliance --strict`, CycloneDX
  SBOM in CI.
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
- **maverick-knowledge** — per-domain vector RAG package backing `knowledge_search`.
- **Reverse-proxy SSO** — trusted forwarded-identity header for enterprise auth.
- **Tenant-aware persistence** — workspaces wall each tenant into
  `~/.maverick/tenants/<t>/` (`workspace.py`, `paths.py`), with a per-tenant
  world DB and `data_dir()`-routed audit / quotas / DSAR / fleets. The shared
  **Postgres** backend (`[world_model] backend = "postgres"`) carries a
  **versioned migration runner** (`schema_migrations` ledger), a `tenant_id` on
  every root table (write-stamped, read-scoped), **tenant-aware UNIQUE
  constraints**, and a **strict-isolation mode** (`[world_model]
  strict_tenant_isolation`).
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
- **Out-of-process execution** — a swappable goal **Dispatcher** (`runner.py`)
  with a **QueueDispatcher** (`queue_dispatcher.py`) that enqueues goals for a
  worker pool (arq adapter behind `[queue]`; `install_from_config` wires it).

## Evaluation & benchmarks

`benchmarks/`: GAIA, τ²-bench-style stateful harness, terminal-bench-style
harness, SWE-bench harness, moat suite — CI-runnable on shipped fixtures.

## Observability & reliability

OpenTelemetry traces, Prometheus `/metrics`, Sentry (all opt-in)
(`observability.py`); per-tool latency profiles + extended stats
(`tool_latency.py`); opt-in per-tool **latency budget** (`latency_budget.py`) and
cross-span **budget propagation** (`latency_span_budget.py`); **tool-output cache**
for read-only tools (`tool_cache.py`); **network egress accounting**
(`egress_accounting.py`); **run health score** (`health_score.py`); **replayable
trace** format (`replay_trace.py`); **cost split by tag** (`cost_by_tag.py`) and
**provider cost-curve fitter** (`cost_curve_fitter.py`); provider health board
(`provider_health.py`); proactive **provider rate-limit predictor**
(`rate_limit_predictor.py`); shared tool-reliability layer (`tool_reliability.py`,
`retry.py`); circuit breaker (`circuit_breaker.py`); adaptive thinking budget
(`thinking_budget.py`).

## UX surfaces

- **CLI** — `maverick init` (wizard), `start`, `resume`, `monitor` (Rich plan-tree
  TUI), `status --cost`, `export`, `replay`, `logs`, `ps`, `whoami`, and
  `maverick diag` (circuit-breaker states, provider rate-limit counts, per-goal
  health score, cost-by-tag, and replay of a `MAVERICK_TRACE_DIR` run trace).
- **GitHub App** — `/webhook/github` (dashboard): a labeled or `/maverick`-mentioned
  issue drives a swarm that clones the repo, fixes it, and opens a PR
  (`github_app.py`, HMAC-verified).
- **Web dashboard** — run list, plan-tree, chat at `/chat`, approval queue, and
  an **oversight console** (`/oversight`): live fleet state, the approval queue,
  a per-guardrail intervention roll-up, and an inline **"why this action"
  drill-down** (the reasoning/tool chain + cost for a running agent, owner-scoped)
  (`maverick dashboard`). **Search across runs** — a live search box on the
  goals page over `GET /api/v1/goals/search` (text match on title/description/
  result, owner-scoped, decrypt-then-filter since those fields are encrypted at
  rest).
- **Cost** — per-run reports, live cost meter, `maverick start --dry-cost`
  forecasting (`cost_forecast.py`).
- **Templates** — starter-goals library + community template registry
  (`maverick template browse/add`).

## Distribution & install

- **Packaging** — 6 packages on PyPI, GHCR Docker image, PyInstaller binaries,
  native double-click installers (Tauri; `.exe` / `.dmg` / `.AppImage`).
- **IDE / CI** — VS Code extension (`apps/vscode-extension/`), GitHub Action
  wrapper (`maverick-action`).
- **Docs** — MkDocs site, [getting started](./getting-started.md), 30-recipe
  [cookbook](./cookbook/), [architecture](./architecture.md),
  [embedding guide](./embedding.md), [security hardening](./security-hardening.md).
