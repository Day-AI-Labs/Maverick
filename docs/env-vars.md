# Environment variables

Lightwork's primary configuration is `~/.maverick/config.toml` (see
[configuration.md](configuration.md)). The `MAVERICK_*` environment variables
below are a complement: they override the equivalent config keys when set, and
expose a handful of knobs that have no config equivalent. **Env vars win over
config.** Most users never need to set any of these — the defaults are the
out-of-the-box behavior. They're documented here for operators tuning a
deployment.

Boolean vars accept `1`/`true`/`yes`/`on` for true and `0`/`false`/`no`/`off`
for false unless noted otherwise.

## Core / run

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_CONFIG` | `~/.maverick/config.toml` | Path to an alternate config file. |
| `MAVERICK_CODING_MODE` | unset | When `1`/`true`/`yes`, switches the agent into coding mode (set by `maverick start --coding-mode`); affects prompts, fs/shell tool defaults, and cache TTL. |
| `MAVERICK_LANGUAGE` | unset | Primary project language hint (e.g. `python`, `go`). Feeds sandbox/toolchain selection and coding mode. |
| `MAVERICK_MAX_STEPS` | `25` | Global cap on agent loop steps per goal. |
| `MAVERICK_STEP_BUDGET_WARNING` | `3` | When this many tool-using turns remain before `MAVERICK_MAX_STEPS`, the loop nudges the agent to give its FINAL answer (so a long run isn't cut off mid-work). `0` disables. |
| `MAVERICK_MAX_SWARM_FANOUT` | `8` | Max child agents a single spawn call may branch into. |
| `MAVERICK_MAX_TOTAL_SPAWNS` | `64` | Process-wide cap on total spawned agents across a run. |
| `MAVERICK_MAX_CONCURRENT_GOALS` | `16` | Global ceiling on goals running in parallel — a host-overload backstop, sized so normal multi-user load never reaches it. |
| `MAVERICK_MAX_CONCURRENT_GOALS_PER_PRINCIPAL` | `3` | Per-user concurrency lane: one principal can run this many goals at once without blocking other users (fair scheduling). |
| `MAVERICK_GOAL_ACQUIRE_TIMEOUT` | `300` | Seconds to wait for a goal-execution slot (per-user lane, then global) before giving up. |
| `MAVERICK_PARALLEL_TOOLS` | `1` (on) | Set `0` to run tool calls within a turn serially instead of in parallel. |
| `MAVERICK_LOOP_GUARD` | `1` (on) | Set `0` to disable the repeated-failure loop guard (nudges the agent when it re-issues the same failing tool call). |
| `MAVERICK_LOOP_GUARD_THRESHOLD` | `3` | Consecutive identical tool-call failures before the loop guard nudges (min 2). |
| `MAVERICK_HALT_FILE` | `~/.maverick/HALT` | Killswitch path; the run aborts if this file exists. |
| `MAVERICK_NO_CLI` | unset | `1` marks embedded mode: skips third-party plugin auto-discovery and CLI-only paths. |
| `MAVERICK_NO_PROGRESS` | unset | Set to suppress the live progress display. |
| `MAVERICK_DEBUG` | unset | `1` re-raises original exceptions and prints full tracebacks instead of friendly errors. |
| `MAVERICK_NO_WIZARD` | unset | `1` runs the installer non-interactively (used by the unattended install scripts). |

## Budget & limits

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_BUDGET_DOLLARS` | config `[budget]` | Override the dollar budget cap for a run. |
| `MAVERICK_DEFAULT_MAX_DOLLARS` | `2.0` | Default per-goal dollar ceiling when none is supplied. |
| `MAVERICK_DEFAULT_MAX_WALL_SECONDS` | `1800` | Default per-goal wall-clock ceiling (seconds). |
| `MAVERICK_DEFAULT_MAX_DEPTH` | `3` | Default max recursion depth for spawned sub-goals. |

