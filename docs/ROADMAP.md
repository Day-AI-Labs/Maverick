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

## Current state (June 2026, updated after the 2027-2028 build wave)

The original gap analysis is **done**. Pull-forward build waves have now run:
the first cleared the 2026 quarters; the second (June 10) drove the **2027-2028
tables themselves** — 140+ items shipped with tests, including the entire
2027-H1 Safety and Ecosystem rows; a continuing pass keeps clearing the
code-buildable tail across every horizon (recent: pgvector adapter,
LibreOffice office-doc converter, continuous profiling daemon, usage-ledger
retention, zstd cold-archive codec, smart notification batching, TrueLayer
open banking, gVisor sandbox, capability revocation propagation, MCP registry
publishing). Everything shipped is catalogued in [`FEATURES.md`](./FEATURES.md).

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
homegrown ACD (this also resolves the former 'ACD spec v1.0/v1.1' roadmap
entries — never to be authored — and the interop tests shipped against A2A); *freeze breadth, invest in depth* — re-home the ~47-connector
tail to the plugin/registry tier with a deprecation window.

### Accuracy caveats

MCP Sampling / Roots / Logging appear to be on a deprecation path — don't build
on sampling. Some ecosystem dates/specs (mid-2026 MCP RC, LangGraph 1.2,
terminal-bench 2.0) postdate the original author's cutoff — re-verify before
committing. Vendor benchmark numbers are directional (contamination /
single-run inflation) — run multi-seed.

> **What remains below is genuinely unbuilt**, and after the June-10 wave the
> remainder skews heavily toward items NO code change can complete:
> **live services** (real Redis broker, live IRC, a real G2 device),
> **hardware/GPU** (Watch/visionOS/AR, embedded JTAG, local-inference KV
> caches, WebGPU), **trained models** (CLAP audio, learned compaction
> summarizers, shield model ensembles), **native app surfaces** (macOS/
> Windows/Linux GUIs, mobile companion apps, MSI/ARM builds), **third-party
> processes** (external SOC2 Type I, third-party pen tests, sigstore CA
> onboarding), **founder-tracked business work** (summits, booths, swag,
> sponsorships, university partnerships, press pushes, surveys, awards,
> foundation paperwork, localization programs), and **the passage of time**
> (2-/3-year retrospectives, LTS support windows, annual reports). A thinner
> tail of ordinary code-buildable engineering also remains (e.g. DuckDB/Redis
> world-model backends, web-UI-heavy views, voice-runtime features); those
> are future-planned, not blocked.

---

## 2027 — H1

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Audio understanding (non-speech CLAP) · speech-to-action live-mic · image gen + edit tools · ASR meeting listener |
| **UX** | Mobile push v2 · Apple Watch glance · voice in channels v2 (Discord stages) · visual graph editor · drag-and-drop goal builder |
| **Distribution** | Localized docs phase 2 (es/ja) · tutorial video season 2 · university outreach (5 partnerships) · Maverick Summit v1 (virtual) · integration partnerships (business half; self-serve guide shipped) · browser extension v1 · localized docs phase 3 (de/fr/pt-BR) · GitHub Stars campaign · office hours |
| **Performance** | Public perf dashboard |
| **Safety** | — (cleared) |
| **Ecosystem** | — (cleared) |

---

## 2027 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Browser anti-bot evasion kit (opt-in) |
| **UX** | Native macOS/Windows/Linux GUI apps · browser extension · VS Code + JetBrains live-run extensions |
| **Distribution** | Windows MSI · sponsorship tiers · conference physical booth · swag store · ambassadors program · long-form handbook · Skill of the Year award · mobile companion app v1 (read-only) · localized docs phase 4 (ko/ru/it/hi) · video season 3 · annual community survey · foundation exploration |
| **Performance** | JIT consideration (mypyc/cython on hot path) · 2-year retrospective |
| **Safety** | eBPF syscall monitor · memory-safe parsers · sigstore keyless signing · federated shield model updates · annual safety report |
| **Ecosystem** | Redis world-model · DuckDB world-model *transactional backend* (declined — OLAP engine, wrong for the concurrent OLTP write path; the **DuckDB analytics layer** over the world model shipped instead, see FEATURES) · Cloudflare Workers + Modal sandboxes |

