<p align="center">
  <img src="Daybreak%20Labs%20Logo.jpg" alt="Daybreak Labs" width="360">
</p>

# Lightwork

> Lightwork — by **Daybreak Labs**.

[![CI](https://github.com/Day-AI-Labs/maverick/actions/workflows/ci.yml/badge.svg)](https://github.com/Day-AI-Labs/maverick/actions/workflows/ci.yml)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)

**The governed, auditable AI agent runtime for regulated enterprises — a long-horizon multi-agent swarm that runs on your data, in your environment, under a hard budget.**

Hand Lightwork a goal. Its orchestrator decomposes it, spawns specialist sub-agents — researcher, coder, writer, verifier — that work in parallel, checks their output, and returns a result. Every step runs under a hard spending cap and through a safety layer, on the models *you* choose.

- 🛡️ **Governed & contained by default.** RBAC, capability tokens, per-tool ACLs, consent gates, and a kill switch bound every agent action — and in Enterprise mode an **egress lock** blocks the agent's outbound network paths (LLM calls and the built-in HTTP tools/connectors), so a prompt-injected agent can't exfiltrate through them (pair it with a network-level egress firewall to also cover raw-shell egress). Agent Shield also screens every prompt, tool call, and output; detector strength depends on the configured backend (see [`docs/safety.md`](./docs/safety.md)).
- 🧾 **Tamper-evident & audit-ready.** A signed, hash-chained, append-only audit log (`maverick audit verify`) with SIEM export, encryption-at-rest, DSAR, and SOC2-aligned evidence — built to survive a security review.
- 🔒 **Self-host & air-gap.** Runs entirely in your environment — laptop, VPC, Kubernetes, or a disconnected network with no required data egress. No hyperscaler dependency, no telemetry.
- 📈 **A workforce that provably improves.** Closed-loop learning — offline experience consolidation ("dreaming"), per-department memory, skill distillation with safe forgetting — every learned artifact audited, snapshotted, and rollback-able. `maverick hindsight` detects if learning ever regressed; `maverick proof` reports deliverables, cost avoided, ROI, and the improvement curve.
- 🔬 **Causal learning, not vibes (opt-in).** A **Cognitive Data Engine** (`maverick flywheel`) triages production failures by their *causal* impact on real outcomes — stratified ATE with confidence intervals, placebo refutation, and a trustworthiness gate — then mines self-retiring **guardrails**, consolidates **habits**, and lets an **Operations Scientist** prove a better process in a world-model before spending a real experiment. The **Consequence Engine** (`maverick record-outcome`) grounds all of it in what *actually* happened — an invoice paid, a ticket reopened — so the workforce learns from reality, not a model grading its own work. All OFF by default.
- 🏢 **2,020 prebuilt specialists across 53 business suites.** Customer support, finance, legal, HR, ops, GTM, marketing, procurement, data, security ops, tax preparation for CPA firms, and 30+ industry verticals (healthcare, insurance, banking, gov contracting, maritime, mining, semiconductors, chemicals, water, renewables, …) — every pack a real agent with a least-privilege tool envelope and risk ceiling, an editable workflow playbook, a declared deliverable, a right-sized reasoning tier, and hard prohibited-use refusals (EU AI Act Art-5 for HR, safety-critical for the physical suites). Prove it: `maverick domains-lint` (0 errors, 0 warnings), `domains-audit` (0 drafting agents can reach a state-mutator), `domains-eval` (behavioral golden cases). The orchestrator finds the right one via query-based routing. Backed by a library of **514 reusable, validator-compliant skills** (`SKILL.md`) that any pack can activate by trigger, and an **agent factory** that equips every freshly-approved pack with the skills and tools its workflow needs *at birth* — never widening the pack's already-clamped envelope.
- 🏭 **An agent factory that builds agents — and itself.** Describe a job, or just *demonstrate* it: `maverick learn-demo` watches a person do their work (observed actions + narration, secret-redacted at the door) and synthesizes the agent that does it through the same intake pipeline — identical envelope clamp and persona shield-scan, with a human review gate always appended. `maverick factory-learn` closes the loop onto generation quality, mining provisioning/approval gaps into proposer guidance that improves future pack generation. OFF by default; never widens any pack's envelope.
- 📚 **Primary-source data grounding.** Every analyst pack is auto-granted (by suite) a set of 37 read-only, GET-only public-data connectors — SEC EDGAR, FRED, Treasury, World Bank, FDIC, Census, BLS, EIA, openFDA, NPPES, ClinicalTrials, USAspending, SAM.gov, CourtListener, Federal Register, GLEIF, OpenCorporates, NWS/NOAA weather, EPA, Climatiq, and more — so the workforce grounds its work in authoritative primary sources, not model recall. On by default (low-risk, deferred), with a kill switch (`[workforce] data_grounding = false` / `MAVERICK_WORKFORCE_DATA_GROUNDING=off`) and an installer wizard step. These sit alongside 214 write-capable long-tail enterprise REST/GraphQL connectors and dedicated modules (Salesforce, HubSpot, Stripe, ServiceNow, Snowflake, …).
- 🧪 **Governance proven across the whole roster.** A roster-wide invariant test suite verifies six governance invariants across all 2,020 packs — tool-reachability (no drafting agent can reach a state-mutating tool), the autonomy dial (onboarding and high-risk actions are never autonomous), capability attenuation (a spawned child can never exceed its parent grant), compartment isolation (a quarantine seal never bleeds across suites), unstrippable hard refusals, and never-silently-exceeded budget caps — each fault-injected with a non-vacuous control across the full roster, plus hostile-argument fuzzing of every connector and tool.
- 🧠 **Long-horizon multi-agent depth.** A recursive orchestrator spawns specialist sub-agents that work for hours under hard dollar / wall-clock / tool-call caps — frontier-agent depth, on the models *you* choose, with the governance and learning layers no coding-agent runtime ships.

> **Proprietary software — not open source.** Lightwork is enterprise software; use, redistribution, and derivative works require a license. [Contact us](https://github.com/Day-AI-Labs/Maverick) for evaluation or commercial access. See [`LICENSE`](./LICENSE) and [`TRADEMARK.md`](./TRADEMARK.md).

```bash
pipx install 'maverick-agent[installer]'
maverick init                        # four questions, safe defaults
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

Prefer no terminal? Grab the [**double-click desktop installer**](#install). New here? See [`docs/getting-started.md`](./docs/getting-started.md).

## Status

Alpha, but **installable today**: all eight packages are on [PyPI](https://pypi.org/project/maverick-agent/), the one-line installers work on Windows/macOS/Linux, and a native double-click installer builds for all three. See [`docs/getting-started.md`](./docs/getting-started.md) for the full flow.

## What works today vs. planned

| Component | v0.1 (today) | Planned (v0.2+) |
|---|---|---|
| Install | **Native installer (`.exe` / `.dmg` / `.AppImage`)**, one-line bootstrap (`install.ps1` / `install.sh`), pipx, or from source | Code-signed bundles + auto-update |
| GUI | Native installer app + local web dashboard (`maverick dashboard`) + chat at `/chat` | Native Tauri shell for the agent itself + iOS/Android |
| Sandbox | Local subprocess, Docker, gVisor, Podman, devcontainer, Firecracker, Kubernetes, SSH, Modal | Daytona |
| AI providers | Anthropic (full), OpenAI, OpenRouter, Ollama, Gemini, DeepSeek, Bedrock, Azure, xAI, Moonshot, TGI, vLLM (per-role routable) | Cohere |
| Channels | All 17 wired — Telegram, Discord, Slack, Signal, Email, Matrix, Bluesky, Mastodon, Voice, IRC, Threads, RCS, Glasses; WhatsApp (Cloud API + Twilio)/SMS (need Twilio), iMessage (macOS-only) | Push notifications |
| Safety | Shield wired at 3 chokepoints; agent-shield SDK if installed, else a built-in rule set | Agent-shield full ~115 patterns |
| Distribution | PyPI (8 packages), GHCR image, PyInstaller binaries, **native installers on Releases** | Code signing; Homebrew tap |
| Tests | 2000+ tests, ruff + pytest on Py 3.10/3.11/3.12 | Integration suite + benchmark RESULTS.md |

**Full list of shipped features → [`docs/FEATURES.md`](./docs/FEATURES.md).** The forward backlog (what isn't built yet) lives in [`docs/ROADMAP.md`](./docs/ROADMAP.md).

## Install

### Download the app — no terminal needed (easiest)

Grab the installer for your OS from the **[latest release ›](https://github.com/Day-AI-Labs/Maverick/releases/latest)**, double-click it, then press **Install Lightwork**:

| OS | File on the release |
|---|---|
| **Windows** | `Lightwork_*_x64-setup.exe` |
| **macOS** | `Lightwork_*_aarch64.dmg` |
| **Linux** | `Lightwork_*_amd64.AppImage` |

It's unsigned for now, so the first launch shows an "unknown developer" prompt — on Windows click **More info → Run anyway**; on macOS right-click the app → **Open**. The app installs Python and Lightwork for you, then you're set.

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
git clone https://github.com/Day-AI-Labs/maverick
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
| `maverick schedule goal / add / list / rm` | Schedule recurring autonomous goals via cron |
| `maverick worker` | Drain the scheduled-job queue (runs the recurring tasks) |
| `maverick fact / facts` | Get / set persistent facts |
| `maverick skills` | List installed + distilled skills |
| `maverick skill install / remove / info` | Manage the skill marketplace |
| `maverick template list / show` | Goal templates with `{{ var }}` substitution |
| `maverick learn-demo FILE [--name --no-llm --source --industry --yes]` | Build an agent from a recorded demonstration (parse → induce → approve → save → provision) |
| `maverick factory-learn [--min-support N] [--dry-run]` | Self-improving factory: mine provisioning/approval gaps into proposer guidance (opt-in `[self_improvement]`) |
| `maverick budget` | Total + per-run cost history |
| `maverick flywheel` | Cognitive Data Engine: causal failure triage → guardrails → habits (opt-in `[data_engine]`) |
| `maverick record-outcome GOAL EP VALUE` | Feed a real downstream outcome to a past episode (Consequence Engine) |
| `maverick codebook / codec-learn` | Learn the swarm's auditable coordination shorthand from real messages |
| `maverick codec-probe` | Measure the codec's real token (not just byte) savings with the target tokenizer |

## Repository layout

```
packages/
  maverick-core/       Python agent kernel: recursive swarm, persistent world
                       model (SQLite + FTS5, or Postgres; schema v23), 12 LLM providers, 9
                       sandboxes, MCP client, skills, templates, persona,
                       background runner, budget tracking
  maverick-shield/     Agent Shield integration + built-in fallback rule set
  maverick-channels/   17 channel adapters: Telegram, Discord, Slack, Signal,
                       Email, Matrix, Bluesky, Mastodon, Voice, WhatsApp, WhatsApp
                       Cloud, SMS, iMessage, IRC, Threads, RCS, Glasses
                       (WhatsApp/SMS need Twilio; iMessage is macOS-only)
  maverick-dashboard/  Local FastAPI web UI + REST API at /api/v1 + OpenAPI
                       docs at /docs. Live progress streaming via short-poll.
  maverick-mcp/        MCP server (stdio JSON-RPC) -- exposes Lightwork to Claude
                       Code, Cursor, Claude Desktop as a tool. The agent kernel
                       can also CONSUME external MCP servers as its own tools.
apps/
  installer-cli/       Interactive Python TUI wizard (`maverick init`)
  installer-desktop/   Tauri-based GUI installer (built; unsigned -- code signing in v0.2)
deploy/
  docker/ vps/ desktop/  Dockerfile, install.sh, systemd unit, Caddyfile
docs/
  getting-started.md     Install + first run
  architecture.md        The governed agent runtime (OS-style primitives)
  configuration.md       Full config schema reference
  deployment.md          Desktop / Docker / VPS / Phone-companion targets
  safety.md              Shield chokepoints and built-in rule set
  security-hardening.md  Enterprise opt-in controls + compliance commands
  api.md                 REST API reference + curl examples
benchmarks/
  longhorizon/           Reproducible long-horizon evaluation tasks
  example-skills/        Curated SKILL.md files for the marketplace
  example-templates/     Reusable goal-template files
```

## Drive Lightwork from another language

Lightwork's kernel is Python, but its **wire surface** is the
[Model Context Protocol](https://modelcontextprotocol.io/). Any
MCP-speaking language can drive the swarm from outside Python:

- **TypeScript / JavaScript** → [docs/clients/typescript-quickstart.md](./docs/clients/typescript-quickstart.md)
- **Go** → [docs/clients/go-quickstart.md](./docs/clients/go-quickstart.md)
- **Rust** → [docs/clients/rust-quickstart.md](./docs/clients/rust-quickstart.md)
- **C# / .NET** → [docs/clients/csharp-quickstart.md](./docs/clients/csharp-quickstart.md)
- **Java / JVM** → [docs/clients/java-quickstart.md](./docs/clients/java-quickstart.md)

Each is a 20-line program: spawn `maverick mcp`, list tools, call one.
Why this and not a separate `@maverick/core` port?
[Language Bindings — Council Decision](./docs/ROADMAP.md#language-bindings--council-decision-may-2026).

## Run Lightwork in CI

Run the swarm inside any repo's GitHub Actions — on a PR, a schedule, or on
demand — under a hard spend cap:

```yaml
- uses: Day-AI-Labs/maverick/deploy/github-action@v0.1.6
  with:
    goal: "Summarize this PR and flag anything risky."
    max-dollars: "0.50"
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

See [docs/github-action.md](./docs/github-action.md).

## Vision

| Axis | Lightwork |
|---|---|
| **Target user** | Enterprise & technical teams -- self-hosted, governed, auditable |
| **Wedge** | Long-horizon depth + true multi-agent coordination |
| **Safety** | First-class. Every input, tool call, and output passes through Agent Shield. |
| **Control** | You pick the models. Per-role. Multi-provider. |
| **Deploy** | Desktop / Docker / VPS / Phone (17 channels) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## License

Proprietary — commercially licensed. Use, redistribution, and derivative works
require a license. See [`LICENSE`](./LICENSE) and [`TRADEMARK.md`](./TRADEMARK.md);
[contact us](https://github.com/Day-AI-Labs/Lightwork) for access.
