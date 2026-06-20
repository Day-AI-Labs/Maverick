# Configuration

Lightwork reads `~/.maverick/config.toml`. The installer wizard writes it; you can also edit by hand.

## Full schema

```toml
[deployment]
type = "desktop"       # desktop | docker | vps | phone

[providers.anthropic]
api_key = "${ANTHROPIC_API_KEY}"   # env var interpolation

[providers.openai]
api_key = "${OPENAI_API_KEY}"

[providers.openrouter]
api_key = "${OPENROUTER_API_KEY}"

[providers.ollama]
base_url = "http://localhost:11434"

[models]
# Per-role model picks. Format: "provider:model-id".
# Any role omitted falls back to maverick.llm.ROLE_MODELS defaults.
orchestrator    = "anthropic:claude-opus-4-7"
researcher      = "anthropic:claude-sonnet-4-6"
coder           = "anthropic:claude-sonnet-4-6"
writer          = "anthropic:claude-sonnet-4-6"
analyst         = "anthropic:claude-sonnet-4-6"
revisor         = "anthropic:claude-opus-4-7"
verifier        = "anthropic:claude-sonnet-4-6"
summarizer      = "anthropic:claude-haiku-4-5"
skill_distiller = "anthropic:claude-sonnet-4-6"

[budget]
max_dollars         = 5.0
max_wall_seconds    = 3600
max_tool_calls      = 500
max_input_tokens    = 1000000
max_output_tokens   = 200000

[safety]
profile         = "balanced"   # strict | balanced | permissive | off
block_threshold = "high"       # low | medium | high | critical
scan_input      = true
scan_tool_calls = true
scan_output     = true

[sandbox]
backend = "local"                   # local | docker | ssh | podman | devcontainer | firecracker | kubernetes
workdir = "~/maverick-workspace"
timeout = 60

[features]
# Toggle agent-facing behaviors that are otherwise always on. All default true.
skills      = true   # inject distilled/installed skills into agent prompts
                     #   (the MAVERICK_USE_SKILLS env var overrides this when set)
world_model = true   # inject persisted facts (cross-run memory) into runs;
                     #   false = run without prior stored facts. The goal/event/
                     #   checkpoint store (world.db) still works regardless.
streaming   = true   # stream live progress to the terminal during `maverick start`
                     #   (MAVERICK_NO_PROGRESS or non-TTY output still suppress it)
pack_editing = true  # allow editing/overriding agents (domain packs) from the
                     #   dashboard editor at /agents; false = the editor is
                     #   read-only and the mutating /api/v1/agents endpoints 403,
                     #   locking the roster (host-side override TOML still works).
role_editing = true  # allow editing the core roles (orchestrator, coder, ...)
                     #   from the dashboard editor at /roles -- a per-tenant
                     #   system-prompt addendum + model/effort override per role
                     #   (winning over [models]/[effort]); false = read-only and
                     #   /api/v1/roles mutations 403.

[durable]
# Crash-resume: checkpoint a goal's loop state each step so `maverick resume`
# continues from where a crash left off instead of starting over. Off by
# default (a small write per step). keep_last bounds retained checkpoints.
enabled   = false
keep_last = 5

[analytics]
# Consent-gated, OFF by default. When true, the MCP server tallies a coarse
# language bucket from each client's User-Agent (typescript/go/rust/c#/java/
# python) into a local counts file — no request content, no identifiers,
# nothing uploaded. Feeds the language-bindings decision gate.
# The wizard asks for consent in its Analytics step (`maverick init`).
mcp_client_language = false

[channels.telegram]
enabled   = false
bot_token = "${TELEGRAM_BOT_TOKEN}"

[dashboard]
# Optional bearer token. Required for VPS deploys reachable from the open
# internet; harmless to leave unset on a desktop install (localhost-only).
token = "${MAVERICK_DASHBOARD_TOKEN}"

[persona]
# Appended to every agent's system prompt. Optional.
name      = "Lightwork"
style     = "concise"   # concise | thorough | friendly | formal | playful
addendum  = ""           # free-form extra instruction

[mcp_servers.filesystem]
# External MCP servers Lightwork consumes as tools. Each one is spawned as
# a subprocess; their tools appear in the agent's catalog as
# `mcp_<name>__<tool>` and still pass through Shield.
command       = "npx"
args          = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
inherit_env   = false    # default; opt-in to pass the full process env

[mcp_servers.github]
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-github"]
# Pass-through env values must be listed explicitly; secrets live in
# ~/.maverick/.env so they aren't committed by accident.
env     = { GITHUB_PERSONAL_ACCESS_TOKEN = "${GITHUB_TOKEN}" }
```

