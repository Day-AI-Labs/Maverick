# Maverick 36-Month Roadmap (Q1 2026 → Q4 2028)

Produced by a 6-agent council pass across six concerns: **capabilities, UX,
distribution, performance, safety, ecosystem**. Each quarter lists ~5-10
concrete tasks per concern, each sized for 1-2 weeks of one engineer's work.

The roadmap is the working backlog, not a contract. Items get re-prioritized
as the community grows and as benchmarks reveal gaps. Track delivery in
GitHub Projects; this doc is the strategic frame.

Positioning: **proprietary, commercially licensed enterprise software**,
self-hosted in the customer's environment. A deliberately stripped-down
**open-source "lite" edition** may follow later as a community on-ramp (once
the platform is built out), but the full runtime + governance/compliance
platform stay proprietary. Target audience: enterprise / regulated teams that
need a self-hostable, governed, auditable agent runtime, plus technical users
who want the deepest agent framework on the shelf (vs Devin, Hermes, OpenClaw,
Cline, Aider).

---

## How this doc works

This roadmap is the **forward backlog — what isn't built yet.** When an item
ships, it comes *off* this list and moves to [`FEATURES.md`](./FEATURES.md), the
catalogue of built features and tools. So if something you remember seeing here
is gone, it almost certainly shipped — check `FEATURES.md`.

## Current state (June 2026)

The original gap analysis is **done**: the agent-loop control surface (A1–A3),
the MCP / interop layer (B1–B3), the learning & eval loop (C1–C3), and the
reliability plumbing (D1–D3) are built, along with a large
**governed-agent-runtime + domain-pack** surface (conversational intake, RBAC,
per-domain knowledge RAG, reverse-proxy SSO, SIEM audit export, scheduling). All
of it is catalogued in [`FEATURES.md`](./FEATURES.md).

**Framing (June 2026): this is now a governed agent _platform_, not just a
local kernel.** The three-layer control plane is real — oversight
(`governance.py`), compliance-regime engine, per-employee fleets (`fleet.py`) —
on a tenant-aware substrate (`workspace.py` walls each tenant into
`~/.maverick/tenants/<t>/`; the world model keeps a per-tenant DB; `data_dir()`
routes audit/quotas/dsar/soc2/fleet; `quotas.py` enforces per-principal spend
caps; OIDC + `[roles.<role>]` RBAC gate access). The forward backlog is now
organised around **finishing the platform spine** (below) over the old quarter
grid, which is mostly shipped.

**Still open — near-term engineering:**

- **MCP elicitation, URL mode (B1, Phase 3)** — the secrets-never-transit-model
  path; dovetails with remote-server OAuth (`specs/mcp-elicitation.md`).
- **IRC channel** and **LangChain / LangGraph adapters** — external-dependency
  connectors that need a live service to test meaningfully.
- **Glasses / wearable channel** — Even Realities G2 BYOA bridge, and wearable
  integrations generally; expected to become table-stakes, so it stays a
  standing roadmap commitment. See the council note below.
- **MCP-client language analytics** — the one remaining language-bindings gate
  step (needs the telemetry-consent UI); see the council decision below.

> **Shipped since this list was last cut:** the **long-context retrieval router**
> (`long_context_router.py`, opt-in `[context] retrieval_router`); the **gRPC API
> surface** (`grpc_api/`, `StartGoal` / `StreamEpisode` / `Cancel` / `GetStatus`
> behind the `[grpc]` extra); **MCP client OAuth 2.1 authorization-code grant +
> PKCE** (`AuthorizationCodeProvider`, `mcp_oauth.py` — joining the shipped
> client-credentials grant); a **goal-execution Dispatcher seam** (`runner.py`,
> threads now / queue later via `set_dispatcher`); and the oversight **"why this
> action" drill-down**. All are in [`FEATURES.md`](./FEATURES.md).

**Platform spine — what's left to be a multi-tenant hosted platform.** The
single-node, file-per-tenant model is solid (and is the right shape for
self-hosted, one-tenant-per-deploy). Eventually-both (self-hosted **and** a
hosted SaaS) means finishing these, roughly in dependency order. None is a
code-red; the two seams are cheap-now/costly-later and are partly done.

- **Shared-DB tenancy (Postgres).** A versioned migration runner + a nullable
  `tenant_id` on the root tables + write-stamping + NULL-tolerant read-scoping
  for goals have **shipped** (`world_model_backends/postgres.py`). Remaining:
  extend read-scoping to the rest of the root tables, then move to Row-Level
  Security + a connection pool for strict isolation and horizontal scale. _(#1
  spine item.)_
