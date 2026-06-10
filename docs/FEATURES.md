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
- **Local continuous learning** — distill successful run trajectories into a
  reusable, validator-compliant `SKILL.md` under `~/.maverick/learned-skills`
  (`skill_distillation_local.py`), opt-in via `[self_learning] distill_local`.
  **v2** (`skill_distillation_v2.py`) adds two quality gates so the loop stays
  useful: it won't distill from fewer than N successful trajectories (a one-off
  success is noise), and it dedups a candidate against the learned-skills store
  by lexical containment so near-duplicate lessons don't accumulate — the
  orchestrator uses the gated path.
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
- **System** — `shell` (sandbox-mediated), `git_advanced`, `compute`,
  `dns_lookup`, `openapi_runner`, `clipboard`, `notify`, `attachments`,
  `android` / `ios_sim`, `a11y`, `task_graph` (persistent dependency-DAG of
  tasks), `workspace_snapshot` (snapshot/restore a working dir), **S3-backed
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
  guarantee when a bound is hit).
- **Extensibility** — `@tool` decorator (`tools/decorator.py`): turn a typed
  function into a registered Tool with a signature-derived JSON Schema, no
  boilerplate. **Plugin sandboxing** — opt-in
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
(`email_v2.py`).

## Sandboxes

7 run-to-completion backends (`sandbox/`): local subprocess, Docker, SSH, Podman,
devcontainer, Firecracker microVM, Kubernetes. Selected via `[sandbox] backend`.
**gVisor** is offered as a backend (`backend = "gvisor"`): Docker with the
`runsc` runtime (`--runtime=runsc`), interposing a userspace application kernel
between a possibly prompt-injected agent and the host — stronger isolation than
seccomp + dropped capabilities alone. It reuses every Docker knob (image,
network, memory/pids/cpu caps, non-root); `[sandbox] runtime` overrides the
runtime for a custom registration.

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
- **A2A** (`a2a.py`, `a2a_tasks.py`) — Agent Card discovery + delegation.
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
- **Access control** — tool ACLs, consent prompts + a persistent **consent
  ledger** (`safety/consent.py`; `MAVERICK_CONSENT_MODE` =
  auto-approve / auto-deny / ask / dashboard), capability tokens
  (`capability.py`), role-based access control over capabilities, the
  `self_capability` self-report tool, **capability revocation**
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
- **Audit & compliance** — signed append-only audit log (`maverick audit verify`),
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
  UNIQUE constraints**, and a **strict-isolation mode** (`[world_model]
  strict_tenant_isolation`).
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

**Chaos game-day drill** (`chaos_gameday.py`,
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

`benchmarks/`: GAIA, τ²-bench-style stateful harness, terminal-bench-style
harness, SWE-bench harness, moat suite, and an **adversarial-cost suite**
(`eval_adversarial_cost.py`): scripted money-wasting scenarios — tool loops,
token bombs, runaway iterations — each asserted CLAMPED by the cache /
output-cap / Budget ceilings; `main()` exits 1 on any unclamped scenario. All
CI-runnable on shipped fixtures.

## Observability & reliability

OpenTelemetry traces, Prometheus `/metrics`, and a **Sentry performance
tab** (all opt-in) (`observability.py`): `MAVERICK_SENTRY_DSN` (or
`[observability] sentry_dsn`) initializes Sentry tracing and every existing
`trace_span` call feeds it — a transaction at the root (episodes), child spans
inside (tools) — sample rate via `MAVERICK_SENTRY_TRACES_SAMPLE_RATE`, PII off,
`[sentry]` extra; per-tool latency profiles + extended stats
(`tool_latency.py`); opt-in per-tool **latency budget** (`latency_budget.py`) and
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
(`egress_accounting.py`); **run health score** (`health_score.py`); **replayable
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
classifier; read-only — the operator sets the value. **Continuous profiling daemon** (`profiling_daemon.py`,
`python -m maverick.profiling_daemon`, opt-in `[perf] profiling`): a sampling
profiler that periodically runs `py-spy record` against the live process and
drops speedscope/flame-graph profiles under `data_dir("profiles/")` — py-spy
samples from outside the interpreter (no GIL cost) so it's safe to leave on in
production; default-OFF, with an injectable runner/clock so the schedule is
tested without spawning py-spy.

## UX surfaces

- **CLI** — `maverick init` (wizard — with **branching paths**: a mode picker
  routes consumer users to a tailored short flow (`run_consumer`) while
  advanced users get the full step sequence, and the deployment answer
  (desktop/docker/vps/phone) filters the channel/sandbox questions that
  follow; `--fast` and `--resume` skip/restore branches), `start`, `resume`, `monitor` (Rich plan-tree
  TUI), `status --cost`, `export`, `replay`, `logs`, `ps`, `whoami`, and
  `maverick diag` (circuit-breaker states, provider rate-limit counts, per-goal
  health score, cost-by-tag, and replay of a `MAVERICK_TRACE_DIR` run trace).
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
- **Smart notification batching** — opt-in `[notifications]
  batch_window_seconds` (`notification_batcher.py`): coalesces the
  low/normal-priority push stream (ntfy/Pushover/Discord/Slack) into one
  windowed digest ("5 updates" with the lines folded in) so a long run doesn't
  turn a phone into a slot machine; **high/urgent** notifications cut the line
  and deliver immediately (flushing any pending batch first, so order holds). A
  daemon flusher drives the window; unconfigured, `notify()` is unchanged.

## Distribution & install

- **Packaging** — 6 packages on PyPI, GHCR Docker image, PyInstaller binaries,
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
  ready, terminal-split UX), GitHub Action wrapper (`maverick-action`) — all
  contract-tested against the real CLI verb set.
- **RFCs** — [RFC 0001: Maverick 2.0](./rfcs/0001-maverick-2.0.md) (config
  schema v2 + async-only channel SDK + connector re-homing, migration story
  riding `maverick migrate`) and [RFC 0002: Plugin API v2](./rfcs/0002-plugin-api-v2.md)
  (static manifests discovered without importing plugin code, lifecycle hooks,
  the wire shape for the gRPC plugin host) — both Draft, open for comment.
- **Docs** — MkDocs site, [getting started](./getting-started.md), 30-recipe
  [cookbook](./cookbook/), [architecture](./architecture.md),
  [embedding guide](./embedding.md), [security hardening](./security-hardening.md),
  [comparison page](./comparison.md) (Maverick vs the field, claims grounded in
  this catalogue), [press kit](./press-kit.md), [showcase wall](./showcase.md)
  (built-with-Maverick submissions by PR), and a self-serve
  [observability integrations guide](./integrations/observability-partners.md)
  (OpenRouter provider, OTLP-generic tracing incl. LangSmith, Helicone via
  base_url override).
