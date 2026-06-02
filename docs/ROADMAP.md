# Maverick 36-Month Roadmap (Q1 2026 → Q4 2028)

Produced by a 6-agent council pass across six concerns: **capabilities, UX,
distribution, performance, safety, ecosystem**. Each quarter lists ~5-10
concrete tasks per concern, each sized for 1-2 weeks of one engineer's work.

The roadmap is the working backlog, not a contract. Items get re-prioritized
as the community grows and as benchmarks reveal gaps. Track delivery in
GitHub Projects; this doc is the strategic frame.

Positioning: open-source-only, no paid tiers. Building the project as a
brand for the founder. Target audience: general consumers running agents
locally + technical users who want the deepest agent framework on the
shelf (vs Devin, Hermes, OpenClaw, Cline, Aider).

---

## Current state & gap analysis (reconciled June 2026)

*Folded in from the former `ROADMAP-ADDITIONS.md`. The quarterly backlog below is
the forward plan; this section is the **current-state truth**, reconciled against
the code on `main`.*

**Thesis.** The backlog is *breadth-heavy* (100+ tools, channels, integrations).
The highest-leverage additions are **not** more breadth — they cluster in three
under-invested places: (1) the agent-loop control surface (durable execution,
hooks, context lifecycle), (2) the MCP / interop layer the cross-language strategy
rides on, and (3) closing Maverick's own learning & eval loop. Most of (1) and the
reliability plumbing (D) have since shipped — see the table.

**Status:** ✅ shipped · 🟡 partial · ⬜ open. PR numbers cite where it landed;
`file:line` cites implementing code.

