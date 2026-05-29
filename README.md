# Maverick

[![CI](https://github.com/cdayAI/maverick/actions/workflows/ci.yml/badge.svg)](https://github.com/cdayAI/maverick/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)

An open-source AI agent that runs locally on your machine.

Maverick combines two projects into one safest-by-default assistant:

- **Maverick Agent**: a recursive multi-agent swarm optimised for long-horizon work (hours, not minutes).
- **Agent Shield**: a safety layer with F1 0.988 prompt-injection detection (full SDK) plus a built-in 20-pattern fallback that ships with Maverick.

The wizard walks you through every choice. Deploy on desktop, in Docker, on a VPS, or as a phone companion (via any of 9 channels).

## Status

Early alpha. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the technical map and [`docs/getting-started.md`](./docs/getting-started.md) for the install flow.

## What works today vs. planned

| Component | v0.1 (today) | Planned (v0.2+) |
|---|---|---|
| Install | One-line bootstrap (`install.ps1` / `install.sh`), pipx, or from source | One-click Tauri DMG / MSIX / AppImage (signed) |
| GUI | Local web dashboard (`maverick dashboard`) + chat at `/chat` | Native Tauri shell + native iOS/Android |
| Sandbox | Local subprocess, Docker, SSH, Podman, devcontainer | Firecracker, Modal, Daytona |
| AI providers | Anthropic (full), OpenAI, OpenRouter, Ollama, Gemini, DeepSeek, Moonshot/Kimi, xAI/Grok, Azure OpenAI, Bedrock, TGI, vLLM (per-role routable) | Cohere (aspirational) |
| Channels | Telegram, Discord, Slack, Signal, Email, Matrix, Bluesky, Mastodon (ready); WhatsApp, SMS, iMessage (scaffolds) | Push notifications, voice |
| Safety | Shield wired at 3 chokepoints; agent-shield SDK if installed, else 20 builtin rules | Agent-shield full ~115 patterns |
| Distribution | GHCR image + PyInstaller binaries + PyPI publish (Trusted Publishing, OIDC) | Signed bundles; Homebrew tap |
| Tests | 1000+ tests, ruff + pytest on Py 3.10/3.11/3.12 | Integration suite + benchmark RESULTS.md |

## Install

### One-line install (recommended)

No Python required — the script installs everything it needs and launches the wizard.

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/desktop/install.ps1 | iex
```

**macOS / Linux**:

```bash
curl -fsSL https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/desktop/install.sh | bash
```

The script installs Python + git if they're missing, sets up an isolated environment, and runs `maverick init`. Override the source with `MAVERICK_REPO` / `MAVERICK_REF` (`$env:MAVERICK_REF` on Windows).

### With pipx (if you already have Python 3.10+)

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

The PyPI distribution name is `maverick-agent` (the `maverick` name is squatted on PyPI). The `[installer]` extra pulls the wizard into the same pipx environment so `maverick init` resolves.

If you already installed the kernel without the extra, inject the wizard:

```bash
pipx inject maverick-agent maverick-installer
```

### From source

```bash
git clone https://github.com/cdayAI/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
# Optional sister packages:
pip install -e ./packages/maverick-shield
pip install -e ./packages/maverick-channels
pip install -e ./packages/maverick-dashboard
pip install -e ./packages/maverick-mcp

maverick init                           # interactive wizard
maverick start "Plan a 2-week trip"      # one-shot goal
maverick chat                            # interactive REPL
maverick dashboard                       # web UI at http://127.0.0.1:8765
maverick serve                           # channel server (Telegram/Discord/...)
maverick mcp                             # MCP server (Claude Code / Cursor)
maverick doctor                          # health check
maverick version                         # installed package versions
```

## CLI reference

| Command | What |
|---|---|
| `maverick init` | Interactive setup wizard with preflight + API-key validation |
| `maverick doctor` | Green / yellow / red health check + remediation hints |
| `maverick version` | Installed package versions + runtime info |
| `maverick config show / path / edit` | Show / locate / edit `~/.maverick/config.toml` |
| `maverick start TITLE [--template NAME --param k=v]` | Run a goal once |
| `maverick chat` | Interactive REPL (each line = a goal) |
| `maverick serve` | Channel server (reads `[channels.*]` from config) |
| `maverick dashboard [--host --port --token]` | Local web UI + REST API |
| `maverick mcp` | MCP server on stdio for Claude Code / Cursor / etc. |
| `maverick logs / status / answer / resume` | Inspect + control running goals |
| `maverick fact / facts` | Get / set persistent facts |
| `maverick skills` | List installed + distilled skills |
| `maverick skill install / remove / info` | Manage the skill marketplace |
| `maverick template list / show` | Goal templates with `{{ var }}` substitution |
| `maverick budget` | Total + per-run cost history |

## Repository layout

```
packages/
  maverick-core/       Python agent kernel: recursive swarm, persistent world
                       model (SQLite + FTS5 + schema v3), 12 LLM providers, 3
                       sandboxes, MCP client, skills, templates, persona,
                       background runner, budget tracking
  maverick-shield/     Agent Shield integration + 20-pattern builtin fallback
  maverick-channels/   9 channel adapters: Telegram, Discord, Slack, Signal,
                       Email, Matrix (ready) + WhatsApp, SMS, iMessage (scaffold)
  maverick-dashboard/  Local FastAPI web UI + REST API at /api/v1 + OpenAPI
                       docs at /docs. Live progress streaming via short-poll.
  maverick-mcp/        MCP server (stdio JSON-RPC) -- exposes Maverick to Claude
                       Code, Cursor, Claude Desktop as a tool. The agent kernel
                       can also CONSUME external MCP servers as its own tools.
apps/
  installer-cli/       Interactive Python TUI wizard (`maverick init`)
  installer-desktop/   Tauri-based GUI installer scaffold (signing in v0.2)
deploy/
  docker/ vps/ desktop/  Dockerfile, install.sh, systemd unit, Caddyfile
docs/
  getting-started.md     Install + first run
  configuration.md       Full config schema reference
  deployment.md          Desktop / Docker / VPS / Phone-companion targets
  safety.md              Shield chokepoints and built-in rule set
  api.md                 REST API reference + curl examples
benchmarks/
  longhorizon/           Reproducible long-horizon evaluation tasks
  example-skills/        Curated SKILL.md files for the marketplace
  example-templates/     Reusable goal-template files
```

## Drive Maverick from another language

Maverick's kernel is Python, but its **wire surface** is the
[Model Context Protocol](https://modelcontextprotocol.io/). Any
MCP-speaking language can drive the swarm from outside Python:

- **TypeScript / JavaScript** → [docs/clients/typescript-quickstart.md](./docs/clients/typescript-quickstart.md)
- **Go** → [docs/clients/go-quickstart.md](./docs/clients/go-quickstart.md)
- **Rust** → [docs/clients/rust-quickstart.md](./docs/clients/rust-quickstart.md)

Each is a 20-line program: spawn `maverick mcp`, list tools, call one.
Why this and not a separate `@maverick/core` port?
[Language Bindings — Council Decision](./docs/ROADMAP.md#language-bindings--council-decision-may-2026).

## Vision

| Axis | Maverick |
|---|---|
| **Target user** | General consumer -- no AI expertise required |
| **Wedge** | Long-horizon depth + true multi-agent coordination |
| **Safety** | First-class. Every input, tool call, and output passes through Agent Shield. |
| **Control** | You pick the models. Per-role. Multi-provider. |
| **Deploy** | Desktop / Docker / VPS / Phone (9 channels) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## License

MIT. See [`LICENSE`](./LICENSE).
