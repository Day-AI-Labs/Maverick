# Configuration

Maverick reads `~/.maverick/config.toml`. The installer wizard writes it; you can also edit by hand.

## Full schema

```toml
[deploy]
target = "desktop"     # desktop | docker | vps | phone

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
skills      = true
world_model = true
streaming   = true

[durable]
# Crash-resume: checkpoint a goal's loop state each step so `maverick resume`
# continues from where a crash left off instead of starting over. Off by
# default (a small write per step). keep_last bounds retained checkpoints.
enabled   = false
keep_last = 5

[channels.telegram]
enabled   = false
bot_token = "${TELEGRAM_BOT_TOKEN}"

[dashboard]
# Optional bearer token. Required for VPS deploys reachable from the open
# internet; harmless to leave unset on a desktop install (localhost-only).
token = "${MAVERICK_DASHBOARD_TOKEN}"

[persona]
# Appended to every agent's system prompt. Optional.
name      = "Maverick"
style     = "concise"   # concise | thorough | friendly | formal | playful
addendum  = ""           # free-form extra instruction

[mcp_servers.filesystem]
# External MCP servers Maverick consumes as tools. Each one is spawned as
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
Maverick. For untrusted skills, avoid mounting secret-bearing paths into
that runtime and prefer sandbox isolation that does not expose host
state.

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

Maverick can consume any MCP server (filesystem, GitHub, Postgres,
browser, etc.) as tools. Add entries under `[mcp_servers.<name>]`:

```toml
[mcp_servers.filesystem]
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

Behavior:

- The server is spawned as a stdio subprocess on swarm start and torn
  down on goal completion.
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