---

## 2028 — H1

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | Computer-use coordinate calibration · audio diarization + emotion · vision-grounded clicking · multi-monitor computer-use · hardware sensor tool |
| **UX** | Plan-tree minimap · conversational supervisor · voice-only mode · mobile offline cache · augmented terminal (Rich inline charts) · multi-tenant view · personalized starter templates · replay annotation export · AR plan-tree (visionOS) · live captions voice · visual goal templates marketplace · adaptive UI density · embedded analytics web component · pluggable themes API · voice macros · RTL language support |
| **Distribution** | 2.0 stable release · migration playbook · marketplace v3 (donate-direct model) · Maverick Summit v2 (hybrid) · editor expansion (JetBrains/Neovim/Zed) · localized docs phase 5 (top-15 langs + MT pipeline) · "Built with Maverick" badge program · comparison benchmark v3 live dashboard · university curriculum kit · foundation paperwork submitted · ARM/RISC-V builds · iOS/Android skill execution (Pyodide/Kivy) · skill + channel certification programs · community grants v1 · regional meetup playbook · embeddable widget · hosted demo cluster (demo.maverick.dev) · press push to major outlets · sponsor tier 2 |
| **Performance** | compaction v6 hybrid (learned classifier picks strategy) · sandbox pool (Firecracker-warm + cross-run pooling — warm Docker container reuse shipped) · cache-aware prompt assembly DSL |
| **Safety** | misuse leaderboard removal · safety steering group · formal verification of sandbox interface (TLA+) · backport security fixes · external SOC2 Type I |
| **Ecosystem** | Browser-extension chat · voice channel v2 (streaming ASR + barge-in) |

---

## 2028 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | WebRTC tool · browser extension bridge · ARIA-first navigation · embedded device tool (JTAG/I2C — serial shipped) · speculative decoding across providers · WebGPU local vision · federated swarm protocol |
| **UX** | "Director" mode (outcomes → plans → autonomy) · cross-device handoff · predictive approvals · embedded video walkthroughs · granular redaction UI · voice biometric unlock · power-user keymap editor · 3D plan-tree (WebGL/VR) · self-healing UX · channel auto-routing · onboarding personalization v2 · "achievements" · universal share link · 36-month UX retrospective + reset |
| **Distribution** | Maverick Conference v3 (in-person flagship) · hackathon series · localized communities (top 5 non-English) · skill marketplace federation · channel federation · public roadmap voting · press kit v2 + case studies · comparison benchmark v4 with reproducibility audits · handbook v2 · "5-year vision" essay · foundation hand-off · governance v2 launch (elected TSC) · documentation rewrite · tutorial season 4 · survey v3 + retrospective · sponsor renewal drive · HF Space spotlight · awards push · 2029 roadmap publication |
| **Performance** | Critical-path-aware parallel *scheduling* (the **critical-path analysis** shipped on `task_graph` — `op: critical`, the longest weighted dependency chain; the scheduler wiring remains) · provider-side caching analytics · 3-year retrospective benchmark · reliability cert · public perf SLA · sunset deprecated paths |
| **Safety** | Shield v3 (trained small-model members + a policy member — the **ensemble framework + explainable reason codes shipped** with the heuristic injection/exfil/PII members, see FEATURES) · air-gapped mode runtime *enforcement* (the **preflight verification** `maverick airgap check` shipped — audits for remote providers / non-deny-all egress / sandbox network; see FEATURES) · confidential-compute support (SEV-SNP/TDX) — attestation + memory-encryption integration (the **detection/posture check** `maverick confidential-compute` shipped; needs the hardware for the rest) · adversarial-prompt corpus release · AI Act conformance package · vuln reward expansion · third-party pen test · consent ergonomics pass · 36-month safety retrospective · sunset policy · LTS safety branch (2-year support) |
| **Ecosystem** | Plugin signing CA · capability negotiation at swarm boot · gRPC API v1 stable · federated swarms over gRPC · plugin API v3 RFC (if warranted) · long-running plugin reliability suite · 3-year retrospective + 2029-2031 plan |

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