`backend = "local"` runs tools in the same runtime environment as
Lightwork. For untrusted skills, avoid mounting secret-bearing paths into
that runtime and prefer sandbox isolation that does not expose host
state.

## Data residency & zero-data-retention (cloud providers)

When a role is routed to a cloud provider, two `[providers.<name>]` knobs
control where the request goes and what data-handling it asserts:

- **`base_url`** — pin the endpoint. Point it at a regional/EU endpoint or at a
  compliance gateway/proxy you operate, so prompts never leave the chosen
  region. Honored by `anthropic`, `openai`, and the self-hosted/OpenAI-compatible
  clients.
- **`default_headers`** — a `key = value` table of HTTP headers attached to every
  request to that provider, so a gateway can enforce **region pinning** or
  **zero-data-retention** at the edge. Threaded into the two primary cloud
  clients (`anthropic`, `openai`) today. Empty by default.

```toml
[providers.anthropic]
api_key = "${ANTHROPIC_API_KEY}"
base_url = "https://anthropic-eu.gateway.internal"   # region-pinned gateway
[providers.anthropic.default_headers]
anthropic-region = "eu"
x-no-retention = "1"
```

For a hard guarantee that *no* prompt leaves your boundary, prefer the
enterprise egress lock (`[enterprise] mode = true`), which pins every role to a
self-hosted provider — see `docs/security-hardening.md`. Outbound PII can also be
stripped before any cloud call with `[privacy] redact_egress = true`.

## Learning & workforce sections

```toml
[dreaming]                 # offline experience consolidation (default off)
enable = true
# min_cluster / insight_ttl_days / retire_skills / rehearse / prune_facts /
# snapshots / promote_shared / user_notes -- see FEATURES.md "Dreaming".
trusted_insight_pubkeys = []   # peers for `maverick insights-import`

[data_engine]              # Cognitive Data Engine flywheel (default off)
enable = true              # causal failure triage -> guardrails -> habits
# Reads the trajectory store; mutates nothing until enabled. `maverick flywheel`.

[operations_scientist]     # discover + prove a better process (default off)
enable = true              # propose a swap, validate it in the world-model first

[consequence]              # reality is the reward (default off)
enable = true              # a recorded outcome overrides the verifier proxy
# Feed outcomes via `maverick record-outcome` or POST /api/v1/outcomes.

[emergent_protocol]        # auditable coordination shorthand (default off)
enable = true              # learn short codes for repeated boilerplate; every
                           # code decodes EXACTLY back to English. `maverick codebook`.

[emergent_codec]           # token-aware codec, live measurement (default off)
enable = true              # measure (never apply) the codec's token savings on
                           # the real coordination stream; GET /api/v1/codec.

[reflexion]                # cross-run failure lessons (default off)
enable = true

[domains]                  # specialist-pack behavior (defaults shown)
discipline = true          # suite operating-discipline appended at spawn
memory = true              # department lessons injected at spawn

[fleet_memory]             # external agents read/write governed memory
enable = false             # explicit trust decision; roster-gated

[suites]                   # disable whole suites (all on by default)
# healthcare = false
```

## Per-role model choice

This is the *fully control every aspect* knob. Heavy roles benefit from a smart model; cheap roles can use a small one. Mix providers freely — the orchestrator can be a cloud Opus while the summarizer is a local Llama.

Roles available:

