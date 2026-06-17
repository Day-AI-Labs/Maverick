# Changelog

All notable changes to Maverick. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Closed-loop self-improvement: offline experience consolidation
  (`maverick dream` — replay, consolidate, rehearse, forget, prune),
  department-scoped reflexion/memory, skill distillation with probation and
  retirement, cross-department insight promotion, human-override and
  user-correction ingestion, and verifier-scored rehearsal gated by the
  calibration interlock.
- Learning governance: per-cycle `learning_update` audit rows, `--dry-run`,
  pre-cycle snapshots with `--rollback`, tenant-isolated learned stores, and
  the hindsight engine (`maverick hindsight`) for learning-regression
  detection.
- `maverick proof` — workforce value report (deliverables, cost avoided,
  ROI, improvement curve), with per-vendor `--fleet` breakdown.
- Cognitive Data Engine (`maverick flywheel`, opt-in `[data_engine]`) —
  causal failure triage (stratified ATE + confidence intervals + placebo
  refutation + a trustworthiness gate) → self-retiring guardrails →
  consolidated habits, composed in one pass; observable at
  `GET /api/v1/flywheel`.
- Operations Scientist (opt-in `[operations_scientist]`) — propose a
  harmful→beneficial action swap and validate it in a g-computation
  world-model before spending a real experiment.
- Consequence Engine (`maverick record-outcome`, `POST /api/v1/outcomes`,
  opt-in `[consequence]`) — a real downstream outcome overrides the
  verifier's self-graded proxy so learning is grounded in reality.
- Emergent Substrate (`maverick codebook` / `codec-learn` / `codec-probe`,
  opt-in `[emergent_protocol]` / `[emergent_codec]`) — an auditable
  coordination codec that learns short codes for repeated boilerplate;
  every code decodes EXACTLY back to English (`decode(encode(x)) == x`,
  fuzz-tested). `codec-probe` measures real token (not just byte) savings;
  the token-aware codec measures ~28% in benchmark. Measure-only on the live
  blackboard (`GET /api/v1/codec`); agents reading codes is a separate step.
- Fleet memory (`maverick fleet-memory`, MCP tools `maverick_fleet_ingest`
  / `maverick_fleet_recall`) — governed, audited memory plane for external
  agents.
- The Operating Record (`maverick record`) — decisions + approvals as a
  queryable system of record with Ed25519-signed, offline-verifiable
  capsule export.
- Federated insight exchange (`maverick insights-export` / `-import`,
  fail-closed signing) and fleet donation aggregation
  (`maverick dream --donations-dir`).
- Specialist portfolio expanded from 338 to 1,000 lint-clean agents across
  25 suites, including customer support, 10 industry verticals, and
  jurisdiction packs; suite operating discipline and department memory
  applied to every pack at spawn; `maverick domains-lint` quality gate.
- Goal rows persist their department (world-model schema v14).
- Tax preparation pipeline (`maverick tax prepare`, `tax_prep.py`): uploaded
  documents → deterministic classification/extraction → workpaper →
  first-pass TY2025 draft 1040 **and resident-state return** (auto-detected
  from W-2 box 15; no-tax/flat states computed, graduated states handed to
  the preparer) → preparer review package, every line cited to its source
  document and out-of-scope items flagged as open items; plus the 19-pack
  `tax_` specialist suite (portfolio now 1,118 packs across 26 suites) and
  CCH Axcess / Thomson Reuters GoSystem connectors (confirm-gated write
  seats + GET-only low-risk read seats for the status packs).
- Signed tax-constants channel (`maverick tax update`, `[tax]` config):
  new tax law arrives as an Ed25519-signed content bundle — fail-closed
  verification, sanity validation, downgrade protection, rollback, audit —
  auto-applied by `maverick tax prepare` when `[tax] auto_update` +
  `update_url` are configured; the `tax_law_watch` pack monitors IRS/state
  guidance (web access, no client-data access) and alerts the firm.


### Fixed
- World model search now backfills the `messages_fts` full-text index on
  upgrade (schema v10). The FTS triggers only index future writes, so a
  database whose messages predated the index carried unindexed history that
  message search silently missed; v10 rebuilds it once.

## [0.1.6] -- 2026-05-31