## Models & routing

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_MODEL_OVERRIDE` | unset | Global run-wide model override (`provider:model-id`); set by `maverick --model`. Beats config for every role. |
| `MAVERICK_MODEL_OVERRIDE_<ROLE>` | unset | Per-role override, e.g. `MAVERICK_MODEL_OVERRIDE_CODER`. Beats the global override for that role. |
| `MAVERICK_TEMPERATURE` | provider default | Sampling temperature for LLM calls. |
| `MAVERICK_VISION_MODEL` | `anthropic:claude-sonnet-4-6` | Model used by the image/video viewing tools (`provider:model-id`). |
| `MAVERICK_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model id. |
| `MAVERICK_COST_ROUTING` | config `[routing] cost_aware` (off) | Enable cost-aware model routing. |
| `MAVERICK_CASCADE_ROUTING` | config `[models] cascade` (off) | Enable cascaded routing (cheap model first, escalate on need). |
| `MAVERICK_ESCALATE_BELOW` | `0.6` | Verifier-confidence threshold below which a cascade escalates to a stronger model. |
| `MAVERICK_ESCALATE_TOOL_DEPTH` | `3` | Tool-call depth at which a cascade escalates. |
| `MAVERICK_ANTHROPIC_CACHE_TTL` | `1h` (coding mode: `5m`) | Anthropic prompt-cache TTL; an explicit value always wins. |
| `MAVERICK_CACHE_MESSAGES` | `1` (on) | Set `0` to disable prompt caching of message history. |
| `MAVERICK_LLM_CACHE` | unset (off) | Enable the on-disk LLM response cache. |
| `MAVERICK_LLM_RETRY_ATTEMPTS` | `5` | Max retry attempts for failed LLM calls. |
| `MAVERICK_LLM_RETRY_BASE_DELAY` | `1.0` | Base backoff delay (seconds) between LLM retries. |
| `MAVERICK_LLM_RETRY_MAX_DELAY` | `30.0` | Max backoff delay (seconds) between LLM retries. |
| `MAVERICK_LLM_CONNECT_TIMEOUT` | `15.0` | LLM connect timeout (seconds). |
| `MAVERICK_LLM_READ_TIMEOUT` | `120.0` | LLM read timeout (seconds). |

