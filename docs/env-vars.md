# Environment variables

Maverick's primary configuration is `~/.maverick/config.toml` (see
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
| `MAVERICK_CODING_MODE` | unset | When `1`/`true`/`yes`, switches the agent into coding mode (set by the `maverick code` CLI path); affects prompts, fs/shell tool defaults, and cache TTL. |
| `MAVERICK_LANGUAGE` | unset | Primary project language hint (e.g. `python`, `go`). Feeds sandbox/toolchain selection and coding mode. |
| `MAVERICK_MAX_STEPS` | `25` | Global cap on agent loop steps per goal. |
| `MAVERICK_MAX_SWARM_FANOUT` | `8` | Max child agents a single spawn call may branch into. |
| `MAVERICK_MAX_TOTAL_SPAWNS` | `64` | Process-wide cap on total spawned agents across a run. |
| `MAVERICK_MAX_CONCURRENT_GOALS` | `3` | Process-wide cap on goals running in parallel. |
| `MAVERICK_GOAL_ACQUIRE_TIMEOUT` | `300` | Seconds to wait for a goal-execution slot before giving up. |
| `MAVERICK_PARALLEL_TOOLS` | `1` (on) | Set `0` to run tool calls within a turn serially instead of in parallel. |
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
| `MAVERICK_AUTO_RECALL` | unset (off) | Auto-recall related prior goals/facts into a run. |
| `MAVERICK_AUTO_RECALL_K` | `3` | Number of prior items to recall when auto-recall is on. |
| `MAVERICK_AUTO_DISTILL` | unset (off) | Auto-distill skills from completed runs. |
| `MAVERICK_SELF_LEARNING` | config `[self_learning] enable` (off) | Enable the self-learning loop. |
| `MAVERICK_SKILL_DECAY` | `1` (on) | Set `0` to disable time-decay of skill usefulness stats. |
| `MAVERICK_ALLOW_SKILL_INSTALL` | unset (off) | Opt in to installing skills from free-text URLs. |
| `MAVERICK_VECTOR_STORE` | config `[memory] backend` | Semantic-recall backend: `chroma`, `qdrant`, or unset/`none` to disable. |
| `MAVERICK_CHROMA_PATH` | `~/.maverick/...` default | On-disk path for the Chroma vector store. |
| `MAVERICK_QDRANT_URL` | unset | Qdrant server URL (remote mode). |
| `MAVERICK_QDRANT_PATH` | default path | Qdrant local on-disk path (embedded mode). |
| `MAVERICK_QDRANT_API_KEY` | unset | API key for a remote Qdrant server. |
| `MAVERICK_WORLD_BACKEND` | config-driven | Set `postgres` to use the Postgres world-model backend. |
| `MAVERICK_PG_DSN` | unset | Postgres DSN for the Postgres world model (e.g. `postgres://user:pass@host:5432/maverick`). |
| `MAVERICK_ORPHAN_RECLAIM_SECONDS` | code default | Seconds before orphaned world-model goal locks are reclaimed. |
| `MAVERICK_BLACKBOARD_MAX_ENTRIES` | `5000` (min 100) | Max entries retained in the shared blackboard. |

## Compaction & context

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_COMPACT_HISTORY` | config `[context] compact` (off) | Enable history compaction. |
| `MAVERICK_HISTORY_WINDOW` | config `[context]` | Max number of recent turns kept verbatim. |
| `MAVERICK_HISTORY_TOKENS` | config `[context]` | Max history tokens before compaction triggers. |
| `MAVERICK_COMPACT_KEEP_RECENT` | `4` | Recent turns always kept uncompacted. |
| `MAVERICK_COMPACT_DIGEST_EVERY` | `10` | Digest older turns every N turns. |
| `MAVERICK_COMPACT_MAX_TOOL_BYTES` | `2048` | Max bytes of tool output retained before truncation during compaction. |

## Sandbox & tools

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_SUPPRESS_SANDBOX_WARNING` | unset | `1` silences the "running without an isolated sandbox" warning. |
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

## Observability

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_LOG_LEVEL` | `INFO` | Logging level. |
| `MAVERICK_LOG_FORMAT` | `text` | Log format: `text` or `json`. |
| `MAVERICK_LOG_TURNS` | unset | Set to log full LLM turns (verbose). |
| `MAVERICK_OTEL_EXPORTER` | unset (off) | Set to enable the OpenTelemetry trace exporter. |
| `MAVERICK_OTEL_ENDPOINT` | `http://localhost:4318/v1/traces` | OTLP collector endpoint. |
| `MAVERICK_PROMETHEUS_PORT` | unset (off) | Set a port to expose Prometheus metrics. |
| `MAVERICK_PROMETHEUS_ADDR` | `127.0.0.1` | Bind address for the Prometheus metrics server. |

## Plugins

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_PLUGINS_ALLOW` | config `[plugins] enabled` | Comma-separated plugin allowlist; `*` enables all. |
| `MAVERICK_PLUGINS_ENFORCE` | config `[plugins] enforce_permissions` (off) | Enforce plugin permission declarations. |

## Channels & integrations

| Env var | Default | Description |
| --- | --- | --- |
| `MAVERICK_WEBHOOK_SECRET` | unset | Optional HMAC signing key for inbound webhooks. |
| `MAVERICK_GH_APP_WEBHOOK_SECRET` | unset | Webhook secret for the GitHub App; requests are rejected if unset. |
| `MAVERICK_TRIGGER_LABELS` / `MAVERICK_GH_TRIGGER_LABELS` | built-in default | Comma-separated issue labels that trigger a GitHub-App run. |
| `MAVERICK_BOT_LINEAR_ID` | unset | Linear user id identifying "the bot" for issue webhooks. |
| `MAVERICK_BOT_JIRA_ACCOUNT_ID` | unset | Jira accountId (or bot email) identifying "the bot" for issue webhooks. |
| `MAVERICK_NTFY_TOPIC` | config `[notifications]` | ntfy topic for push notifications. |
| `MAVERICK_ENABLE_SESSION_PROVIDERS` | config `[session_providers] enabled` (off) | Opt in to session providers. |

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