Post-0.1.4 hardening, plus the cross-language MCP client surface (the
council's "drive Maverick from any language over MCP" decision) and the
polyglot sandbox / coding-mode work.

### Added
- **Cross-language MCP clients.** Runnable example clients and quickstarts for
  **TypeScript / JavaScript, Go, Rust, C# / .NET, and Java / JVM** -- each one
  exercised in CI against a live `maverick mcp` (initialize -> tools/list -> a
  no-LLM tool call). Maverick stays a single Python kernel; any MCP-speaking
  language drives it over stdio JSON-RPC. See `docs/clients/*-quickstart.md`.
- **Per-language sandbox toolchains.** Container backends now pick their image
  from `[sandbox] language` (rust -> rust:1, go -> golang:1, JS/TS -> node:22,
  Java/Kotlin -> eclipse-temurin:21, ruby -> ruby:3; Python is the default),
  and the installer wizard asks which language you code in -- so `cargo test` /
  `go test` / the JS runner actually run instead of failing on python:3.12-slim.
  coding-mode gained Rust/Go/TypeScript failure-pattern hints, and
  `maverick doctor` reports a missing language toolchain.
- **Agent-to-Agent (A2A) task endpoint** with push-notification config, an
  installer wizard step, and docs.

### Security
- **SMS and WhatsApp now enforce a per-sender allowlist** (default-deny),
  closing a critical auth bypass: in 0.1.4 these two Twilio channels checked
  only the `X-Twilio-Signature` (which proves Twilio relayed the message, not
  that the *sender* is authorized), so any PSTN subscriber who texted the
  number could drive the swarm with host shell access. They now match the
  other channels: a valid signature plus an explicit allowlist member.
- **GDPR erase now re-anchors the signed audit chain.** When `[audit] sign`
  is enabled, scrubbing/tombstoning a user's rows used to break the Ed25519
  hash-chain at the erasure point -- a break `maverick audit verify` could
  not tell apart from tampering, so a routine privacy operation destroyed
  the trust anchor. erase re-chains and re-signs the affected files (the
  signed `erase` marker records the authorized cut) so verification passes
  again. Also de-duplicated a double `scrub_user` call in the erase path.
- Bumped dependency floors past known CVEs on the network-facing surfaces:
  `pillow>=12.2.0` (5 CVEs incl. PYSEC-2026-165), `python-multipart>=0.0.27`
  (CVE-2026-42561), `requests>=2.33.0` (CVE-2026-25645), `starlette>=1.0.1`
  (PYSEC-2026-161), `urllib3>=2.7.0` (PYSEC-2026-142/141). starlette is
  declared directly where the dashboard imports it; requests/urllib3 are
  floored in the Twilio (`sms`/`whatsapp`) extras that pull them in.
- The CI `pip-audit` job is now blocking, so a new advisory fails the build
  and prompts a floor bump instead of shipping silently.

### Changed (breaking)
- The `sms` and `whatsapp` channels **require** an allowlist to start. Set
  `SMS_ALLOWED_USER_IDS` / `WHATSAPP_ALLOWED_USER_IDS` (comma-separated) or
  the `allowed_user_ids` config key, or the channel raises on startup. List
  senders as Twilio delivers them: `+14155551234` for SMS,
  `whatsapp:+14155551234` for WhatsApp. (Slack/Signal/Matrix already required
  this as of 0.1.4 -- SMS/WhatsApp were missed.)

## [0.1.4] -- 2026-05-30

The launch-hardening pass that landed just after the 0.1.3 tag was cut.
0.1.3 shipped without these; 0.1.4 is the first release to include them.

### Added
- Per-sender channel allowlists for Slack/Signal/Matrix/Voice (default-deny);
  the installer wizard now collects `*_ALLOWED_USER_IDS` / allowed callers.
- `compute`/sympy math tool wired up (was dead); restored two
  silently-shadowed CLI commands (GDPR `export`, `logs`).

### Fixed
- **Killswitch is now enforced.** `maverick halt`, the dashboard Halt button,
  and the HALT file are checked at the agent turn boundary and the tool
  boundary -- in 0.1.3 they were read by nothing (a no-op).
- **MCP HTTP transport** no longer crashes with `asyncio.run() ... running
  event loop`; client-supplied budgets are clamped and an arbitrary host-file
  read (`trusted_local`) was closed.
- **VPS installer** references the correct pipx package name (`maverick-agent`)
  and its run-as-user model is coherent.
- GDPR `erase` no longer fails on the foreign-key cascade; audit `scrub_user`
  is wired.
- Cost accounting for router-selected models; best-of-N now rolls all budget
  counters (cache tokens + tool calls) into the parent and enforces its cap.
- CircuitBreaker HALF_OPEN admits exactly one probe (was a retry storm); MCP
  negotiates protocol version by supported set, not a lexicographic downgrade.
- `dep_graph` emits forward-slash paths on every platform; arXiv API uses
  https; Windows POSIX file-mode test assertions are guarded.

## [0.1.3] -- 2026-05-29

### Added
- One-line desktop installers: `deploy/desktop/install.ps1` (Windows,
  `irm ... | iex`) and `deploy/desktop/install.sh` (macOS/Linux,
  `curl ... | bash`). They install Python 3 + git if missing, set up an
  isolated pipx environment, and launch the wizard -- no prerequisites.

### Fixed
- Windows installer could not find a just-installed Python: winget runs
  the python.org installer without adding it to PATH. Detection now
  falls back to the PEP 514 registry and well-known install dirs, and
  probes with `--version` instead of a quoted `python -c "..."` snippet
  (Windows PowerShell 5.1 mangles embedded double quotes, which made
  every probe fail even when the interpreter was fine).
- Release binaries crashed with `No module named 'maverick'` -- the
  build installed packages editable, which PyInstaller can't collect.
  Now installed non-editable, with `collect_submodules`/`copy_metadata`
  in the spec.

### Changed
- The MCP server is published to PyPI as `maverick-mcp-server` (the
  `maverick-mcp` name is taken by an unrelated project). The import
  package (`maverick_mcp`) and the `maverick-mcp` command are unchanged.
- PyPI publishing runs one job per package (`fail-fast: false`), so a
  package without a trusted publisher can't abort the others.
- Repository references updated to the `cdayAI` GitHub account.

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

First public release. Maverick combines [Maverick Agent](https://github.com/cdayAI/research/tree/main/maverick) (recursive multi-agent swarm)
and [Agent Shield](https://github.com/cdayAI/agent-shield) (safety detection)
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

**MCP server** (`maverick-mcp-server`)
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