- **Control-plane / data-plane split.** Goals still run as threads in the API
  process (`runner.py` `BoundedSemaphore`). Keep dispatch behind an interface
  now; swap to a real queue (arq / Celery / Temporal) + isolated per-run workers
  when one box can't keep up. _(#2 spine item.)_
- **Tenant lifecycle / provisioning API** — create / suspend / delete / assign
  quota, plus an operator cross-tenant console. Wake at ~3 hosted tenants.
- **Metering → billing / entitlements** — `quotas.py` records & caps usage;
  rating / invoicing / plan-gating is unbuilt. Wake at first hosted revenue.
- **Per-tenant secrets / KMS** — `crypto_at_rest.py` is single-tenant; add a
  per-tenant DEK wrapped by a KMS KEK. Wake at first sensitive hosted tenant.
- **Per-tenant egress policy plane** — `sandbox/network_policy.py` is per-tool;
  add a per-tenant allow-list/proxy above sandboxes. Wake at first shared host.

**Strategic decisions (settled).** Recorded under [`docs/specs/`](./specs/):
*park* the learning substrate (revisit on a trajectory-volume tripwire); adopt
A2A's Agent Card and *cut* the homegrown ACD; *freeze breadth, invest in depth*
— re-home the ~47-connector tail to the plugin/registry tier with a deprecation
window.

**Accuracy caveats.** MCP Sampling / Roots / Logging appear to be on a deprecation
path — don't build on sampling. Some ecosystem dates/specs (mid-2026 MCP RC,
LangGraph 1.2, terminal-bench 2.0) postdate the original author's cutoff —
re-verify before committing. Vendor benchmark numbers are directional (contamination
/ single-run inflation) — run multi-seed.

> **2026 backlog (Q1–Q4): shipped.** The four 2026 quarters' capabilities, UX,
> performance, safety, and ecosystem items are built — see
> [`FEATURES.md`](./FEATURES.md). Their few genuine remainders are captured in
> "Still open" above; community/launch/marketing/localization items are
> founder-tracked, not code. The forward plan below picks up at the 2027 horizon.

### ✅ Shipped — 2027 H2 + 2028 build wave (June 2026)

A pull-forward pass built **every code-buildable item** across 2027 H2, 2028 H1,
and 2028 H2 — each module + test verified in-tree, each hot-path feature behind a
default-OFF flag or optional-dependency extra. Shipped via **#862** (merged),
**#869**, and **#887**. The items below have come off the quarter backlogs.

