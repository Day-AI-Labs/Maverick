# Changelog

All notable changes to Maverick. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] -- 2026-05-25

### Fixed
- PyInstaller release binaries on all three platforms (Linux x86_64,
  macOS arm64, Windows x86_64) failed at `import sqlite3` -- the
  v0.1.0 build flags missed bundling stdlib `sqlite3`. Switched to a
  `.spec` file with an explicit `hiddenimports` list and pinned
  PyInstaller to `>=6.0,<7.0`. A diagnostic step now verifies
  `sqlite3` is importable on the build host before the bundle runs.
- `maverick version` reported `maverick: not installed` after the
  PyPI rename to `maverick-agent`. The reporter now reads
  `maverick-agent` as the canonical distribution name.

### Added
- Multi-turn conversation state per channel user (schema v3 -> v4).
- File + image input on goals (schema v4 -> v5) with mime allowlist,
  per-file/per-goal quotas, vision-block delivery for images.
- Plugin SDK via `importlib.metadata` entry_points for tools, channels,
  skills, personas. Fault-isolated.
- `benchmarks/harness.py` + RESULTS.md.
- `ask_user` is now scoped to the running goal.
- Council medium-priority polish: docs, schema migration tests,
  orchestrator E2E test, channel adapter smoke tests, /chat/goal
  user-friendly labels, multi-line REPL.

## [Unreleased] -- v0.1.0-alpha

First public release. Maverick combines [Maverick Agent](https://github.com/texasreaper62/research/tree/main/maverick) (recursive multi-agent swarm)
and [Agent Shield](https://github.com/texasreaper62/agent-shield) (safety detection)
into a single safest-by-default agent that anyone can install in one
command.

### Added

**Agent kernel** (`maverick-core`)
- Recursive multi-agent swarm: `spawn_subagent` (blocking) and `spawn_swarm` (parallel via `asyncio.gather`)
- Persistent SQLite + FTS5 world model: goals, episodes, facts, questions, messages
- Hard budget caps: tokens, $, wall-clock, tool calls
- Auto-distilled skills: successful trajectories → reusable SKILL.md
- WorldModel schema migrations with version tracking (currently at v2)

**Multi-provider LLM dispatch**
- Anthropic (full impl: prompt caching, extended thinking, streaming)
- OpenAI (Chat Completions + tool-use, with Anthropic format translation)
- OpenRouter (200+ models via single API)
- Ollama (local models, OpenAI-compatible at `localhost:11434`)
- Gemini (Google, via OpenAI-compatible endpoint)
- Per-role model assignment via `[models]` section of config

**Safety** (`maverick-shield`)
- Agent Shield SDK integration when installed (full ~115 patterns)
- Built-in fallback rules (~20 high-impact patterns) when SDK absent
- Three chokepoints: input scan, tool-call scan, output scan
- Profiles: strict / balanced / permissive / off
- Shield is actually wired into the agent loop (not just documented)

**Channels** (`maverick-channels`)
- Telegram (Bot API), Discord (Gateway), Slack (Socket Mode)
- Signal (via signal-cli subprocess)
- Email (IMAP poll + SMTP send, stdlib only)
- Matrix (federated, via matrix-nio)
- WhatsApp + SMS (Twilio, with signature verification)
- iMessage (macOS, parameterized AppleScript, no shell injection)

**Sandboxes**
- Local subprocess
- Docker (throwaway containers, `--network=none` by default)
- SSH (remote host via system ssh binary)

**Installer**
- `maverick init`: interactive CLI wizard with preflight + API-key validation
- Tauri-based native GUI installer scaffold (`apps/installer-desktop/`)
- Per-role model picker, channel picker, safety profile picker
- Channels prompted for required env vars only

**Web dashboard** (`maverick-dashboard`)
- Local FastAPI app at `127.0.0.1:8765` showing goals / skills / facts / spend
- Dark monospace theme, no JS framework, htmx for the live bits

**MCP server** (`maverick-mcp`)
- Maverick exposed as a Model Context Protocol server over stdio
- Drives the swarm from Claude Code / Cursor / Claude Desktop / any MCP client
- 8 tools: start / status / resume / answer / skill_install / skills_list / fact_set / facts_get

**CLI commands**
- `maverick init` / `start` / `serve` / `doctor` / `config` / `dashboard` / `mcp`
- `maverick logs` / `status` / `answer` / `resume` / `fact` / `facts`
- `maverick skill install/remove/info` / `skills`

**Distribution**
- Release workflow: GHCR Docker image push on tag
- PyInstaller single-file binaries for Linux x86_64 / macOS arm64 / Windows x86_64
- PyPI publish for all 6 packages (gated on `PYPI_API_TOKEN` secret)
- VPS bootstrap: `install.sh` + systemd unit + Caddyfile

**Tests**
- Smoke tests across all packages (imports, config, budget, blackboard, etc.)
- OpenAI format translator: 17 unit tests covering round-trip fidelity
- Skills: install / remove / parse / safe_name / relevance scoring
- Built-in shield rules: each rule category + profile interactions
- Agent loop tests using FakeLLM fixture: FINAL parsing, ask_user blocking,
  Shield blocking, budget exhaustion, max_steps cap
- MCP server: tool catalog + protocol shapes
- Dashboard: every page renders with empty data

**Documentation**
- `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`
- `docs/getting-started.md`, `docs/configuration.md`, `docs/deployment.md`, `docs/safety.md`
- 5 example skills (`benchmarks/example-skills/`)
- 3 long-horizon benchmark tasks with budget/criteria

### Known limitations (v0.1.0-alpha)

- No PyPI publication yet (CI workflow is ready; just needs `PYPI_API_TOKEN`)
- No notarized DMG / signed MSIX (Tauri scaffold exists; signing comes next)
- Skill retrieval is lexical (embeddings-based retrieval is v0.2)
- WhatsApp and SMS scaffolds require a public HTTPS endpoint to receive Twilio webhooks
- Agent Shield SDK not yet on PyPI (built-in fallback rules cover ~20 high-impact patterns until then)