## Reasoning & verification

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_BEST_OF_N` | `1` | Generate N candidate solutions and pick the best. |
| `MAVERICK_BON_LADDER` | built-in ladder | Comma-separated best-of-N sample ladder for adaptive escalation. |
| `MAVERICK_TREE_OF_THOUGHT` | unset (off) | Enable tree-of-thought planning: fork candidate plans, critic selects. |
| `MAVERICK_TOT_CANDIDATES` | built-in | Number of candidate plans tree-of-thought forks. |
| `MAVERICK_REFLEXION` | config `[reflexion] enable` (off) | Enable the reflexion self-critique loop. |
| `MAVERICK_DREAMING` | config `[dreaming] enable` (off) | Enable offline experience consolidation (`maverick dream`). |
| `MAVERICK_SELF_HARNESS` | config `[self_harness] enable` (off) | Enable the self-harness loop: learn a model-specific, regression-validated operating-guidance addendum from failure traces (`maverick self-harness`; promotion also needs `[self_improvement] enable`). |
| `MAVERICK_FACTORY_LEARNING` | config `[self_improvement] factory_learning` (off) | Force-enable the self-improving-factory loop: mine provisioning/approval gaps into proposer corrections, promoted on the `prompt` rung and folded into future pack generation (`maverick factory-learn`; needs `[self_improvement] enable`). Overrides config. |
| `MAVERICK_DATA_ENGINE` | config `[data_engine] enable` (off) | Enable the Cognitive Data Engine flywheel: causal failure triage → guardrails → habits (`maverick flywheel`). |
| `MAVERICK_OPERATIONS_SCIENTIST` | config `[operations_scientist] enable` (off) | Enable the Operations Scientist: propose + simulate a better process before a real experiment. |
| `MAVERICK_CONSEQUENCE` | config `[consequence] enable` (off) | Ground learning in real downstream outcomes over the verifier proxy (`maverick record-outcome`). |
| `MAVERICK_EMERGENT_PROTOCOL` | config `[emergent_protocol] enable` (off) | Enable the auditable coordination codec (sentinel form; `maverick codebook`). |
| `MAVERICK_EMERGENT_CODEC` | config `[emergent_codec] enable` (off) | Measure the token-aware codec on the live coordination stream (telemetry only; `maverick codec-learn`). |
| `MAVERICK_DOMAIN_DISCIPLINE` | config `[domains] discipline` (on) | Append suite operating discipline to specialist personas at spawn. |
| `MAVERICK_FLEET_MEMORY` | config `[fleet_memory] enable` (off) | Allow registered external agents to use the governed memory plane. |
| `MAVERICK_PRM` | `null` | Process reward model: `null`, `heuristic`, or `remote`. |
| `MAVERICK_PRM_ENDPOINT` | unset | Endpoint URL when `MAVERICK_PRM=remote`. |
| `MAVERICK_PRM_API_KEY` | unset | API key for the remote PRM endpoint. |
| `MAVERICK_VERIFY_ENSEMBLE` | config `[routing] verify_ensemble` (off) | Run the multi-model verifier panel (stronger, ~Nx cost). |
| `MAVERICK_VERIFIER_CONFIDENCE` | `0.75` | Confidence threshold at which the verifier accepts a result. |
| `MAVERICK_DISAGREEMENT_HIGH` | `0.5` | Verifier disagreement level treated as high. |
| `MAVERICK_CROSS_FAMILY_VERIFIER` | config-driven | Force the verifier to use a different model family than the generator. |
| `MAVERICK_SPECULATIVE_FINALIZE` | `1` (on) | Set `0` to disable speculative finalization in the orchestrator. |

## Memory & recall

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_MEMORY_DIR` | `~/.maverick/memory` | Root directory for the cross-session `memory` tool (the agent's model-curated long-term notes). |
| `MAVERICK_AUTO_RECALL` | unset (off) | Auto-recall related prior goals/facts into a run. |
| `MAVERICK_AUTO_RECALL_K` | `3` | Number of prior items to recall when auto-recall is on. |
| `MAVERICK_AUTO_DISTILL` | unset (off) | Auto-distill skills from completed runs. |
| `MAVERICK_SELF_LEARNING` | config `[self_learning] enable` (off) | Enable the self-learning loop. |
| `MAVERICK_SKILL_DECAY` | `1` (on) | Set `0` to disable time-decay of skill usefulness stats. |
| `MAVERICK_ALLOW_SKILL_INSTALL` | unset (off) | Opt in to installing skills from free-text URLs. |
| `MAVERICK_VECTOR_STORE` | config `[memory] backend` | Semantic-recall backend: `chroma`, `qdrant`, `weaviate`, `pgvector`, or unset/`none` to disable. |
| `MAVERICK_CHROMA_PATH` | `~/.maverick/...` default | On-disk path for the Chroma vector store. |
| `MAVERICK_QDRANT_URL` | unset | Qdrant server URL (remote mode). |
| `MAVERICK_QDRANT_PATH` | default path | Qdrant local on-disk path (embedded mode). |
| `MAVERICK_QDRANT_API_KEY` | unset | API key for a remote Qdrant server. |
| `MAVERICK_WORLD_BACKEND` | config-driven | Set `postgres` to use the Postgres world-model backend. |
| `MAVERICK_PG_DSN` | unset | Postgres DSN for the Postgres world model (e.g. `postgres://user:pass@host:5432/maverick`). |
| `MAVERICK_ORPHAN_RECLAIM_SECONDS` | code default | Seconds before orphaned world-model goal locks are reclaimed. |
| `MAVERICK_BLACKBOARD_MAX_ENTRIES` | `5000` (min 100) | Max entries retained in the shared blackboard. |

## Hosted control plane & multi-tenancy

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_STRICT_TENANT_ISOLATION` | config `[world_model] strict_tenant_isolation`; **auto-on under enterprise mode** | Postgres reads return ONLY the active tenant's rows (drop NULL-legacy tolerance). Enable after backfilling `tenant_id`. Env wins over config wins over enterprise default. |
| `MAVERICK_PG_RLS` | config `[world_model] rls`; **auto-on under enterprise mode** | DB-native Postgres Row-Level Security on the tenant tables (defense-in-depth over the app predicate). When auto-enabled by enterprise mode, a boot preflight refuses to start on legacy `tenant_id IS NULL` rows (run `maverick tenant backfill`); explicit `=1` keeps the fail-closed opt-in path. |
| `MAVERICK_KMS_KEK` | derived from the at-rest key | The per-tenant-DEK Key Encryption Key (32 bytes, hex/base64) for `tenant/kms.py`. |
| `MAVERICK_KMS_DEK_CACHE_TTL` | config `[kms] dek_cache_ttl` (`0` = process lifetime) | Seconds a tenant DEK stays cached before it must be re-unwrapped by the KMS. A positive TTL bounds how long a *revoked* cloud-KMS key keeps opening data (the next access re-hits the KMS and fails closed). Per-tenant **BYOK** is configured in each tenant's own `tenants/<id>/config.toml` `[kms]` section (provider/key_id/region), resolved deterministically by `get_kms(tenant_id)`. **Rolling the local KEK** across the fleet: `maverick tenant kms-rotate --old-kek <hex> --new-kek <hex>` (re-wrap only, idempotent/resumable, `--dry-run` to preview); set `MAVERICK_KMS_KEK=<new>` live only after it reports 0 failed. Cloud/BYOK rotation uses `tenant.kms.rotate_kek_fleet` with per-tenant resolvers. |
| `MAVERICK_MCP_ANALYTICS` | config `[analytics] mcp_client_language` (off) | Opt-in, consent-gated tally of MCP-client language (feeds the language-bindings gate). |
| `IRC_ALLOWED_ACCOUNTS` | — | Comma-separated allowlist of authenticated IRC account names that may drive the agent over the IRC channel. Requires an IRC server that provides the IRCv3 `account-tag` capability. |
| `GLASSES_ALLOWED_USER_IDS` | — | Allowlist for the glasses/wearable channel. |
| `IRC_SERVER` / `IRC_PASSWORD` | config `[channels.irc]` | IRC server host / password. |

Config-only knobs (no env var): `[queue] backend = "arq"` (out-of-process goal
execution), `[billing.plans]` (override plan entitlements), `[egress]` /
`[tenancy.egress.<t>]` (per-tenant egress plane). Tenants are managed with
`maverick tenant …`; invoices/entitlements with `maverick billing …`.

## LLM cost & latency

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_EFFORT_ENABLED` | config `[effort] enabled` (off) | Turn on the built-in per-role reasoning-effort profile (`output_config.effort`): orchestrator/coder/revisor stay `high`, bulk roles (researcher/verifier/writer) drop to `medium`, reflector/distiller to `low`. The biggest cost/latency lever on Opus 4.7/4.8. Model-gated (Opus 4.5+/Sonnet 4.6) so it never 400s. |
| `MAVERICK_EFFORT` | unset | Global effort for **all** roles (`low`/`medium`/`high`/`xhigh`/`max`). Wins over config. |
| `MAVERICK_EFFORT_<ROLE>` | unset | Per-role override, e.g. `MAVERICK_EFFORT_CODER=xhigh`. Highest precedence. |
| `MAVERICK_CACHE_PREWARM` | config `[cache] prewarm` (off) | Pre-warm the prompt cache at orchestrator start (`max_tokens=0` prefill) so the first turn's time-to-first-token doesn't pay the cold cache write. Best for interactive surfaces. |
| `MAVERICK_CACHE_MESSAGES` | `1` | Cache the stable message-history prefix (set `0` to disable). |
| `MAVERICK_LOG_TURNS` | unset | Print per-turn `in/out/cache_read/cache_write` token stats to stderr. The Prometheus `maverick_llm_cache_tokens_total` counter (kind=`read`/`creation`/`uncached`) is the metric form — a hit-rate panel surfaces a silent cache invalidator. |

Config equivalents live under `[effort]` (`enabled`, `default`, `<role>`) and
`[cache]` (`prewarm`).

## Compaction & context

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_COMPACT_HISTORY` | config `[context] compact` (off) | Enable history compaction. |
| `MAVERICK_COMPACT_TIKTOKEN` | `1` | Use a real local BPE tokenizer (tiktoken) for compaction token counts when installed; `0` forces the `len/4` heuristic. Fails open to the heuristic if tiktoken is absent. |
| `MAVERICK_HISTORY_WINDOW` | config `[context]` | Max number of recent turns kept verbatim. |
| `MAVERICK_HISTORY_TOKENS` | config `[context]` | Max history tokens before compaction triggers. |
| `MAVERICK_COMPACT_KEEP_RECENT` | `4` | Recent turns always kept uncompacted. |
| `MAVERICK_COMPACT_DIGEST_EVERY` | `10` | Digest older turns every N turns. |
| `MAVERICK_COMPACT_MAX_TOOL_BYTES` | `2048` | Max bytes of tool output retained before truncation during compaction (applies to results behind the recent window). |
| `MAVERICK_MAX_TOOL_RESULT_BYTES` | `100000` | Hard cap on a single tool result (head+tail kept) before it enters the context window, so one runaway `shell`/query output can't blow tokens/budget in a turn. |
| `MAVERICK_RETRIEVAL_ROUTER` | config `[context] retrieval_router` (off) | Enable the long-context retrieval router: when a single payload (e.g. a pasted document in the goal description) exceeds the token threshold, shard it and keep only the shards relevant to the goal, instead of overflowing the model window. |
| `MAVERICK_ROUTER_THRESHOLD_TOKENS` | config `[context]` (`200000`) | Payload size (approx tokens) above which the retrieval router activates. |
| `MAVERICK_ROUTER_TOP_K` | config `[context]` (`12`) | Number of shards the retrieval router retains. |

## Sandbox & tools

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_SUPPRESS_SANDBOX_WARNING` | unset | `1` silences the "running without an isolated sandbox" warning. |
| `MAVERICK_DEFERRED_TOOLS` | unset (on) | `0` disables deferred tool loading, putting every SaaS-connector schema back in the model's per-turn catalog (~600 tools). On by default: the model sees the core toolset + `find_tools` and activates connectors on demand. Also settable via `[capabilities] deferred_tools`. |
| `MAVERICK_CODE_EXEC` | unset (off) | `1` enables the `code_exec` tool (programmatic tool calling: a sandboxed Python script that orchestrates declared tool calls, keeping raw outputs out of context). Also settable via `[capabilities] code_exec`. |
| `MAVERICK_FIRECRACKER_STRICT` | `1` (on) | Set `0` to allow Firecracker to fall back to a Docker/hardened sandbox instead of failing. |
| `MAVERICK_LONG_CMD_TIMEOUT` | `600` | Timeout (seconds) for long-running shell commands. |
| `MAVERICK_PARALLEL_TOOLS` | `1` (on) | See Core / run. |
| `MAVERICK_BROWSER_DISABLE` | unset | `1` disables the browser tool. |
| `MAVERICK_BROWSER_STATE` | unset | Path to a per-task browser storage-state file; setting it enables persistence. |
| `MAVERICK_BROWSER_NO_PERSIST` | unset | `1` disables browser-state persistence even when a state file is set. |
| `MAVERICK_BROWSER_HEADED` | `0` (headless) | `1` runs the browser headed (visible). |
| `MAVERICK_COMPUTER_DISABLE` | unset | `1` disables the computer-use tool. |
| `MAVERICK_COMPUTER_OCR` | unset (off) | Enable OCR of computer-use screenshots. |
| `MAVERICK_CLIPBOARD_DISABLE` | unset | `1` disables the clipboard tool. |
| `MAVERICK_EMAIL_DISABLE` | unset | `1` blocks the email tool from sending. |
| `MAVERICK_WHISPER_MODEL` | `small` | Whisper model size for the voice tool. |
| `MAVERICK_SEARCH_BACKEND` | auto (preference order) | Force a web-search backend: `tavily`, `brave`, `serpapi`, or `ddg`. |
| `MAVERICK_FETCH_ALLOW_PRIVATE` | unset | `1` allows fetching URLs resolving to private/loopback/reserved IPs (SSRF escape hatch). |
| `MAVERICK_FETCH_RESPECT_ROBOTS` | unset | `1` makes the fetch tool honor `robots.txt`. |
| `MAVERICK_FETCH_NO_SCAN` | unset | `1` skips safety scanning of fetched remote content. |
| `MAVERICK_NET_HOST_CONCURRENCY` | `4` | Max concurrent network requests per host. |
| `MAVERICK_ATTACH_MAX_FILE_BYTES` | `26214400` (25 MiB) | Max size of a single attachment file. |
| `MAVERICK_ATTACH_MAX_GOAL_BYTES` | `104857600` (100 MiB) | Max total attachment bytes per goal. |
| `MAVERICK_ALLOW_RAW_MEDIA_ARGS` | unset | `1` passes raw media tool args verbatim (skips sanitization). |
| `MAVERICK_ENABLE_CRED_TOOLS` | unset (off) | Enable credential-handling tools. |
| `MAVERICK_USE_SKILLS` | config `[features] skills` | Override skill injection; `0` disables (e.g. for benchmark runs). |

## Safety & consent

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_CONSENT_MODE` | `auto-approve` | Gating for destructive actions: `auto-approve`, `auto-deny`, `ask`, or `dashboard`. |
| `MAVERICK_CONSENT_DASHBOARD_TIMEOUT` | `300` | Seconds to wait for a dashboard approval before treating as denied. |
| `MAVERICK_MCP_ELICITATION` | `decline` | How the MCP client answers an external server's `elicitation/create`: `decline` (continue without the value), `cancel` (abort the server's op), or `prompt` (collect typed input from an interactive operator, gated through consent). The prompt is shield-scanned either way. |
| `MAVERICK_MCP_ELICITATION_TIMEOUT` | `300` | Seconds the MCP *server* waits for an elicitation response from a stdio client before giving up and leaving the question parked for the async `maverick_answer` flow. |
| `MAVERICK_MCP_MAX_ELICIT_ROUNDS` | `8` | Max elicit→answer→resume rounds the MCP server runs per `maverick_start`/`maverick_resume` call before returning (bounds runaway question loops). |
| `MAVERICK_MCP_TASK_WORKERS` | `4` | Background worker threads for MCP async tasks (concurrent task-augmented tool calls over stdio). |
| `MAVERICK_MCP_MAX_TASKS` | `256` | Max MCP tasks retained in the in-memory registry; the oldest are evicted past this cap. |
| `MAVERICK_MCP_TASK_TTL_MS` | `3600000` | Default task lifetime (ms) when the client doesn't request a `ttl`; the task may be purged after it elapses. |
| `MAVERICK_MCP_TASK_MAX_TTL_MS` | `86400000` | Ceiling (ms) a client-requested task `ttl` is clamped to. |
| `MAVERICK_MCP_TASK_POLL_MS` | `1000` | `pollInterval` (ms) the server suggests to clients in task responses. |
| `MAVERICK_PREFLIGHT` | `warn` | Request preflight mode: `warn` (log only), `strict` (hard-refuse), or `off`. |
| `MAVERICK_AUDIT_SIGN` | config `[audit] sign` (off) | Sign audit-log rows. |
| `MAVERICK_ANON` | config `[privacy] anonymous` (off) | Enable anonymous mode (scrubs home paths and identifying data). |
| `MAVERICK_AI_DISCLOSURE` | config `[compliance] disclosure_text` | AI-disclosure text appended to outputs; empty string opts out. |
| `MAVERICK_STRIPE_ENABLE_REFUNDS` | unset (off) | Required to allow the Stripe tool to issue real refunds. |

## Secrets, residency & audit forwarding

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_SECRETS_BACKEND` | config `[secrets] backend` (`env`) | Where deployment secrets are read from. `env` = process environment (default, unchanged). `file` = mounted secret files (Vault Agent / Secrets Store CSI / Docker/podman secrets), one secret per file, with env fallback. Applies to OIDC client/session secrets, the inbound webhook secret, and the SCIM bearer. |
| `MAVERICK_SECRETS_DIR` | config `[secrets] dir` | Directory the `file` backend reads (`<dir>/MAVERICK_OIDC_CLIENT_SECRET`, etc.; trailing newline trimmed). |
| `MAVERICK_RESIDENCY_STRICT` | config `[residency] strict` (off) | Refuse to boot when the declared data region is missing or outside the allowed set (`require_residency_or_die`). Off = informational only. |
| `MAVERICK_DATA_REGION` | config `[residency] region` | The deployment's declared data region (ISO code or group, e.g. `DE`, `EU`). |
| `MAVERICK_RESIDENCY_ALLOWED` | config `[residency] allowed_regions` | Comma-separated permitted storage regions; `EU`/`EEA` groups expand to members. Empty = region unconstrained. |
| `MAVERICK_SIEM_DEST` | config `[audit] siem_dest` | Destination for `maverick audit forward`: `tcp://host:port` / `udp://host:port` (syslog) or `http(s)://host/path` (Splunk HEC `/raw`, etc.). |
| `MAVERICK_SIEM_TOKEN` | — | Bearer sent on HTTP(S) audit forwarding (read via the secret provider). |

## Observability

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_LOG_LEVEL` | `INFO` | Logging level. |
| `MAVERICK_LOG_FORMAT` | `text` | Log format: `text` or `json`. |
| `MAVERICK_LOG_TURNS` | unset | Set to log full LLM turns (verbose). |
| `MAVERICK_OTEL_EXPORTER` | unset (off) | Set to enable the OpenTelemetry trace exporter. |
| `MAVERICK_OTEL_ENDPOINT` | `http://localhost:4318/v1/traces` | OTLP collector endpoint. |
| `MAVERICK_RESIDENCY_REGION` | config `[residency] region` (unset) | Declare a data-residency requirement (e.g. `eu`). `maverick doctor` then warns about any residency-sensitive feature still defaulting to a US region (`AWS_REGION`→us-east-1, `VERTEX_LOCATION`→us-central1). No effect unset. |
| `MAVERICK_PROMETHEUS_PORT` | unset (off) | Set a port to expose Prometheus metrics. |
| `MAVERICK_PROMETHEUS_ADDR` | `127.0.0.1` | Bind address for the Prometheus metrics server. |
| `MAVERICK_ALERTS` | config `[alerts] enabled` (off) | Enable OPERATIONAL alerts — page the operator (via the configured notification backends) on infrastructure events like a killswitch trip or a deployment-wide provider cost-cap exhaustion. Distinct from agent-task notifications. |

## Plugins

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_PLUGINS_ALLOW` | config `[plugins] enabled` | Comma-separated plugin allowlist; `*` enables all. |
| `MAVERICK_PLUGINS_ENFORCE` | config `[plugins] enforce_permissions` (off) | Enforce plugin permission declarations. |

## Channels & integrations

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_WEBHOOK_SECRET` | unset | HMAC secret for inbound webhooks. **Inbound receivers fail closed (401) without it** — set it before relying on inbound webhook channels (e.g. Twilio SMS / WhatsApp), or they will reject every request. |
| `MAVERICK_WEBHOOK_WORKERS` | config `[webhooks] workers` (4) | Outbound webhook dispatch thread-pool size. |
| `MAVERICK_WEBHOOK_MAX_INFLIGHT` | config `[webhooks] max_inflight` (16×workers) | Cap on queued+running dispatches; excess is dropped + logged (bounds memory under a burst against a slow receiver). |
| `MAVERICK_GRPC_MAX_WORKERS` | config `[grpc] max_workers` (8) | gRPC goal-API server thread-pool size. |
| `MAVERICK_GRPC_MAX_CONCURRENT` | config `[grpc] max_concurrent_rpcs` (unbounded) | Max in-flight gRPC RPCs (RESOURCE_EXHAUSTED backpressure past the cap). |
| `MAVERICK_FEDERATION_MAX_WORKERS` | config `[federation] max_workers` (8) | Federation server thread-pool size. |
| `MAVERICK_FEDERATION_MAX_CONCURRENT` | config `[federation] max_concurrent_rpcs` (unbounded) | Max in-flight federation RPCs. |
| `MAVERICK_GH_APP_WEBHOOK_SECRET` | unset | Webhook secret for the GitHub App; requests are rejected if unset. |
| `MAVERICK_TRIGGER_LABELS` / `MAVERICK_GH_TRIGGER_LABELS` | built-in default | Comma-separated issue labels that trigger a GitHub-App run. |
| `MAVERICK_BOT_LINEAR_ID` | unset | Linear user id identifying "the bot" for issue webhooks. |
| `MAVERICK_BOT_JIRA_ACCOUNT_ID` | unset | Jira accountId (or bot email) identifying "the bot" for issue webhooks. |
| `MAVERICK_NTFY_TOPIC` | config `[notifications]` | ntfy topic for push notifications. |
| `MAVERICK_ENABLE_SESSION_PROVIDERS` | config `[session_providers] enabled` (off) | Opt in to session providers. |

## Connectors

Each enterprise connector reads its own credentials from named environment
variables — by convention `<SYSTEM>_BASE_URL` + `<SYSTEM>_TOKEN`, with a few
system-specific shapes (e.g. `SERVICENOW_INSTANCE_URL`, `SNOWFLAKE_ACCOUNT`,
`DATABASE_URL`). The full list of connectors and their exact variables lives in
[connectors.md](connectors.md); `maverick init` can collect them for you.

| Env var | Default | Description |
| --- | --- | --- |
| `<SYSTEM>_BASE_URL` / `<SYSTEM>_TOKEN` | unset | Per-connector endpoint + credential; see [connectors.md](connectors.md). Writes stay confirm-gated regardless. |
| `DATABASE_URL` | unset | SQLAlchemy URL for the `database` tool (Postgres / MySQL / SQL Server / Oracle / Redshift / ...). |
| `MAVERICK_ENABLE_CRED_TOOLS` | unset (off) | `1`/`true` registers connectors that can use ambient host credentials (AWS Lambda/DynamoDB, Google Drive, Airtable, Asana, ClickUp, Vercel). Off by default. |

## Agent-to-agent (A2A)

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_A2A_ENABLED` | config `[a2a] enabled` (off) | Enable the outward-facing A2A surface. |
| `MAVERICK_A2A_BASE_URL` | code default | Base URL advertised for A2A. |
| `MAVERICK_A2A_TOKEN` | unset | Bearer token required from A2A clients. |
| `MAVERICK_A2A_ALLOW_UNAUTHENTICATED` | unset (off) | `1` allows unauthenticated A2A requests (trusted networks only). |
| `MAVERICK_A2A_MAX_DOLLARS` | `5.0` | Dollar ceiling for an A2A-initiated task. |
| `MAVERICK_A2A_MAX_WALL_SECONDS` | `3600` | Wall-clock ceiling (seconds) for an A2A task. |
| `MAVERICK_A2A_MAX_DEPTH` | `3` | Max recursion depth for an A2A task. |
| `MAVERICK_A2A_MAX_TASKS` | `1000` (min 16) | Max concurrently-tracked A2A tasks. |

## Durable execution

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_DURABLE` | config `[durable] enabled` (off) | Enable durable execution (checkpoint/resume). |
| `MAVERICK_WORLD_SYNCHRONOUS` | config `[world_model] synchronous` (NORMAL) | World-DB PRAGMA synchronous level. `FULL`/`EXTRA` make every commit durable on OS crash/power loss (no acked-row loss) at a write-latency cost — for deployments treating the world DB as the billed Operating Record. |
