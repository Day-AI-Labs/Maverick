# Maverick Roadmap (Q1 2026 → Q4 2028)

Produced by a 6-agent council pass across six concerns: **capabilities, UX,
distribution, performance, safety, ecosystem**. Each line is sized for ~1-2
weeks of one engineer's work.

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

This roadmap is the **forward backlog — what isn't built yet.** The moment an
item ships it comes *off* this list and into [`FEATURES.md`](./FEATURES.md),
the catalogue of built features and tools. Nothing should appear in both. So
if something you remember seeing here is gone, it shipped — check
`FEATURES.md`.

## Current state (June 2026)

The original gap analysis is **done**, along with a large
governed-agent-runtime surface and a pull-forward build wave that cleared every
code-buildable item across the 2026 quarters and the 2027 H2 / 2028 waves. All
of it is catalogued in [`FEATURES.md`](./FEATURES.md).

**This is now a governed agent _platform_, not just a local kernel.** The
three-layer control plane is real — oversight (`governance.py`),
compliance-regime engine, per-employee fleets (`fleet.py`) — on a tenant-aware
substrate (`workspace.py` walls each tenant into `~/.maverick/tenants/<t>/`;
the world model keeps a per-tenant DB; `data_dir()` routes
audit/quotas/dsar/soc2/fleet; `quotas.py` enforces per-principal spend caps;
OIDC + `[roles.<role>]` RBAC gate access). The forward backlog is organised
around **finishing the platform spine** and the 2027–2028 horizons below.

### Still open — near-term engineering

The cross-language MCP surface, the IRC / glasses-wearable / LangChain
connectors, the MCP elicitation URL-mode path, and the multi-tenant hosting
spine (Postgres tenancy, queue dispatch, tenant lifecycle, billing, per-tenant
KMS + egress, operator console) have **shipped** — see
[`FEATURES.md`](./FEATURES.md). What genuinely remains is non-code or live-infra:

| Item | Remaining work |
|---|---|
| Language-bindings decision (Q1 2027 gate) | A *measurement*, not code: the consent-gated MCP-client language analytics that feeds it has shipped; fund a native client only if >15% of active installs drive Maverick from non-Python MCP clients (see council decision below). |
| Live-service validation | The connectors + queue/KMS backends ship with their protocol/logic unit-tested; end-to-end validation against a live IRC server, a real G2 device, a langchain install, and a Redis broker is the remaining gate, not new code. |
| Postgres tenancy hardening (live-infra) | App-layer tenant isolation (strict-isolation mode) is shipped; remaining is database-native Row-Level Security + a `psycopg_pool` connection pool for horizontal scale. |
| Queue dispatch at scale (live-infra) | The `QueueDispatcher` (arq) is wired; remaining is running it against a real Redis broker + an out-of-process worker pool. |

### Strategic decisions (settled)

Recorded under [`docs/specs/`](./specs/): *park* the learning substrate
(revisit on a trajectory-volume tripwire); adopt A2A's Agent Card and *cut* the
homegrown ACD; *freeze breadth, invest in depth* — re-home the ~47-connector
tail to the plugin/registry tier with a deprecation window.

### Accuracy caveats

MCP Sampling / Roots / Logging appear to be on a deprecation path — don't build
on sampling. Some ecosystem dates/specs (mid-2026 MCP RC, LangGraph 1.2,
terminal-bench 2.0) postdate the original author's cutoff — re-verify before
committing. Vendor benchmark numbers are directional (contamination /
single-run inflation) — run multi-seed.

> **2026 quarters and the 2027 H2 / 2028 build wave are shipped** — their
> code-buildable items are in [`FEATURES.md`](./FEATURES.md). What remains
> below is genuinely unbuilt. Much of it is blocked on a live service, real
> hardware/GPU, a trained model, a frontend/native surface, or is
> founder-tracked (community / launch / marketing / localization) — but not
> all of it: the tables still hold ordinary code-buildable engineering items.
> Those are future-planned, not blocked.

---