**2027 H2** — agent capability tools _(PR #869)_:

- [x] LaTeX render (math→MathML + doc→PDF) — `tools/latex_tool.py`
- [x] Diagramming (Graphviz / Mermaid) — `tools/diagram_tool.py`
- [x] Persistent task graph (dependency DAG, resumable) — `task_graph.py`
- [x] Browser auth vault (Fernet-encrypted sessions) — `browser_auth_vault.py`
- [x] HTML-to-app scaffolder — `html_to_app.py`
- [x] Notebook execution (sandboxed .ipynb) — `tools/notebook_exec.py`
- [x] Real-time WebSocket tool — `tools/websocket_tool.py`
- [x] Self-edit tool (human-gated, path-confined) — `tools/self_edit.py`
- [x] Browser device emulation (presets) — `browser_device.py`
- [x] Slack/Discord/**Teams** tool (completes the trio) — `tools/teams_tool.py`
- [x] Continuous-benchmarking tool — `continuous_benchmark.py`

**2028 H1** — platform / runtime _(PR #862, merged; latency-stats extended in #887)_:

- [x] Tool-output cache (memoize read-only tools) — `tool_cache.py` → `ToolRegistry.run`
- [x] Live-DOM diff — `dom_diff.py`
- [x] Phishing-content detector — `maverick_shield/phishing.py` → `Shield.scan_output`
- [x] License compliance scanner — `license_scan.py`
- [x] Replayable trace format — `replay_trace.py`
- [x] Per-tool latency stats (extended) — `tool_latency.extended_report()`
- [x] Network egress accounting — `egress_accounting.py` → `http_fetch`
- [x] Workspace snapshot / restore — `workspace_snapshot.py`
- [x] Cost split by tag — `cost_by_tag.py`
- [x] Run health score — `health_score.py`
- [x] Async tool invocation — _already shipped_ via MCP `TaskStore` (`maverick_mcp/tasks.py`)

**2028 H2** — runtime + introspection _(PR #887)_:

- [x] Zero-config BYO-tool (`@tool` decorator) — `tools/decorator.py`
- [x] Generic OIDC tool — `tools/oidc_tool.py`
- [x] Capability self-report tool — `tools/capability_query.py`
- [x] Provider-cost-curve fitter — `cost_curve_fitter.py`
- [x] Sub-second tool latency budget — `latency_budget.py` → `ToolRegistry.run`
- [x] Latency budget propagation across spans — `latency_span_budget.py`
- [x] Network sandbox (per-tool egress) — `sandbox/network_policy.py` → `http_fetch`
- [x] Energy-aware routing — `energy_aware_router.py`
- [x] Local-first default mode — `provider_local_first.py` → `llm.model_for_role`
- [x] Continuous-learning skill loop (local) — `skill_distillation_local.py`
- [x] Email channel v2 (IDLE + threading) — `maverick_channels/email_v2.py`

> **2027 H1 has no remaining code-buildable items** — its open entries are
> frontend/native-GUI, external-service, ML-training, or non-code (community/
> marketing). The remaining 2027 H2 / 2028 entries below are likewise blocked on a
> live service, real hardware/GPU, a trained model, a frontend/native surface, or
> are founder-tracked.

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

**Capabilities**: Multi-modal RAG; agent-to-agent debate over shared scratchpad; WASM sandbox; ROS robotics action tool; browser anti-bot evasion kit (opt-in); SQL agent tool (read-only by default); critic-agent template; cost-aware model router; multi-agent observation channel.

**UX**: Native macOS/Windows/Linux GUI apps; browser extension; voice persona presets; multi-language voice; wizard branching paths; inline cost preview; run gallery; replay export to MP4. Collaborative supervision (multi-user dashboard); approval delegation rules; trace pinning to commit; VS Code + JetBrains live-run extensions; TUI mouse mode; cost anomaly alerts; "why this cost" drill-down; run-as-tutorial export; accessibility audit pass; i18n community portal.

**Distribution**: macOS .app + DMG; Windows MSI; Linux AppImage; marketplace moderation tooling; sponsorship tiers; conference physical booth; swag store; ambassadors program; long-form handbook; Skill of the Year award. 2.0 RFC; backwards-compat tooling (`maverick migrate`); mobile companion app v1 (read-only); self-hosted relay reference; localized docs phase 4 (ko/ru/it/hi); video season 3; skill search engine (HF); annual community survey; foundation exploration.

**Performance**: Anthropic 1h extended cache adoption; token-level cost projection at plan time; compaction v4 structural diff; tool-call dedup cache; provider rate-limit predictor; latency-aware best-of-N (cancel slowest); distributed cache (Redis); cold-start optimization (<300ms `--help`); JIT consideration (mypyc/cython on hot path); reliability SLO publication (99.5%). Compaction v5 multi-modal; cross-run learning cache; autoscaling local backends; energy/CO2 accounting; real-time anomaly detection; failure-mode telemetry shipping (opt-in); tail-latency hunting; KV-cache offload to disk; provider migration cost calculator; 2-year retrospective.

**Safety**: Constitutional layer (NL profile rules → runtime classifier checks); refusal calibration; gVisor tool sandbox; eBPF syscall monitor; memory-safe parsers; supply-chain pinning; sigstore keyless signing; out-of-process model proxy; rate-limit shield calls per goal; public safety bulletin RSS. Federated shield model updates; model card per LLM; behavioral diff on upgrades; cross-run anomaly detection; honeytoken planting; tamper-evident screenshots; DSAR command; right-to-rectification; crash-only logging; annual safety report.

**Ecosystem**: ACD spec v1.0; AutoGen + CrewAI adapters; Threads + RCS channels; Anki integration; web archive tool; GitHub repo search; Redis world-model. Plugin telemetry opt-in; marketplace v2 (federated indexes); IDE protocol unification (one MCP server, multiple editors); run-events firehose (WebSocket); generic OAuth helper; DuckDB world-model; Cloudflare Workers + Modal sandboxes; plugin version-pinning lockfile.

---

## 2028 — H1

**Capabilities**: computer-use coordinate calibration; audio diarization + emotion; vision-grounded clicking; file-format converter (pandoc+ffmpeg+libreoffice); knowledge-graph builder; cron/scheduler tool. Multi-monitor computer-use; process introspection; hardware sensor tool; voice cloning consent gate; semantic code search; cross-repo dependency graph; test generation (Hypothesis); mutation testing; container build tool; streaming reasoning trace channel.

**UX**: Plan-tree minimap; conversational supervisor; voice-only mode; smart notification batching; mobile offline cache; augmented terminal (Rich inline charts); multi-tenant view; personalized starter templates; replay annotation export. AR plan-tree (visionOS); live captions voice; visual goal templates marketplace; "diff to expected"; smart goal completion; adaptive UI density; embedded analytics web component; pluggable themes API; voice macros; RTL language support.

**Distribution**: 2.0 stable release; migration playbook; marketplace v3 (donate-direct model); Maverick Summit v2 (hybrid); editor expansion (JetBrains/Neovim/Zed); localized docs phase 5 (top-15 langs + MT pipeline); "Built with Maverick" badge program; comparison benchmark v3 live dashboard; university curriculum kit; foundation paperwork submitted. ARM/RISC-V builds; iOS/Android skill execution (Pyodide/Kivy); skill + channel certification programs; community grants v1; regional meetup playbook; embeddable widget; hosted demo cluster (demo.maverick.dev); press push to major outlets; sponsor tier 2.

**Performance**: Speculative best-of-N (kill underperformers at first reasoning checkpoint); compaction v6 hybrid (learned classifier picks strategy); sub-ms dispatch overhead (msgspec/orjson); continuous profiling daemon (py-spy); cost-aware routing v3 (contextual bandits); sandbox pool (warm Docker/Firecracker, <100ms acquire); cache-aware prompt assembly DSL; SLA-breach automation; open metric standard. Multi-region failover; compaction v7 streaming; long-context cost guardrails (>$50/run gate); persistent KV-cache for local; online schema migrations; p999 latency campaign; cost-of-quality study; battery-mode for laptops; ML cache eviction (ARC/LeCaR).

**Safety**: Risk-tier auto-classifier (low/med/high goal scoring); containment mode (no-network ephemeral fs); capability negotiation protocol; cryptographic budget receipts; independent audit-log mirror; quorum approval for config changes; misuse leaderboard removal; safety steering group. Formal verification of sandbox interface (TLA+); capability-leak fuzzer; provenance chain across agents; multi-tenant isolation tests; right-to-explanation; bias eval suite; long-horizon goal review checkpoint; provider-level cost cap; backport security fixes; external SOC2 Type I.

**Ecosystem**: Plugin API v2 RFC; plugin compatibility matrix CI; multi-language plugin support (gRPC plugin host); TypeScript plugin SDK; generic SaaS-trigger framework; pgvector adapter; Apple Shortcuts integration; browser-extension chat. Plugin API v2 release; marketplace moderation tools; ACD interop tests; voice channel v2 (streaming ASR + barge-in); Discord slash-command framework; Slack workflow integration; Salesforce/HubSpot adapters; local-first embeddings cache (LMDB).

---

## 2028 — H2

**Capabilities**: WebRTC tool; browser extension bridge; ARIA-first navigation; adversarial self-test; sandbox-escape detector; embedded device tool (serial/JTAG/I2C); mixed-precision local inference; speculative decoding across providers; long-form writing (outline→draft→polish); citation verifier. Agent simulator harness; multi-agent fairness scheduler; WebGPU local vision; synthetic data tool; federated swarm protocol.

**UX**: "Director" mode (outcomes → plans → autonomy); cross-device handoff; predictive approvals; embedded video walkthroughs; granular redaction UI; conversation memory across runs; voice biometric unlock; power-user keymap editor; localized currency display. Unified inbox; smart NL filters; 3D plan-tree (WebGL/VR); self-healing UX; channel auto-routing; onboarding personalization v2; "achievements"; cost retrospective AI; universal share link; 36-month UX retrospective + reset.

**Distribution**: Maverick Conference v3 (in-person flagship); hackathon series; localized communities (top 5 non-English); skill marketplace federation; channel federation; public roadmap voting; press kit v2 + case studies; comparison benchmark v4 with reproducibility audits; handbook v2; "5-year vision" essay. Foundation hand-off; governance v2 launch (elected TSC); documentation rewrite; tutorial season 4; survey v3 + retrospective; sponsor renewal drive; HF Space spotlight; awards push; 2029 roadmap publication.

**Performance**: Self-tuning budgets (per-task-class learned defaults); compaction v8 graph-structured; zstd compression on world_model; critical-path-aware parallel scheduling; provider-side caching analytics; chaos game-day script; cost telemetry retention policy; real-time SSE dashboards; reliability harness 2.0. Cost/perf canary system per release; compaction v9 plug-in API; full OpenTelemetry semconv; 3-year retrospective benchmark; reliability cert; public perf SLA; sunset deprecated paths.

**Safety**: Shield v3 (small-model ensemble: injection + jailbreak + exfil + policy, explainable reason codes); provable redaction; differential erasure verification; air-gapped mode (full stack, no outbound); confidential-compute support (SEV-SNP/TDX); per-jurisdiction data residency; adversarial-prompt corpus release; AI Act conformance package; vuln reward expansion; third-party pen test. Federated audit-log verification; capability revocation propagation; key rotation playbook; PIA generator; safety regression budget; polyglot injection defense; consent ergonomics pass; 36-month safety retrospective; sunset policy; LTS safety branch (2-year support).

**Ecosystem**: Plugin signing CA; capability negotiation at swarm boot; gRPC API v1 stable; federated swarms over gRPC; KaTeX/Mermaid rich-render channel; Open Banking tool (Plaid/TrueLayer); HomeAssistant integration; MCP server publishing. Marketplace stats dashboard; plugin API v3 RFC (if warranted); ACD spec v1.1; multi-tenant `maverick serve`; channel SDK v2 (async-only); sandbox SDK v2; long-running plugin reliability suite; 3-year retrospective + 2029-2031 plan.

---

## Language Bindings — Council Decision (May 2026)

Three-perspective council pass on whether to ship Maverick in Rust /
TypeScript / Go / other languages. Research covered LangChain.js,
AutoGen .NET, CrewAI, Mastra, OpenAI/Anthropic SDKs.

### Conclusion

**Thin API clients port well; opinionated frameworks don't.** Maverick
is the second kind. We do **not** port `maverick-core` to a second
language. Instead we expose Maverick to other languages **over MCP**.
The MCP surface and the TypeScript / Go / Rust / C# / Java quickstarts
have shipped (see [`FEATURES.md`](./FEATURES.md)); what remains is the
measurement gate below.

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

The smallest concrete steps — polish the MCP server as the cross-language
surface and ship TS/Go/Rust/C#/JVM quickstarts — are **done**. The one open
step is **opt-in analytics on MCP-client language headers** (needs the
telemetry-consent UI). Then:

**Decision gate (Q1 2027):** if >15% of active installs are being
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

- **Self-hostable (no hosted dependency).** OpenClaw's bridge is a Cloudflare Worker — a
  hosted dependency. Ours ships with a "you can self-host this" path: the same thin
  shim runs either as a Worker **or** as a small local/edge service pointing at
  `POST /webhook/start`. No mandatory paid edge.
- **Config knob + wizard (CLAUDE.md #5/#6).** A new channel adapter gets a
  `[channels.glasses]` knob and an enable/disable step in the installer wizard
  (`apps/installer-cli/maverick_installer/wizard.py`).
- **The timeout split is the point.** The quick-vs-ack-then-run boundary is where the
  long-horizon design shows up on a 30-second device — keep it the headline of the
  demo, not an afterthought.

### Verify before committing

Device-side specifics (the ~30 s timeout, on-device STT behavior, HUD payload limits)
are third-party-reported — one community write-up plus Even's support center — and
should be re-checked against Even Realities' own G2 SDK before this becomes a build
commitment — the same caveat discipline as the **Accuracy caveats** under "Current
state" above.

**Sources:** [G2 × OpenClaw bridge write-up](https://blog.juchunko.com/en/even-realities-g2-openclaw-bridge/) ·
[Even Support Center — G2 "Bring Your Own Agent"](https://support.evenrealities.com/hc/en-us/categories/13489714076815-G2) ·
[bridge published as an OpenClaw Skill](https://mcpmarket.com/tools/skills/even-realities-g2-openclaw-bridge) ·
[prior art — openclaw-glasses for Even G1](https://github.com/littlebotshi/openclaw-glasses)

---

- **Track items**: each line is a candidate GitHub issue. Slice into smaller PRs as needed.
- **Re-prioritize**: items move freely. Anything in Q4 2028 can land sooner if a contributor wants to ship it. The quarter labels are guidance about scaling and team size, not constraints.
- **Cross-concern dependencies**: marked implicitly by quarter alignment. If you tackle a Q3 2027 capability item, expect related UX/safety items the same quarter to be useful as prerequisites.
- **Honest about scope**: each item should be sized at 1-2 weeks of one engineer's time. If something looks bigger when you start, slice it.
- **Self-host first**: the product runs in the customer's own environment; anything that would otherwise require a hosted service ships with a self-hostable path.
- **Shipped items live in [`FEATURES.md`](./FEATURES.md)** — when you close one here, move it there.
