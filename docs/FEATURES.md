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
  loop with cross-session failure memory (`reflexion.py`).
- **Planning topologies** — tree-of-thought (`tree_of_thought.py`), debate
  (`debate.py`), speculative decode/finalize (`speculative.py`), shared-scratchpad
  blackboard (`blackboard.py`), cross-agent bus (`agent_bus.py`).
- **Context lifecycle** — deferred tool loading + `find_tools`, cross-session
  `memory` tool (`tools/memory.py`), programmatic tool calling
  (`tools/code_exec.py`), structural/retrieval-augmented compaction
  (`compaction.py`, `context_compactor.py`).
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
  (Microsoft Teams webhook).
- **Extensibility** — `@tool` decorator (`tools/decorator.py`): turn a typed
  function into a registered Tool with a signature-derived JSON Schema, no
  boilerplate.

## Channels

12 wired channels (`packages/maverick-channels/`): Telegram, Discord, Slack,
Signal, Email, Matrix, Bluesky, Mastodon, Voice (Twilio), WhatsApp, SMS, iMessage
(macOS). Rich formatting + dedup + per-channel authz. **Email v2** adds IMAP IDLE
(push instead of poll) + conversation threading from Message-ID/In-Reply-To/
References (`email_v2.py`).

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

## MCP & agent interop

- **MCP server** (`packages/maverick-mcp/`) — stdio JSON-RPC **and** Streamable
  HTTP transport; tool `outputSchema`, resource subscriptions.
- **Elicitation** — client inbound (policy + shield) and server outbound form
  mode.
- **MCP Tasks (2025-11-25)** — task-augmented `tools/call` → `CreateTaskResult`,
  background worker, `tasks/get|result|cancel|list`, status notifications.
- **MCP client** (`mcp_client.py`) — consume remote HTTP servers; **OAuth 2.1
  client-credentials** (`mcp_oauth.py`).
- **MCP registry** (`mcp_registry.py`) — `maverick mcp-registry browse/add/...`.
- **A2A** (`a2a.py`, `a2a_tasks.py`) — Agent Card discovery + delegation.
- **Cross-language quickstarts** — TypeScript, Go, Rust, C#, Java (`docs/clients/`).

## Safety & security

- **Shield** at 3 chokepoints (input / tool-call / output); built-in rule set
  fail-open if the SDK isn't installed.
- **Floors** — secret detector, PII detector, jailbreak heuristics, unicode /
  zero-width filter, remote-content scan, output-policy classifier
  (regurgitation + refusal-leak), **phishing-content detector** (credential-harvest
  + deceptive-link heuristics, composed into `Shield.scan_output`),
  Constitutional-Classifier-v2 cascade (`safety/`, `maverick_shield/`).
- **Access control** — tool ACLs, consent prompts, capability tokens
  (`capability.py`), role-based access control over capabilities, the
  `self_capability` self-report tool, per-tool network egress policy
  (`sandbox/network_policy.py`), `maverick whoami`.
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
- **maverick-knowledge** — per-domain vector RAG package backing `knowledge_search`.
- **Reverse-proxy SSO** — trusted forwarded-identity header for enterprise auth.
- **Process table** — `maverick ps` (unified view of runs/workers).
- **Scheduling** — recurring autonomous goals from a prompt; `worker --once`
  cron-friendly drain (`scheduler.py`, `job_queue.py`, `worker.py`).

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
(`provider_health.py`); shared tool-reliability layer (`tool_reliability.py`,
`retry.py`); circuit breaker (`circuit_breaker.py`); adaptive thinking budget
(`thinking_budget.py`).

## UX surfaces

- **CLI** — `maverick init` (wizard), `start`, `resume`, `monitor` (Rich plan-tree
  TUI), `status --cost`, `export`, `replay`, `logs`, `ps`, `whoami`.
- **Web dashboard** — run list, plan-tree, chat at `/chat`, approval queue
  (`maverick dashboard`).
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