## 2027 — H1

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Audio understanding (non-speech CLAP) · cross-language LSP bridge · speculative parallel tool calls · speech-to-action live-mic · image gen + edit tools · ASR meeting listener · auto-skill distillation v2 |
| **UX** | Multi-run dashboard · pinned watch list · annotated traces · mobile push v2 · Apple Watch glance · voice in channels v2 (Discord stages) · high-contrast & dyslexic fonts · i18n expansion (fr/de/ja/zh) · visual graph editor · saved dashboard views · channel reply threading · drag-and-drop goal builder · plain-language explanations |
| **Distribution** | Localized docs phase 2 (es/ja) · reproducible benchmark v2 (terminal-bench, weblinx, HumanEval-fix) · marketplaces v2 with ratings · tutorial video season 2 · university outreach (5 partnerships) · skill validator service · comparison page · press kit · devcontainer + Codespaces template · Maverick Summit v1 (virtual) · showcase wall · integration partnerships (LangSmith/Helicone/OpenRouter) · reference architectures (k8s/ECS/Fly.io/Railway) · browser extension v1 · skill + channel template generators · localized docs phase 3 (de/fr/pt-BR) · GitHub Stars campaign · office hours |
| **Performance** | Tiered storage (hot SQLite + cold parquet) · query plan regression CI · async compaction · cost-aware router v2 (per-role policies) · streaming tool_result · Sentry performance tab · provider failover policy engine · adversarial-cost benchmark suite · continuous batching local · compaction v3 learned summarizer · speculative tool execution · gRPC dispatch · WAL contention audit (N=16) · cache-warm-on-start · memory-leak quarantine · cost-attribution API · public perf dashboard |
| **Safety** | shield calibration dashboard · image-content classifier · voice safety pass · red-team CI |
| **Ecosystem** | Marketplace ratings + install verification · Emacs integration · WhatsApp Cloud API rewrite · plugin sandboxing (subinterpreter) · hot plugin reload · Vim/Neovim plugin · GitHub + GitLab Issues integrations · S3-backed attachments |

---

## 2027 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Multi-modal RAG · WASM sandbox · ROS robotics action tool · browser anti-bot evasion kit (opt-in) · multi-agent observation channel |
| **UX** | Native macOS/Windows/Linux GUI apps · browser extension · voice persona presets · multi-language voice · wizard branching paths · inline cost preview · run gallery · replay export to MP4 · collaborative supervision (multi-user dashboard) · trace pinning to commit · VS Code + JetBrains live-run extensions · TUI mouse mode · cost anomaly alerts · "why this cost" drill-down · run-as-tutorial export · accessibility audit pass · i18n community portal |
| **Distribution** | Windows MSI · marketplace moderation tooling · sponsorship tiers · conference physical booth · swag store · ambassadors program · long-form handbook · Skill of the Year award · 2.0 RFC · backwards-compat tooling (`maverick migrate`) · mobile companion app v1 (read-only) · self-hosted relay reference · localized docs phase 4 (ko/ru/it/hi) · video season 3 · skill search engine (HF) · annual community survey · foundation exploration |
| **Performance** | Token-level cost projection at plan time · compaction v4 structural diff · distributed cache (Redis) · cold-start optimization (<300ms `--help`) · JIT consideration (mypyc/cython on hot path) · reliability SLO publication (99.5%) · compaction v5 multi-modal · cross-run learning cache · autoscaling local backends · energy/CO2 accounting · real-time anomaly detection · failure-mode telemetry shipping (opt-in) · tail-latency hunting · KV-cache offload to disk · provider migration cost calculator · 2-year retrospective |
| **Safety** | Refusal calibration · gVisor tool sandbox · eBPF syscall monitor · memory-safe parsers · supply-chain pinning · sigstore keyless signing · out-of-process model proxy · rate-limit shield calls per goal · public safety bulletin RSS · federated shield model updates · model card per LLM · behavioral diff on upgrades · cross-run anomaly detection · honeytoken planting · tamper-evident screenshots · right-to-rectification · crash-only logging · annual safety report |
| **Ecosystem** | ACD spec v1.0 · AutoGen + CrewAI adapters · Threads + RCS channels · Anki integration · web archive tool · GitHub repo search · Redis world-model · plugin telemetry opt-in · marketplace v2 (federated indexes) · IDE protocol unification (one MCP server, multiple editors) · run-events firehose (WebSocket) · generic OAuth helper · DuckDB world-model · Cloudflare Workers + Modal sandboxes · plugin version-pinning lockfile |

---

