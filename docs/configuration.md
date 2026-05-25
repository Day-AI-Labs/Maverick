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
backend = "local"                   # local | docker | ssh
workdir = "~/maverick-workspace"
timeout = 60

[features]
skills      = true
world_model = true
streaming   = true

[channels.telegram]
enabled   = false
bot_token = "${TELEGRAM_BOT_TOKEN}"
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