| Item | Ask | Status | Evidence |
|------|-----|--------|----------|
| A1 | Durable/resumable execution + checkpoint/rewind | ✅ | `checkpoint.py`, `cli resume` |
| A2 | Kernel lifecycle hooks (Pre/PostToolUse, UserPromptSubmit) | ✅ | `hooks.py` |
| A3 | Context lifecycle — deferred tool loading / memory tool / programmatic calling | 🟡 | deferred loading + `find_tools` (#693); compaction exists; memory-tool + programmatic calling still open |
| B1 | Tool `outputSchema` | ✅ | `server.py` |
| B1 | Resource subscriptions | ✅ #694 | `http_transport.py` |
| B1 | Streamable-HTTP transport | ✅ | `http_transport.py` |
| B1 | Elicitation | 🟡 | client inbound handler shipped (`mcp_client.py`, `tests/test_mcp_elicitation.py`) — answers `elicitation/create` by policy + shield, advertises the capability, `-32601` for other inbound methods; server-outbound (form) + URL mode still open (`specs/mcp-elicitation.md` Phases 2–3) |
| B1 | Async tasks | ⬜ | — |
| B2 | MCP client OAuth 2.1 + Registry | ⬜ blocked | client is stdio-only (`mcp_client.py`); needs a remote-HTTP client transport first |
| B3 | A2A vs. homegrown ACD | ⬜ decision | recommend adopting A2A's Agent Card; reframe/cut ACD |
| C1 | Eval harness (GAIA / τ²-bench / terminal-bench) | 🟡 | GAIA shipped (#687); the other two need real verification-env *harnesses* (SWE-bench-style, cf. `swe_bench.py`), not simple adapters |
| C1 | Skill quality gate / pruning | ✅ | gate (#396) + decay + active pruning (`skill_stats.evictable()` + `skills evict`), wired (`agent.py:274`, `orchestrator.py:227`), tested; only versioning absent |
| C2 | Learning-substrate decision (close loop vs. prune) | ⬜ decision | `training/`, `prm.py`, compaction gate are scaffolds |
| C3 | Verifier default-on across goal types | ✅ | `agent.py:1155–1342` (not coding-gated) |
| D1 | Shared tool-reliability layer | ✅ #684 | `tool_reliability.py`, `retry.py` |
| D2 | Semantic memory wired into reflexion | ✅ #678 | `reflexion.py` cosine path |
| D3 | Session-provider tool-use gaps | ✅ #685 | de-scoped + documented |

**Still open — near-term focus**

1. **MCP elicitation + async tasks (B1)** — client-inbound elicitation has shipped
   (`mcp_client.py` answers `elicitation/create` by policy + shield, no more stalls);
   the remaining server-spec items are server-*outbound* elicitation (form mode,
   capability-gated) and async tasks — both need a design for the synchronous stdio
   loop (outputSchema / resources / streamable-HTTP / subscriptions already shipped).
2. **Remote-HTTP MCP *client* transport → then OAuth 2.1 + Registry (B2)** — the
   client is stdio-only, so the transport is the prerequisite; OAuth validation also
   needs real accounts.
3. **Finish A3** — memory / context-editing abstraction + programmatic tool calling.
4. **Finish C1's benchmark coverage** — terminal-bench + τ²-bench *harnesses*
   (verification-env, SWE-bench-style), not simple adapters.
5. **Decisions (need the founder):** C2 learning substrate (close the eval→reward
   loop or prune the scaffolds); B3 A2A-vs-ACD; and the breadth-vs-depth call — see
   [`specs/tool-inventory.md`](./specs/tool-inventory.md) (56 core tools vs. a
   47-tool SaaS-connector tail).

**Accuracy caveats.** MCP Sampling / Roots / Logging appear to be on a deprecation
path — don't build on sampling. Some ecosystem dates/specs (mid-2026 MCP RC,
LangGraph 1.2, terminal-bench 2.0) postdate the original author's cutoff —
re-verify before committing. Vendor benchmark numbers are directional (contamination
/ single-run inflation) — run multi-seed.

---

## Q1 2026

> **Status (June 2026): ✅ shipped (engineering).** The Q1 capabilities, perf,
> safety, and ecosystem/plugin items are in the tree (tools in `maverick/tools/`;
> `hooks.py`, `checkpoint.py`, `secrets.py`, `killswitch.py`, `audit/`, plugin API;
> CI / publish / release / docs workflows). Community/launch items (Discord,
> HN/Reddit, landing page, good-first-issue sweep) are founder-tracked — not
> code-verifiable here.

**Capabilities**
- **Web search tool**: unified `web_search` with Tavily/Brave/DDG/SerpAPI backends, BYOK, ranked snippets + citations. *(shipped this round)*
- **PDF reader tool**: `read_pdf` via pypdf/pdfplumber with page-range slicing and table detection.
- **Image understanding tool**: `view_image` sends inline images to vision-capable providers, auto-resize + tile-split for large images.
- **HTTP fetch tool**: `http_fetch` with retries, robots.txt respect, HTML→markdown via readability/trafilatura.
- **AST-aware editor**: `ast_edit` wrapping tree-sitter for Python/JS/TS/Go/Rust; supports rename-symbol, extract-function, insert-import.
- **Reflexion retry loop**: on tool failure, an agent gets a `reflection` step to critique its last action before retrying.
- **Streaming tool output**: pipe long shell stdout as incremental events; agent can interrupt runaways.
- **Dependency-graph repo map**: extend repo_map with import + call graphs per language.
- **Token budget tool**: `budget_status` returns remaining context, cost-so-far, per-tool cost breakdown for self-throttling.

**UX**
- **Plan-tree TUI viewer**: `maverick monitor` renders agent/task tree with Rich, refreshing on event stream. *(shipped this round)*
- **Wizard progress bar**: step N/M with breadcrumb trail in `maverick init`.
- **Skip-defaults flag**: `maverick init --fast` drops wizard to <30 seconds.
- **Per-run cost report**: `maverick status --cost` breakdown by agent/model/tool.
- **Budget warning banner**: TUI surfaces yellow/red bar at 50%/90% of configured budget.
- **Trajectory JSONL exporter**: `maverick export <run-id>` writes a portable trace bundle.
- **Web dashboard run list**: historical runs with status badges, duration, cost.
- **Log search command**: `maverick logs grep <pattern>` with context lines.
- **Wizard re-run from step**: `maverick init --resume` at last unanswered question.
- **Starter goals library v1**: 10 curated templates (research, refactor, triage, scrape, ...).

**Distribution**
- **PyPI publish workflow**: GitHub Action with OIDC trusted publishing for all 6 packages on tag push.
- **Conventional commits**: commitlint + commitizen hooks in pre-commit and CI.
- **Semantic versioning automation**: release-please action wired to monorepo packages.
- **CONTRIBUTING.md + CODE_OF_CONDUCT.md**: contributor guide + Contributor Covenant 2.1.
- **Issue and PR templates**: bug/feature/docs/skill-request + PR checklist.
- **"Good first issue" sweep**: label 30+ issues with file pointers.
- **Discord server launch**: #general #help #skills #channels #contributors #showcase.
- **MkDocs Material site**: versioned site at maverick.dev via Pages + mike.
- **Landing page**: maverick.dev with pitch, animated terminal cast, install command, badges.
- **HN/Reddit launch**: coordinated Show HN + r/Python + r/LocalLLaMA.

**Performance**
- **Provider streaming parity audit**: which providers stream tokens vs batch; tracking issue per gap.
- **OpenAI prompt caching wiring**: auto cache_control hints for gpt-4.1/o-series ≥1024 tokens.
- **Gemini implicit cache support**: restructure system+tools before user content so prefix hits.
- **DeepSeek context-caching headers**: pass `prompt_cache_hit_tokens` into unified Usage.
- **Per-turn cost ledger refactor**: structured `CostEvent` jsonl stream.
- **CLI live cost meter**: render running `$0.0123 (cache 38%, in/out 4.1k/892)` line.
- **Token preflight v1**: hard-refuse with actionable error if estimated tokens > context − reserve.
- **World model index audit**: EXPLAIN QUERY PLAN on hot queries; add covering indices.
- **Retry classifier scaffolding**: `ErrorClass` enum + per-class backoff policies.
- **Benchmark baseline freeze**: capture wall-clock, $/task, cache-hit-rate on 50-task SWE-bench slice; pin as `baseline.q1-2026.json`.

**Safety**
- **Structured audit event schema**: versioned JSON event types in `maverick/audit/events.py`.
- **Audit log writer**: append-only NDJSON sink at `~/.maverick/audit/YYYY-MM-DD.ndjson` with rotation.
- **Tool allow-list config**: `agent.allowed_tools = [...]` in profile YAML; registry rejects undeclared tools.
- **Secret detector v1**: regex pack (AWS/GCP/Azure/GitHub PATs/JWTs/Anthropic/OpenAI); redact in tool outputs.
- **Consent prompt primitive**: `require_consent(action, risk_level)` for rm -rf, force-push, dd, mkfs.
- **Killswitch file**: `~/.maverick/HALT` polled each tool call; presence aborts all running goals.
- **Shield bypass test suite**: 50 known jailbreak prompts in CI; regressions fail the build.
- **Threat model doc**: STRIDE pass; `docs/security/threat-model.md`.
- **SECURITY.md**: PGP key, 90-day embargo, scope, safe-harbor language.

**Ecosystem**
- **Plugin API v1 freeze**: stable `maverick.tools`/`.channels`/`.skills`/`.personas` contract; `MAVERICK_API_VERSION`.
- **Plugin lifecycle hooks**: register `PreToolUse`/`PostToolUse` via entry_points (not just TOML).
- **Plugin manifest schema**: `maverick-plugin.toml` declaring API version, capabilities, permissions.
- **VS Code extension MVP**: sidebar webview calling local `maverick serve` REST for goals/episodes/world-model.
- **GitHub Actions wrapper**: `maverick-action@v1` runs the swarm on PR with configurable goal template.
- **Generic OpenAI-compatible provider**: one provider class driven by `base_url`; vLLM/LM Studio/llama.cpp/Together/Groq.
- **Webhook outbound**: `[webhooks] outbound = [...]` config emits signed POSTs for run events.
- **Embeddable mode flag**: `MAVERICK_NO_CLI=1` skips Click imports so library users don't pay startup cost.

---

## Q2 2026

> **Status (June 2026 — current quarter): 🟡 mostly shipped.** Landed: voice
> in/out, Docker sandbox, cross-agent bus, OCR, preview-diff / kv-memory /
> clipboard; OpenTelemetry / Prometheus / Sentry, repo+file caches, parallel tools;
> per-channel & per-user ACLs, signed skills; Postgres / TGI / Chroma adapters,
> arXiv, catalog index. Remaining are mostly community/distribution (playground,
> cookbook growth, socials, bug bounty) plus a few perf/safety classifiers —
> in-progress or founder-tracked.

**Capabilities**
- **Voice input (Whisper)**: `transcribe_audio` via faster-whisper + OpenAI/Groq Whisper API, diarization + timestamps.
- **Voice output (TTS)**: `speak` via ElevenLabs/OpenAI/Piper, streamable, SSML support.
- **Docker sandbox executor**: shell `--sandbox docker` spins ephemeral container per session.
- **ReAct trace compression**: collapse repetitive thought/action loops into single observation.
- **Cross-agent message bus**: `send_to_agent(id, payload)` + `recv_from_agent()` for non-parent-child swarms.
- **Screen-OCR fallback**: Tesseract/PaddleOCR when computer-use can't see DOM.
- **Type-aware refactor (Python)**: pyright watch mode gives type-error feedback after each edit.
- **File-diff preview tool**: `preview_diff` shows unified diff of pending edits before commit.
- **SQLite memory tool**: `kv_get/kv_set/kv_search` for cross-session fact persistence.
- **Clipboard tool**: `clipboard_read/write` bridge between computer-use, browser, shell.

**UX**
- Web plan-tree visualization (D3/Cytoscape live tree in dashboard).
- Agent trajectory replay with variable speed.
- Event timeline view with filter by agent/severity.
- Error inspector panel for failed turns.
- Monthly cost summary with CSV export.
- Channel rich formatting (code blocks, tables, inline images).
- File attachment inline (drop into Slack/Discord).
- Wizard undo (Backspace/<).
- Theme presets (dark/light/solarized/hicontrast).
- Push-notification bridge (ntfy.sh/Pushover).

**Distribution**
- Homebrew tap with auto-bump Action.
- Docker Hub official multi-arch image, signed with cosign.
- PyInstaller release binaries (Linux/macOS/Windows).
- Playground site (try.maverick.dev) on Pyodide.
- Cookbook section: 12 recipes runnable in <60s.
- awesome-maverick-skills curated repo.
- YouTube channel + first 3 tutorials (install, first skill, multi-agent swarm).
- Twitter/X 90-day content calendar.
- DevRel blog series (6 posts: architecture, channels, shield, comparisons).
- GitHub Sponsors + Open Collective.

**Performance**
- OpenTelemetry traces (opt-in OTLP).
- Prometheus `/metrics` endpoint.
- Sentry integration (opt-in DSN).
- Streaming-everywhere phase 1 (Anthropic, OpenAI, Gemini).
- Hierarchical compaction v1 (two-tier: per-tool + per-phase).
- Repo-map cache with content-addressed invalidation.
- File-content read cache (LRU per run).
- Parallel tool execution via asyncio.gather.
- Failure-mode taxonomy doc + fault-injection tests.
- Compaction quality regression suite (20 long-trajectory fixtures).

**Safety**
- Prompt-injection classifier (DeBERTa-v3 stage after regex).
- Jailbreak score on user input.
- Output policy classifier (refusal leak, system-prompt regurgitation).
- Per-channel ACL: channel ID → allowed_tools.
- Per-user ACL: identity → max risk + tool subset.
- PII detector (presidio-style) with redaction under strict profile.
- Erase coverage extension: scrub audit log entries.
- Sandbox-escape canaries.
- Bug bounty launch (huntr.dev or HackerOne).
- Signed releases via cosign on PyPI + Docker.

**Ecosystem**
- Skill marketplace index (static JSON at skills.maverick.dev).
- Signed skills with Ed25519 sig in frontmatter.
- Trusted publisher badge.
- Bluesky + Mastodon channels.
- Postgres world-model backend.
- HuggingFace TGI provider.
- arXiv tool (paper search + abstract fetch).
- Chroma vector store adapter.

---

## Q3 2026

**Capabilities**
- Video understanding (`view_video`: adaptive frame sampling + audio transcript → Gemini/GPT-4o).
- Tree-of-thought planner mode (3-5 candidate plans, critic scores, execute winner).
- SSH sandbox executor for remote deployment agents.
- Browser session persistence (cookies/localStorage per-task survive crashes).
- Multi-file atomic edits (`apply_patch` all-or-nothing).
- Debate protocol primitive (`debate(question, [A, B], rounds, judge=C)`).
- Symbolic math tool (SymPy: arithmetic, calculus, equations).
- Data analysis tool (`pandas_query` on CSV/Parquet/JSON).
- Email tool (SMTP send + IMAP/Gmail read).

**UX**
- iOS/Android companion app alphas (SwiftUI/Compose, QR-pair, push, ack-then-run).
- Hotword wake-up (offline porcupine).
- STT task issuance (`maverick voice` → Whisper → run).
- TTS run summaries (system TTS or ElevenLabs).
- Voice messages in channels (auto-transcribe).
- Approval queue UI in dashboard.
- Run sharing as gist (sanitized).
- "Claim as bug report" pre-filled GitHub issue.
- Locale scaffolding (gettext/Babel) + English + Spanish bundled.

**Distribution**
- apt/dnf repos via Cloudsmith.
- AUR (Arch) packages.
- Snap package with stable channel.
- VS Code extension v1.
- Plugin marketplace v1 (PyPI packages with `maverick-plugin` tag).
- Channel marketplace v1.
- Telemetry opt-in (privacy-respecting; quarterly public report).
- Comparison benchmark suite v1 (Maverick/Devin-OSS/Cline/Aider on 30 SWE-bench-lite tasks).
- Conference CFPs (PyCon US, EuroPython, PyData, KubeCon AI Day, OSS Summit).
- Newsletter launch (monthly "Maverick Dispatch").

**Performance**
- KV-cache reuse across roles in best-of-N (shared immutable prefix).
- Speculative decoding via vLLM (small draft + large target).
- Ollama parallel-request tuning.
- Cost-aware router v1 (auto-downgrade Opus→Sonnet under quality threshold).
- Streaming-everywhere phase 2 (DeepSeek/Moonshot/xAI/Ollama/OpenRouter).
- Distributed swarm tracing (parent-child OTel spans).
- World model partitioning (shard events by run_id range).
- Chaos test harness (`chaos/` package).
- Network-partition simulator (ToxiProxy-style middleware in CI).
- LLM-response cache (semantic, disk-backed, TTL).

**Safety**
- Audit log signing (Ed25519 prev-hash chain; `maverick audit verify`).
- Append-only enforcement (`chattr +a` on Linux).
- Provenance tags on artifacts (`.maverick-prov.json` sidecars).
- Goal-budget enforcement (max tokens / tool calls / wall-clock).
- Bot-detection on remote content (injection patterns, hidden Unicode).
- Unicode/zero-width filter on inbound text.
- Anti-spam heuristic (mass-send consent).
- Credential-stuffing detector.
- Telemetry opt-in only.
- Anonymous mode (`MAVERICK_ANON=1` strips goal text/usernames).

**Ecosystem**
- JetBrains plugin MVP.
- Linear + Jira integrations (issue-assigned → goal).
- GitLab CI wrapper.
- Voice channel (Twilio Voice in, TTS reply).
- Generic inbound webhook (`POST /webhook/start` HMAC-signed).
- **Wearable / smart-glasses channel — Even Realities G2 (BYOA bridge)**: thin self-hostable bridge (Cloudflare Worker *or* local edge service fronting `POST /webhook/start`) that exposes Maverick as the "bring-your-own-agent" backend for G2 glasses — on-device STT in, green-laser HUD out, with a quick-reply (<22 s) vs. ack-then-run split sized to the G2's ~30 s timeout and long-task results routed to a secondary channel. New `glasses` adapter in `maverick-channels` + wizard knob; see council note below.
- Podman sandbox.
- Devcontainer sandbox.
- gRPC API surface (`StartGoal`/`StreamEpisode`/`Cancel`).
- **MCP-as-cross-language-surface (council decision)**: harden the
  MCP server so any TypeScript / Go / Rust / .NET / JVM client can
  drive Maverick over stdio JSON-RPC; ship a 20-line TS quickstart
  in the README + `docs/clients/`. See "Language Bindings — Council
  Decision" below.

---

## Q4 2026

**Capabilities**
- Kubernetes sandbox executor (jobs in a cluster, GPU/parallel workloads).
- Long-context retrieval router (>200k tokens auto-shard to FAISS/Chroma).
- Reflexion library (persistent failure-pattern memory across sessions).
- Browser form-fill helper (batch dozens of inputs).
- Mobile emulator tool (Android via UIAutomator).
- iOS simulator tool (Xcode simctl + accessibility tree).
- Calendar tool (Google/Outlook/CalDAV).
- Git advanced ops (bisect, rebase --onto, cherry-pick, worktree).
- Coverage-guided test runner (pytest-testmon style).
- Embedding-as-a-tool (Voyage/OpenAI/Cohere/local).

**UX**
- Replay-from-trajectory (`maverick replay <id> --from-step N`).
- Diff viewer for plan revisions.
- Cost forecasting (`maverick start --dry-cost` with embedding similarity).
- Budget envelope alerts (per-channel daily caps).
- Screen reader pass (TUI ARIA, NVDA/VoiceOver tested).
- Keyboard-only dashboard with `?` shortcut overlay.
- Channel digest mode (4-hour summary).
- Inline image rendering (Kitty/iTerm image protocol).
- Goal templates v2 community registry.
- Onboarding tour (5-step interactive walkthrough).

**Distribution**
- Flatpak (Flathub).
- Scoop + Chocolatey (Windows).
- **1.0 stable release**: API freeze, semver guarantees, deprecation policy, signed artifacts.
- Public ROADMAP page + GitHub Projects mirror.
- Skill quality leaderboard on HuggingFace.
- Embed integrations doc (FastAPI/Django/Flask/Slack/Discord/Telegram).
- Cookbook to 30 recipes.
- Localized docs phase 1 (zh-CN).
- Maintainer team formalization (3-5 external committers).
- Year-end retrospective post.

**Performance**
- Adaptive thinking budget controller (closed-loop Opus thinking adjustment).
- Compaction v2 retrieval-augmented (embed locally; retrieve top-k chunks).
- Structural compaction (collapse file-read tool_use/tool_result to path+sha refs).
- Provider health board (per-provider success/latency/$).
- Memory profiling baseline (tracemalloc + memray weekly soak).
- GC tuning experiment (`gc.freeze()` post-warmup).
- Token-prediction preflight v2 (regressor on collected runs).
- WAL checkpoint scheduler (explicit checkpoint-on-idle).
- HTTP/2 pool sizing audit.
- 1-year retrospective benchmark (vs Q1 baseline).

**Safety**
- Shield v2 (bidirectional output scanning for exfil patterns).
- Deterministic replay (`maverick replay <traj.jsonl>` with fixed seeds + mocked tools).
- Trajectory storage (`~/.maverick/traj/<goal_id>.jsonl`).
- Capability tokens (unforgeable handles passed by orchestrator).
- Network egress allow-list in docker sandbox.
- DNS-rebinding mitigation in browser tool.
- File-write quota per goal.
- SBOM (CycloneDX) per release.
- Vendored-deps audit (pip-audit + osv-scanner in CI).
- CODEOWNERS + security-team rotation.

**Ecosystem**
- Plugin API v1.1 (additive: `tool.streaming`, `Channel.send_typing()`).
- ACD spec v0.1 (Agent Capability Descriptor; published `docs/specs/acd.md`).
- LangChain compat shim.
- LangGraph adapter.
- Kubernetes sandbox `sandbox/k8s.py`.
- Notion + Obsidian integrations.
- IRC channel.
- Plugin scaffolding CLI (`maverick plugin new <name>`).

---

## 2027 — H1

**Capabilities**: Firecracker microVM sandbox; audio understanding (non-speech CLAP); 3D model viewer; DOM accessibility-tree extractor (5-10x token cut); plan-execute-reflect loop topology; cross-language LSP bridge; file watcher; spreadsheet tool; vector-store as first-class memory; speculative parallel tool calls. Constrained-generation tool; speech-to-action live-mic; GUI element memory; image gen + edit tools; web automation recorder; ASR meeting listener; auto-skill distillation v2; per-tool rate limiter; diff-aware code review.

**UX**: Multi-run dashboard; pinned watch list; annotated traces; comparative replay; mobile push v2; Apple Watch glance; voice command grammar; voice in channels v2 (Discord stages); high-contrast & dyslexic fonts; i18n expansion (fr/de/ja/zh). Visual graph editor; tool-call inspector; latency heatmap; search-across-runs; saved dashboard views; "what changed" digest; channel reply threading; drag-and-drop goal builder; plain-language explanations; error pattern recognizer.

**Distribution**: Localized docs phase 2 (es/ja); reproducible benchmark v2 (terminal-bench, weblinx, HumanEval-fix); marketplaces v2 with ratings; tutorial video season 2; university outreach (5 partnerships); skill validator service; comparison page; press kit; devcontainer + Codespaces template. Maverick Summit v1 (virtual); showcase wall; integration partnerships (LangSmith/Helicone/OpenRouter); reference architectures (k8s/ECS/Fly.io/Railway); browser extension v1; skill + channel template generators; localized docs phase 3 (de/fr/pt-BR); GitHub Stars campaign; office hours.

**Performance**: Tiered storage (hot SQLite + cold parquet); query plan regression CI; async compaction; cache purge API; cost-aware router v2 (per-role policies); parallel agent execution within a run; streaming tool_result; Sentry performance tab; provider failover policy engine; adversarial-cost benchmark suite. Continuous batching local; compaction v3 learned summarizer; per-tool latency profile; speculative tool execution; gRPC dispatch; WAL contention audit (N=16); cache-warm-on-start; memory-leak quarantine; cost-attribution API; public perf dashboard.

**Safety**: EU AI Act risk classification helper; HIPAA mode profile; SOC2-aligned audit export; encrypted audit at rest (AES-GCM keyed via OS keychain); differential privacy on usage stats; consent ledger; two-person rule for irreversible ops; shield calibration dashboard; adversarial eval harness; coordinated-disclosure log. Multi-agent collusion detector; per-agent identity + signing; capability delegation graph; watermark detector; image-content classifier; voice safety pass; geofence config; data-retention enforcement; privacy budget per user; red-team CI.

**Ecosystem**: Marketplace ratings + install verification; Voyage + Cohere embeddings; Qdrant + Weaviate vector stores; Bitbucket Pipelines; Emacs integration; WhatsApp Cloud API rewrite. Plugin sandboxing (subinterpreter); hot plugin reload; Vim/Neovim plugin; GitHub + GitLab Issues integrations; Google Calendar; SemanticScholar; Wikipedia tool; S3-backed attachments.

---

## 2027 — H2

**Capabilities**: Multi-modal RAG; agent-to-agent debate over shared scratchpad; WASM sandbox; ROS robotics action tool; browser anti-bot evasion kit (opt-in); SQL agent tool (read-only by default); LaTeX render; diagramming (Mermaid/Graphviz/PlantUML); critic-agent template; cost-aware model router. Persistent task graph (checkpoint per step); browser auth vault; HTML-to-app scaffolder; notebook execution; real-time WebSocket tool; multi-agent observation channel; self-edit tool (human-gated); browser device emulation; Slack/Discord/Teams tool; continuous-benchmarking tool.

**UX**: Native macOS/Windows/Linux GUI apps; browser extension; voice persona presets; multi-language voice; wizard branching paths; inline cost preview; run gallery; replay export to MP4. Collaborative supervision (multi-user dashboard); approval delegation rules; trace pinning to commit; VS Code + JetBrains live-run extensions; TUI mouse mode; cost anomaly alerts; "why this cost" drill-down; run-as-tutorial export; accessibility audit pass; i18n community portal.

**Distribution**: macOS .app + DMG; Windows MSI; Linux AppImage; marketplace moderation tooling; sponsorship tiers; conference physical booth; swag store; ambassadors program; long-form handbook; Skill of the Year award. 2.0 RFC; backwards-compat tooling (`maverick migrate`); mobile companion app v1 (read-only); self-hosted relay reference; localized docs phase 4 (ko/ru/it/hi); video season 3; skill search engine (HF); annual community survey; foundation exploration.

**Performance**: Anthropic 1h extended cache adoption; token-level cost projection at plan time; compaction v4 structural diff; tool-call dedup cache; provider rate-limit predictor; latency-aware best-of-N (cancel slowest); distributed cache (Redis); cold-start optimization (<300ms `--help`); JIT consideration (mypyc/cython on hot path); reliability SLO publication (99.5%). Compaction v5 multi-modal; cross-run learning cache; autoscaling local backends; energy/CO2 accounting; real-time anomaly detection; failure-mode telemetry shipping (opt-in); tail-latency hunting; KV-cache offload to disk; provider migration cost calculator; 2-year retrospective.

**Safety**: Constitutional layer (NL profile rules → runtime classifier checks); refusal calibration; gVisor tool sandbox; eBPF syscall monitor; memory-safe parsers; supply-chain pinning; sigstore keyless signing; out-of-process model proxy; rate-limit shield calls per goal; public safety bulletin RSS. Federated shield model updates; model card per LLM; behavioral diff on upgrades; cross-run anomaly detection; honeytoken planting; tamper-evident screenshots; DSAR command; right-to-rectification; crash-only logging; annual safety report.

**Ecosystem**: ACD spec v1.0; AutoGen + CrewAI adapters; Threads + RCS channels; Anki integration; web archive tool; GitHub repo search; Redis world-model. Plugin telemetry opt-in; marketplace v2 (federated indexes); IDE protocol unification (one MCP server, multiple editors); run-events firehose (WebSocket); generic OAuth helper; DuckDB world-model; Cloudflare Workers + Modal sandboxes; plugin version-pinning lockfile.

---

## 2028 — H1

**Capabilities**: Live-DOM diff in browser tool; computer-use coordinate calibration; audio diarization + emotion; vision-grounded clicking; file-format converter (pandoc+ffmpeg+libreoffice); knowledge-graph builder; cron/scheduler tool; workspace snapshot/restore; tool-output cache; async tool invocation. Multi-monitor computer-use; process introspection; hardware sensor tool; voice cloning consent gate; semantic code search; cross-repo dependency graph; test generation (Hypothesis); mutation testing; container build tool; streaming reasoning trace channel.

**UX**: Plan-tree minimap; conversational supervisor; voice-only mode; smart notification batching; mobile offline cache; augmented terminal (Rich inline charts); cost split by tag; multi-tenant view; personalized starter templates; replay annotation export. AR plan-tree (visionOS); live captions voice; visual goal templates marketplace; "diff to expected"; smart goal completion; adaptive UI density; embedded analytics web component; pluggable themes API; voice macros; RTL language support.

**Distribution**: 2.0 stable release; migration playbook; marketplace v3 (donate-direct model); Maverick Summit v2 (hybrid); editor expansion (JetBrains/Neovim/Zed); localized docs phase 5 (top-15 langs + MT pipeline); "Built with Maverick" badge program; comparison benchmark v3 live dashboard; university curriculum kit; foundation paperwork submitted. ARM/RISC-V builds; iOS/Android skill execution (Pyodide/Kivy); skill + channel certification programs; community grants v1; regional meetup playbook; embeddable widget; hosted demo cluster (demo.maverick.dev); press push to major outlets; sponsor tier 2.

**Performance**: Speculative best-of-N (kill underperformers at first reasoning checkpoint); compaction v6 hybrid (learned classifier picks strategy); sub-ms dispatch overhead (msgspec/orjson); continuous profiling daemon (py-spy); cost-aware routing v3 (contextual bandits); sandbox pool (warm Docker/Firecracker, <100ms acquire); replayable trace format; cache-aware prompt assembly DSL; SLA-breach automation; open metric standard. Multi-region failover; compaction v7 streaming; long-context cost guardrails (>$50/run gate); persistent KV-cache for local; network egress accounting; online schema migrations; p999 latency campaign; cost-of-quality study; battery-mode for laptops; ML cache eviction (ARC/LeCaR).

**Safety**: Risk-tier auto-classifier (low/med/high goal scoring); containment mode (no-network ephemeral fs); capability negotiation protocol; cryptographic budget receipts; independent audit-log mirror; quorum approval for config changes; phishing-content detector; misuse leaderboard removal; license compliance scanner; safety steering group. Formal verification of sandbox interface (TLA+); capability-leak fuzzer; provenance chain across agents; multi-tenant isolation tests; right-to-explanation; bias eval suite; long-horizon goal review checkpoint; provider-level cost cap; backport security fixes; external SOC2 Type I.

**Ecosystem**: Plugin API v2 RFC; plugin compatibility matrix CI; multi-language plugin support (gRPC plugin host); TypeScript plugin SDK; generic SaaS-trigger framework; pgvector adapter; Apple Shortcuts integration; browser-extension chat. Plugin API v2 release; marketplace moderation tools; ACD interop tests; voice channel v2 (streaming ASR + barge-in); Discord slash-command framework; Slack workflow integration; Salesforce/HubSpot adapters; local-first embeddings cache (LMDB).

---

## 2028 — H2

**Capabilities**: WebRTC tool; browser extension bridge; ARIA-first navigation; adversarial self-test; sandbox-escape detector; embedded device tool (serial/JTAG/I2C); mixed-precision local inference; speculative decoding across providers; long-form writing (outline→draft→polish); citation verifier. Continuous-learning skill loop (local); agent simulator harness; multi-agent fairness scheduler; sub-second tool latency budget; network sandbox (per-tool egress); zero-config BYO-tool (`@tool` decorator); WebGPU local vision; synthetic data tool; federated swarm protocol; capability self-report tool.

**UX**: "Director" mode (outcomes → plans → autonomy); cross-device handoff; predictive approvals; run health score; embedded video walkthroughs; granular redaction UI; conversation memory across runs; voice biometric unlock; power-user keymap editor; localized currency display. Unified inbox; smart NL filters; 3D plan-tree (WebGL/VR); self-healing UX; channel auto-routing; onboarding personalization v2; "achievements"; cost retrospective AI; universal share link; 36-month UX retrospective + reset.

**Distribution**: Maverick Conference v3 (in-person flagship); hackathon series; localized communities (top 5 non-English); skill marketplace federation; channel federation; public roadmap voting; press kit v2 + case studies; comparison benchmark v4 with reproducibility audits; handbook v2; "5-year vision" essay. Foundation hand-off; governance v2 launch (elected TSC); documentation rewrite; tutorial season 4; survey v3 + retrospective; sponsor renewal drive; HF Space spotlight; awards push; 2029 roadmap publication.

**Performance**: Self-tuning budgets (per-task-class learned defaults); compaction v8 graph-structured; zstd compression on world_model; critical-path-aware parallel scheduling; provider-side caching analytics; chaos game-day script; cost telemetry retention policy; provider-cost-curve fitter; real-time SSE dashboards; reliability harness 2.0. Cost/perf canary system per release; compaction v9 plug-in API; latency budget propagation across spans; energy-aware routing; local-first default mode; full OpenTelemetry semconv; 3-year retrospective benchmark; reliability cert; public perf SLA; sunset deprecated paths.

**Safety**: Shield v3 (small-model ensemble: injection + jailbreak + exfil + policy, explainable reason codes); provable redaction; differential erasure verification; air-gapped mode (full stack, no outbound); confidential-compute support (SEV-SNP/TDX); per-jurisdiction data residency; adversarial-prompt corpus release; AI Act conformance package; vuln reward expansion; third-party pen test. Federated audit-log verification; capability revocation propagation; key rotation playbook; PIA generator; safety regression budget; polyglot injection defense; consent ergonomics pass; 36-month safety retrospective; sunset policy; LTS safety branch (2-year support).

**Ecosystem**: Plugin signing CA; capability negotiation at swarm boot; gRPC API v1 stable; federated swarms over gRPC; KaTeX/Mermaid rich-render channel; Open Banking tool (Plaid/TrueLayer); HomeAssistant integration; email channel v2 (IDLE + threading); MCP server publishing. Marketplace stats dashboard; plugin API v3 RFC (if warranted); ACD spec v1.1; generic OIDC tool; multi-tenant `maverick serve`; channel SDK v2 (async-only); sandbox SDK v2; long-running plugin reliability suite; 3-year retrospective + 2029-2031 plan.

---

## Language Bindings — Council Decision (May 2026)

Three-perspective council pass on whether to ship Maverick in Rust /
TypeScript / Go / other languages. Research covered LangChain.js,
AutoGen .NET, CrewAI, Mastra, OpenAI/Anthropic SDKs.

### Conclusion

**Thin API clients port well; opinionated frameworks don't.** Maverick
is the second kind. We do **not** port `maverick-core` to a second
language. Instead we expose Maverick to other languages **over MCP**.

### Top 5 target languages (priority order)

1. **TypeScript / JavaScript** — half the agent dev population lives in
   Node / Next.js; Mastra demonstrates the appetite. Ship the official
   client here first.
2. **Go** — k8s / cloud-native operators, infra teams, devops tools.
   Modest LOC count (HTTP + JSON), pairs naturally with the
   Kubernetes sandbox.
3. **Rust** — embedded / perf-sensitive callers, CLI tool authors;
   smallest binary size; strong typing buys safety in long-running
   automations.
4. **C# / .NET** — Microsoft / Unity / Game-dev ecosystem; .NET
   Aspire and Semantic Kernel users want a turnkey agent backend.
5. **Java / Kotlin** — JVM enterprise + Android; second-class today,
   but the ROI on a single thin client is high once #1 ships.

(Python is not on this list because it *is* Maverick.)

### Gate: don't decide, measure

Smallest concrete first step (1–2 weeks, one engineer):

1. Polish the existing MCP server as the official cross-language
   surface. *(Q3 2026: in progress.)*
2. Ship a 20-line **TypeScript quickstart** in the README — uses the
   official MCP SDK, connects to a locally running `maverick mcp`,
   issues one tool call. *(Q3 2026.)*
3. Mirror that quickstart for **Go** and **Rust** before any
   client-package decision. *(Q4 2026.)*
4. Add opt-in analytics on MCP-client language headers.
   *(Q4 2026 — needs new telemetry consent UI.)*
5. **Decision gate (Q1 2027):** if >15% of active installs are being
   driven from non-Python MCP clients, fund **one** thin
   `@maverick/client` TypeScript package (RPC wrapper, ~2k LOC,
   Stainless-generated where possible). Under 15%, the answer is the
   MCP surface, full stop.

### Hard constraints

- No port of `maverick-core` to a second language ever — that's a
  permanent ~40% team-headcount tax that LangChain.js shows still
  doesn't yield parity.
- Sandbox backends (firecracker, k8s, devcontainer, podman) stay
  Linux-process glue in Python; they are not part of the
  cross-language contract.
- Multi-agent topology (orchestrator + proposer + verifier + revisor +
  reflector) stays Python. Other languages drive Maverick; they do
  not re-implement it.

### Roadmap placement

The MCP-surface + quickstart deliverables live under
**Q3 2026 — Ecosystem** (MCP hardening, TS quickstart) and **Q4 2026
— Ecosystem** (Go + Rust quickstarts, MCP-client analytics). The
binding decision itself is gated to **Q1 2027** based on measured
non-Python MCP usage.

---

## Wearable Channel — Even Realities G2 (BYOA bridge) — Council Note (June 2026)

OpenClaw (the Rust competitor we benchmark against) shipped a "bring-your-own-agent"
bridge that drives **Even Realities G2** smart glasses. The ask here is *not* to
integrate OpenClaw — it's to make **Maverick** drivable from the same glasses, as
just another channel. The pattern is a near-perfect showcase of the long-horizon
wedge, so it earns a roadmap slot.

### How OpenClaw does it (for reference)

- A thin **~250-line Cloudflare Worker** translates between the G2's expected API
  shape and OpenClaw's Gateway protocol. That bridge is OpenClaw-specific (published
  as a reusable *OpenClaw Skill*); the glasses themselves are agent-agnostic.
- The G2 has a hard **~30 s** request timeout. The Worker enforces a **22 s**
  deadline and classifies each utterance:
  - **Quick query** (weather, a fact, short chat) → proxied synchronously to the
    Gateway and answered inside the deadline.
  - **Long task** (`write.*code | research | deploy`) → answered *immediately* with
    an ack ("Got it! Writing article… result will be sent to Telegram"), run in the
    background on an isolated session, with the full result delivered to a
    **secondary channel** (Telegram) when done.
- **Voice is handled on-device**: the G2 does its own speech-to-text and sends only
  text; replies render on the green-laser **HUD** (no TTS audio in the loop).

### Why it fits Maverick (reuse, don't reinvent)

This is the **ack-then-run** pattern already on the roadmap (Q3 2026 mobile alpha),
sitting on seams that already exist:

- **Channel adapter** — a new `glasses` adapter in
  `packages/maverick-channels/maverick_channels/` next to `telegram.py` / `voice.py`,
  subclassing `base.py`. The HUD's short-text constraint reuses `formatting.py`.
- **Transport** — the bridge fronts the existing inbound `POST /webhook/start`
  (Q3 2026 "Generic inbound webhook"); no new server surface.
- **Long-task delivery** — results ride the existing **outbound webhooks**
  (`packages/maverick-core/maverick/webhooks.py`) + push bridge into a secondary
  channel, exactly as OpenClaw routes to Telegram.
- **Voice tools optional** — `transcribe_audio` / `speak`
  (`maverick/tools/voice.py`) are *not* needed for G2 (on-device STT, HUD out), but
  cover wearables that ship raw audio instead.

### Constraints (house rules)

- **Open-source-first / self-hostable.** OpenClaw's bridge is a Cloudflare Worker — a
  hosted dependency. Ours ships with a "you can self-host this" path: the same thin
  shim runs either as a Worker **or** as a small local/edge service pointing at
  `POST /webhook/start`. No mandatory paid edge.
- **Config knob + wizard (CLAUDE.md #5/#6).** A new channel adapter gets a
  `[channels.glasses]` knob and an enable/disable step in the installer wizard
  (`apps/installer-cli/maverick_installer/wizard.py`).
- **The timeout split is the point.** The quick-vs-ack-then-run boundary is where the
  long-horizon design shows up on a 30-second device — keep it the headline of the
  demo, not an afterthought.

### Roadmap placement

Headline item under **Q3 2026 — Ecosystem** (the channels cluster, beside the Voice
channel and inbound webhook it depends on). Its prerequisites — ack-then-run
(Q3 2026 UX), inbound/outbound webhooks (Q1/Q3 2026 Ecosystem), push-notification
bridge (Q2 2026 UX) — all land by Q3 2026, so no new long-pole work is implied. The
broader "smart-glasses / wearable channel" generalization (other devices, audio-out
wearables) tracks alongside the **2027 H1** wearables cluster (Apple Watch glance,
voice command grammar).

### Verify before committing

Device-side specifics (the ~30 s timeout, on-device STT behavior, HUD payload limits)
are third-party-reported — one community write-up plus Even's support center — and
should be re-checked against Even Realities' own G2 SDK before this becomes a build
commitment — the same caveat discipline as the **Accuracy caveats** under "Current
state & gap analysis" above.

**Sources:** [G2 × OpenClaw bridge write-up](https://blog.juchunko.com/en/even-realities-g2-openclaw-bridge/) ·
[Even Support Center — G2 "Bring Your Own Agent"](https://support.evenrealities.com/hc/en-us/categories/13489714076815-G2) ·
[bridge published as an OpenClaw Skill](https://mcpmarket.com/tools/skills/even-realities-g2-openclaw-bridge) ·
[prior art — openclaw-glasses for Even G1](https://github.com/littlebotshi/openclaw-glasses)

---



- **Track items**: each line is a candidate GitHub issue. Slice into smaller PRs as needed.
- **Re-prioritize**: items move freely. Anything in Q4 2028 can land Q1 2026 if a contributor wants to ship it. The quarter labels are guidance about scaling and team size, not constraints.
- **Cross-concern dependencies**: marked implicitly by quarter alignment. If you tackle a Q3 2027 capability item, expect related UX/safety items the same quarter to be useful as prerequisites.
- **Honest about scope**: each item should be sized at 1-2 weeks of one engineer's time. If something looks bigger when you start, slice it.
- **Open-source first**: no item assumes paid infrastructure. Anything that requires hosted services (e.g., marketplace index) ships with a "you can self-host this" path.