## 2028 — H1

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Computer-use coordinate calibration · audio diarization + emotion · vision-grounded clicking · office-doc converter (libreoffice) · multi-monitor computer-use · process introspection · hardware sensor tool · voice cloning consent gate · streaming reasoning trace channel |
| **UX** | Plan-tree minimap · conversational supervisor · voice-only mode · smart notification batching · mobile offline cache · augmented terminal (Rich inline charts) · multi-tenant view · personalized starter templates · replay annotation export · AR plan-tree (visionOS) · live captions voice · visual goal templates marketplace · "diff to expected" · smart goal completion · adaptive UI density · embedded analytics web component · pluggable themes API · voice macros · RTL language support |
| **Distribution** | 2.0 stable release · migration playbook · marketplace v3 (donate-direct model) · Maverick Summit v2 (hybrid) · editor expansion (JetBrains/Neovim/Zed) · localized docs phase 5 (top-15 langs + MT pipeline) · "Built with Maverick" badge program · comparison benchmark v3 live dashboard · university curriculum kit · foundation paperwork submitted · ARM/RISC-V builds · iOS/Android skill execution (Pyodide/Kivy) · skill + channel certification programs · community grants v1 · regional meetup playbook · embeddable widget · hosted demo cluster (demo.maverick.dev) · press push to major outlets · sponsor tier 2 |
| **Performance** | Speculative best-of-N (kill underperformers at first reasoning checkpoint) · compaction v6 hybrid (learned classifier picks strategy) · sub-ms dispatch overhead (msgspec/orjson) · continuous profiling daemon (py-spy) · cost-aware routing v3 (contextual bandits) · sandbox pool (warm Docker/Firecracker, <100ms acquire) · cache-aware prompt assembly DSL · SLA-breach automation · open metric standard · multi-region failover · compaction v7 streaming · long-context cost guardrails (>$50/run gate) · persistent KV-cache for local · online schema migrations · p999 latency campaign · cost-of-quality study · ML cache eviction (ARC/LeCaR) |
| **Safety** | Risk-tier auto-classifier (low/med/high goal scoring) · containment mode (no-network ephemeral fs) · capability negotiation protocol · cryptographic budget receipts · independent audit-log mirror · quorum approval for config changes · misuse leaderboard removal · safety steering group · formal verification of sandbox interface (TLA+) · capability-leak fuzzer · provenance chain across agents · multi-tenant isolation tests · right-to-explanation · bias eval suite · long-horizon goal review checkpoint · provider-level cost cap · backport security fixes · external SOC2 Type I |
| **Ecosystem** | Plugin API v2 RFC · plugin compatibility matrix CI · multi-language plugin support (gRPC plugin host) · TypeScript plugin SDK · generic SaaS-trigger framework · pgvector adapter · Apple Shortcuts integration · browser-extension chat · plugin API v2 release · marketplace moderation tools · ACD interop tests · voice channel v2 (streaming ASR + barge-in) · Discord slash-command framework · Slack workflow integration · local-first embeddings cache (LMDB) |

---

## 2028 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | WebRTC tool · browser extension bridge · ARIA-first navigation · adversarial self-test · embedded device tool (serial/JTAG/I2C) · mixed-precision local inference · speculative decoding across providers · long-form writing (outline→draft→polish) · agent simulator harness · multi-agent fairness scheduler · WebGPU local vision · federated swarm protocol |
| **UX** | "Director" mode (outcomes → plans → autonomy) · cross-device handoff · predictive approvals · embedded video walkthroughs · granular redaction UI · voice biometric unlock · power-user keymap editor · localized currency display · unified inbox · smart NL filters · 3D plan-tree (WebGL/VR) · self-healing UX · channel auto-routing · onboarding personalization v2 · "achievements" · cost retrospective AI · universal share link · 36-month UX retrospective + reset |
| **Distribution** | Maverick Conference v3 (in-person flagship) · hackathon series · localized communities (top 5 non-English) · skill marketplace federation · channel federation · public roadmap voting · press kit v2 + case studies · comparison benchmark v4 with reproducibility audits · handbook v2 · "5-year vision" essay · foundation hand-off · governance v2 launch (elected TSC) · documentation rewrite · tutorial season 4 · survey v3 + retrospective · sponsor renewal drive · HF Space spotlight · awards push · 2029 roadmap publication |
| **Performance** | Self-tuning budgets (per-task-class learned defaults) · compaction v8 graph-structured · zstd compression on world_model · critical-path-aware parallel scheduling · provider-side caching analytics · chaos game-day script · cost telemetry retention policy · real-time SSE dashboards · reliability harness 2.0 · cost/perf canary system per release · compaction v9 plug-in API · full OpenTelemetry semconv · 3-year retrospective benchmark · reliability cert · public perf SLA · sunset deprecated paths |
| **Safety** | Shield v3 (small-model ensemble: injection + jailbreak + exfil + policy, explainable reason codes) · provable redaction · differential erasure verification · air-gapped mode (full stack, no outbound) · confidential-compute support (SEV-SNP/TDX) · per-jurisdiction data residency · adversarial-prompt corpus release · AI Act conformance package · vuln reward expansion · third-party pen test · federated audit-log verification · capability revocation propagation · key rotation playbook · PIA generator · safety regression budget · polyglot injection defense · consent ergonomics pass · 36-month safety retrospective · sunset policy · LTS safety branch (2-year support) |
| **Ecosystem** | Plugin signing CA · capability negotiation at swarm boot · gRPC API v1 stable · federated swarms over gRPC · KaTeX/Mermaid rich-render channel · Open Banking tool (TrueLayer) · MCP server publishing · marketplace stats dashboard · plugin API v3 RFC (if warranted) · ACD spec v1.1 · multi-tenant `maverick serve` · channel SDK v2 (async-only) · sandbox SDK v2 · long-running plugin reliability suite · 3-year retrospective + 2029-2031 plan |