| Role | Used for |
|---|---|
| `orchestrator` | Plans, decomposes, verifies. Wants the smartest model. |
| `researcher`   | Searches, gathers info. Workhorse. |
| `coder`        | Writes and tests code. |
| `writer`       | Drafts long prose. |
| `analyst`      | Synthesizes findings. |
| `revisor`      | Second-pass review when verify fails. |
| `verifier`     | Independent final-answer check. |
| `summarizer`   | Cheap distillation. |
| `skill_distiller` | Turns trajectories into reusable skills. |

## Env vars vs config

- **Secrets** (API keys, bot tokens) live in `~/.maverick/.env` (chmod 600) and are referenced via `${VAR}` interpolation.
- **Everything else** lives in `config.toml` and is safe to commit (e.g. to a personal dotfiles repo).

The installer keeps these separated automatically.

> **Config is not schema-validated.** An unknown or **mis-typed** key is
> silently ignored and the runtime uses the built-in default — so a typo like
> `[budget] max_dollarss` runs **uncapped** rather than erroring. Until
> schema validation lands, after editing `config.toml` by hand run
> `maverick doctor` and confirm the security/cost-critical values
> (`[budget]`, `[enterprise]`, `[encryption]`, `[audit]`, `[safety]`) read back
> as you intend — e.g. via `maverick compliance` for the enterprise boundary.

## Overriding the config path

```bash
MAVERICK_CONFIG=/etc/maverick/config.toml maverick start "..."
```

Useful for VPS deployments where you want the config under `/etc/`.

## Dashboard authentication

For desktop installs the dashboard binds to `127.0.0.1:8765` and bearer
auth is optional. For VPS deploys (reachable from the open internet)
set `MAVERICK_DASHBOARD_TOKEN` — every request to `/api/v1/*` and every
HTML page is then gated. Only `/healthz`, `/openapi.json`, `/docs`, and
`/redoc` are exempt (so monitoring + API discovery still works).

Two ways to authenticate:

- **Header**: `Authorization: Bearer <token>` — for API clients.
- **Query string**: `?token=<token>` — so phone browsers can bookmark a
  page once and not retype the token.

Token comparison is constant-time (`hmac.compare_digest`).

## External MCP servers

Lightwork can consume any MCP server (filesystem, GitHub, Postgres,
browser, etc.) as tools. Add entries under `[mcp_servers.<name>]`:

```toml
# stdio: spawn a local subprocess
[mcp_servers.filesystem]
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

# remote: connect to a server over Streamable HTTP (set `url` instead of `command`)
[mcp_servers.remote]
url        = "https://mcp.example.com/mcp"
auth_token = "..."                      # optional; sent as `Authorization: Bearer …`
# headers  = { X-Org = "acme" }         # optional extra request headers
```

Behavior:

- A `command` server is spawned as a stdio subprocess on swarm start and
  torn down on goal completion. A `url` server is reached over HTTP
  (Streamable HTTP, spec 2025-11-25) — `tools/list` + `tools/call` over
  JSON or SSE, with session-id continuity; no subprocess. OAuth 2.1 isn't
  wired yet, but a static bearer (`auth_token`) is.
- Every tool it exposes is registered as `mcp_<name>__<tool>` in the
  agent's catalog and passes through `Shield.scan_tool_call` like any
  other tool.
- By default *no* environment is inherited from the parent process —
  only `PATH`, `HOME`, `USER`, `LANG`, `TZ`, `TMPDIR` (see
  `mcp_client.DEFAULT_ENV_ALLOWLIST`). Pass secrets explicitly via the
  `env = { ... }` table or set `inherit_env = true` to pass the full
  environment (only do this for fully-trusted servers).
- A background reader drains stderr to prevent pipe-buffer deadlocks
  when a server logs verbosely.

## Concurrency cap

The dashboard, REST API, and MCP server all share a process-wide
semaphore that bounds the number of swarms running in background
threads simultaneously. Override with:

```bash
MAVERICK_MAX_CONCURRENT_GOALS=4 maverick dashboard
```

Default is 2. Raise on a beefy machine; lower on a Raspberry Pi.

## Environment variables

Most settings live in this file, but many can be overridden (or only set) via
`MAVERICK_*` environment variables — see **[Environment variables](env-vars.md)**
for the full reference.
