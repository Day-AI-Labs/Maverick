# Maverick

[![CI](https://github.com/cdayAI/maverick/actions/workflows/ci.yml/badge.svg)](https://github.com/cdayAI/maverick/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)

**An open-source AI agent that runs on your machine, works for hours, and won't blow your budget.**

Hand Maverick a goal. Its orchestrator decomposes it, spawns specialist sub-agents — researcher, coder, writer, verifier — that work in parallel, checks their output, and returns a result. Every step runs under a hard spending cap and through a safety layer, on the models *you* choose.

- 🧠 **Long-horizon swarm.** Recursive multi-agent coordination built for hours-long tasks, not one-shot replies.
- 🛡️ **Safe by default.** Agent Shield screens every prompt, tool call, and output — the full SDK scores F1 0.988 on prompt-injection, and a built-in rule set ships out of the box (fail-open, never a hard dependency).
- 🎛️ **Your models, your budget.** 12 providers, routable per role (plan on Opus, summarise on Haiku). Set a dollar + wall-clock + tool-call cap the kernel refuses to exceed — no surprise bills.
- 💻 **Runs anywhere.** Desktop app, one-line script, Docker, VPS, or a phone companion across 11 channels. MIT-licensed, no telemetry, no paid tier.

```bash
pipx install 'maverick-agent[installer]'
maverick onboard                     # set up (if needed) + run your first goal, live
```

`maverick onboard` is the fastest path: it runs the four-question setup if
you haven't yet, then immediately runs a goal **in your terminal** so you
watch the swarm decompose, work, and verify in real time — instead of
being handed a command to copy-paste. Already set up? Drive it directly:

```bash
maverick init                        # four questions, safe defaults
maverick start "Research the top 3 CRMs for a 5-person startup and write a recommendation"
```

Here's what one run looks like — the swarm decomposing, working in
parallel, and verifying its own output before it answers:

```console
$ maverick start "Audit this repo's auth code for missing rate limiting, then write the fix and a test."

goal #1 created
orchestrator   planning → 3 independent sub-tasks, fanning out
  ├─ researcher  locating auth entry points… found api/login.py:42, api/token.py:18
  ├─ researcher  checking for existing rate limits… none on /login or /token/refresh
  └─ coder       drafting a fixed-window limiter in api/ratelimit.py
orchestrator   synthesizing → patch touches 3 files (+58 −4)
  verifier     running the new test… tests/test_ratelimit.py::test_blocks_6th_attempt PASSED
  verifier     accepted (confidence 0.91)

DONE.  Added api/ratelimit.py + wired it into login/refresh; new test passes.
[$0.14 · 71s · 12 tool calls]
```

Prefer no terminal? Grab the [**double-click desktop installer**](#install). New here? See [`docs/getting-started.md`](./docs/getting-started.md).

## Status

Alpha, but **installable today**: all six packages are on [PyPI](https://pypi.org/project/maverick-agent/), the one-line installers work on Windows/macOS/Linux, and a native double-click installer builds for all three. See [`docs/getting-started.md`](./docs/getting-started.md) for the full flow.

## What works today vs. planned

| Component | v0.1 (today) | Planned (v0.2+) |
|---|---|---|
| Install | **Native installer (`.exe` / `.dmg` / `.AppImage`)**, one-line bootstrap (`install.ps1` / `install.sh`), pipx, or from source | Code-signed bundles + auto-update |
| GUI | Native installer app + local web dashboard (`maverick dashboard`) + chat at `/chat` | Native Tauri shell for the agent itself + iOS/Android |
| Sandbox | Local subprocess, Docker, SSH, Podman, devcontainer, Firecracker, Kubernetes | Modal, Daytona |
| AI providers | Anthropic (full), OpenAI, OpenRouter, Ollama, Gemini, DeepSeek, Bedrock, Azure, xAI, Moonshot, TGI, vLLM (per-role routable) | Cohere |
| Channels | Telegram, Discord, Slack, Signal, Email, Matrix, Bluesky, Mastodon (ready); WhatsApp, SMS, iMessage (scaffolds) | Push notifications, voice |
| Safety | Shield wired at 3 chokepoints; agent-shield SDK if installed, else a built-in rule set | Agent-shield full ~115 patterns |
| Distribution | PyPI (6 packages), GHCR image, PyInstaller binaries, **native installers on Releases** | Code signing; Homebrew tap |
| Tests | 2000+ tests, ruff + pytest on Py 3.10/3.11/3.12 | Integration suite + benchmark RESULTS.md |

## Install

### Download the app — no terminal needed (easiest)

Grab the installer for your OS from the **[latest release ›](https://github.com/cdayAI/Maverick/releases/latest)**, double-click it, then press **Install Maverick**:

| OS | File on the release |
|---|---|
| **Windows** | `Maverick_*_x64-setup.exe` |
| **macOS** | `Maverick_*_aarch64.dmg` |
| **Linux** | `Maverick_*_amd64.AppImage` |

It's unsigned for now, so the first launch shows an "unknown developer" prompt — on Windows click **More info → Run anyway**; on macOS right-click the app → **Open**. The app installs Python and Maverick for you, then you're set.

### Terminal install with pipx

If you already have Python 3.10+, install the published package instead of running a remote bootstrap script:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

For source-based desktop bootstrapping, download `deploy/desktop/install.sh` or `deploy/desktop/install.ps1` from a commit or release you trust, verify it, and set `MAVERICK_REF` to a full 40-character commit SHA. The bootstrap scripts intentionally reject mutable branch/tag refs by default.

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
                       model (SQLite + FTS5 + schema v8), 12 LLM providers, 7
                       sandboxes, MCP client, skills, templates, persona,
                       background runner, budget tracking
  maverick-shield/     Agent Shield integration + built-in fallback rule set
  maverick-channels/   11 channel adapters: Telegram, Discord, Slack, Signal,
                       Email, Matrix, Bluesky, Mastodon (ready) + WhatsApp,
                       SMS, iMessage (scaffold)
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
| **Deploy** | Desktop / Docker / VPS / Phone (11 channels) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## License

MIT. See [`LICENSE`](./LICENSE).