---

## Language Bindings — Council Decision (May 2026)

Three-perspective council pass on whether to ship Maverick in Rust /
TypeScript / Go / other languages. Research covered LangChain.js,
AutoGen .NET, CrewAI, Mastra, OpenAI/Anthropic SDKs.

### Conclusion

**Thin API clients port well; opinionated frameworks don't.** Maverick is the
second kind. We do **not** port `maverick-core` to a second language. Instead
we expose Maverick to other languages **over MCP** — the MCP surface and the
TypeScript / Go / Rust / C# / Java quickstarts are shipped (see
[`FEATURES.md`](./FEATURES.md)). What remains is the measurement gate below.

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

The cross-language surface (MCP server + TS/Go/Rust/C#/JVM quickstarts) is
built, and the **opt-in analytics on MCP-client language headers** ship with
their telemetry-consent step in the installer wizard (`maverick init` →
Analytics; off by default). What remains is letting opt-in install-base data
accumulate. Then:

**Decision gate (Q1 2027):** if >15% of active installs are being driven from
non-Python MCP clients, fund **one** thin `@maverick/client` TypeScript package
(RPC wrapper, ~2k LOC, Stainless-generated where possible). Under 15%, the
answer is the MCP surface, full stop.

### Hard constraints

- No port of `maverick-core` to a second language ever — that's a permanent
  ~40% team-headcount tax that LangChain.js shows still doesn't yield parity.
- Sandbox backends (firecracker, k8s, devcontainer, podman) stay Linux-process
  glue in Python; they are not part of the cross-language contract.
- Multi-agent topology (orchestrator + proposer + verifier + revisor +
  reflector) stays Python. Other languages drive Maverick; they do not
  re-implement it.

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
commitment — the same caveat discipline as the **Accuracy caveats** above.

**Sources:** [G2 × OpenClaw bridge write-up](https://blog.juchunko.com/en/even-realities-g2-openclaw-bridge/) ·
[Even Support Center — G2 "Bring Your Own Agent"](https://support.evenrealities.com/hc/en-us/categories/13489714076815-G2) ·
[bridge published as an OpenClaw Skill](https://mcpmarket.com/tools/skills/even-realities-g2-openclaw-bridge) ·
[prior art — openclaw-glasses for Even G1](https://github.com/littlebotshi/openclaw-glasses)

---

## Working notes

- **Track items**: each cell entry is a candidate GitHub issue. Slice into smaller PRs as needed.
- **Re-prioritize**: items move freely. Anything in 2028 can land sooner if a contributor wants to ship it. The horizon labels are guidance about scaling and team size, not constraints.
- **Honest about scope**: each item should be sized at 1-2 weeks of one engineer's time. If something looks bigger when you start, slice it.
- **Self-host first**: the product runs in the customer's own environment; anything that would otherwise require a hosted service ships with a self-hostable path.
- **Shipped items live in [`FEATURES.md`](./FEATURES.md)** — when you close one here, delete it from this doc and add it there. Nothing belongs in both.
