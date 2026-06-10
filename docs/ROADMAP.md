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
| Postgres tenancy hardening | App-layer tenant isolation, **database-native Row-Level Security** (`[world_model] rls`; FORCE-RLS policy keyed on a `maverick.tenant` session GUC, validated under a non-superuser role) and a **`psycopg_pool` connection pool** (`[world_model] pool_size`) for horizontal scale have all shipped — see [`FEATURES.md`](./FEATURES.md). Remaining is operator runbook guidance (connect as a non-superuser role; apply RLS as the table owner). |
| Queue dispatch at scale (live-infra) | The `QueueDispatcher` (arq) is wired; remaining is running it against a real Redis broker + an out-of-process worker pool. |

### Strategic decisions (settled)

Recorded under [`docs/specs/`](./specs/): *park* the learning substrate
(revisit on a trajectory-volume tripwire); adopt A2A's Agent Card and *cut* the
homegrown ACD (this also resolves the former 'ACD spec v1.0/v1.1' roadmap
entries — never to be authored — and the interop tests shipped against A2A); *freeze breadth, invest in depth* — re-home the ~47-connector
tail to the plugin/registry tier with a deprecation window; *do not* compile
the hot path with mypyc/Cython (measured decision, revisit on an SLA breach —
see [`specs/jit-consideration.md`](./specs/jit-consideration.md)).

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
| **Capabilities** | — (cleared) |
| **UX** | visual graph editor · drag-and-drop goal builder |
| **Distribution** | tutorial video season 2 — (localized docs phases 2-3 (es/ja, de/fr/pt-BR): **shipped** — real human translations at [i18n/](./i18n/); university outreach, Maverick Summit v1, integration partnerships business half, GitHub Stars campaign, office hours: **program kits shipped**, see [programs/](./programs/) — running them is a maintainer act) |
| **Performance** | — (cleared) |
| **Safety** | — (cleared) |
| **Ecosystem** | — (cleared) |

---

## 2027 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | — (cleared: browser anti-bot evasion kit **declined** — its purpose is to defeat another operator's access control; the supported path is authorized/authenticated automation, see [`specs/anti-bot-evasion-decision.md`](./specs/anti-bot-evasion-decision.md)) |
| **UX** | Native macOS/Windows/Linux GUI apps |
| **Distribution** | Windows MSI · mobile companion app v1 (read-only) · video season 3 — (localized docs phase 4 (ko/ru/it/hi): **shipped** at [i18n/](./i18n/); sponsorship tiers, conference booth, swag store, ambassadors, Skill of the Year award, annual community survey, foundation exploration: **program kits shipped**, see [programs/](./programs/); the **long-form handbook shipped** at [handbook.md](./handbook.md)) |
| **Performance** | — (cleared: the 2-year retrospective is time-gated — its generators shipped (`benchmark_retrospective` for perf, `safety_report` for safety, `ux_retrospective` for usage); the operator runs them at the mark) |
| **Safety** | — (cleared) |
| **Ecosystem** | — (cleared: Redis primary store declined — see [`specs/redis-world-model-decision.md`](./specs/redis-world-model-decision.md); the Redis layers that fit shipped (tool cache, arq queue). DuckDB transactional backend declined — analytics layer shipped. **Modal sandbox backend shipped**; the Cloudflare-Workers half declined for shell semantics — Workers run JS/WASM, not processes; the Worker deployment story is the relay reference + `wasm_run`.) |

---

## 2028 — H1

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | — (cleared) |
| **UX** | AR plan-tree (visionOS) · embedded analytics web component · RTL language support — (mobile offline cache: **shipped** (`offline_bundle.py` + `GET /api/v1/offline/bundle`, consumed by `apps/mobile-companion/`); conversational supervisor, voice-only mode, augmented terminal (Rich inline charts), voice macros: **shipped** as library capabilities — see FEATURES; `maverick charts` wires the terminal charts) |
| **Distribution** | 2.0 stable release · migration playbook · marketplace v3 (donate-direct model) · Maverick Summit v2 (hybrid) · editor expansion (JetBrains/Neovim/Zed) · localized docs phase 5 (top-15 langs — the **MT pipeline shipped** (`maverick.docs_i18n`, quality-gated); the human es/ja/de/fr/pt-BR/ko/ru/it/hi set ships, the long tail rides the pipeline) · comparison benchmark v3 live dashboard · foundation paperwork submitted · ARM/RISC-V builds · iOS/Android skill execution (Pyodide/Kivy) · skill + channel certification programs · embeddable widget · hosted demo cluster (demo.maverick.dev) · press push to major outlets · sponsor tier 2 — ("Built with Maverick" badge program, university curriculum kit, community grants v1, regional meetup playbook: **program kits shipped**, see [programs/](./programs/)) |
| **Performance** | compaction v6 hybrid (learned classifier picks strategy) · sandbox pool (Firecracker-warm + cross-run pooling — warm Docker container reuse shipped) |
| **Safety** | — (cleared: the **Safety steering group charter shipped** ([`governance/safety-steering-group.md`](./governance/safety-steering-group.md) — remit, decision process, and the wiring to the shipped controls; staffing the seats is a company act). external SOC2 Type I: the repo-side readiness shipped ([`compliance/soc2-controls.md`](./compliance/soc2-controls.md) + `maverick.soc2` evidence collector); the attestation itself is an external audit. misuse leaderboard removal: verified absent — resolved) |
| **Ecosystem** | — (cleared: voice channel v2 — the streaming ASR + barge-in **session layer shipped** (`maverick_channels.streaming_voice`): partial/final endpointing on an injected clock, immediate barge-in halt with the interrupted reply preserved; the real streaming-ASR + playback adapters plug into its seams) |

---

## 2028 — H2

| Concern | Planned (not yet built) |
|---|---|
| **Capabilities** | — (cleared: **embedded device tool** (JTAG/I2C) shipped — `tools/embedded_device.py`, OpenOCD via sandbox + I2C over `[i2c]`, flash gated behind `[embedded] allow_flash`; **WebGPU local vision** shipped — `extensions/webgpu-vision/` WGSL primitives + the cross-language perceptual hash `perceptual_hash.py`) |
| **UX** | embedded video walkthroughs · 3D plan-tree (WebGL/VR) |
| **Distribution** | Maverick Conference v3 (in-person flagship) · hackathon series · localized communities (top 5 non-English) · skill marketplace federation · channel federation · public roadmap voting · comparison benchmark v4 with reproducibility audits · handbook v2 · "5-year vision" essay · foundation hand-off · governance v2 launch (elected TSC) · documentation rewrite · tutorial season 4 · survey v3 + retrospective · sponsor renewal drive · HF Space spotlight · awards push · 2029 roadmap publication — (press kit v2 + case studies: **shipped**, [programs/press-and-case-studies.md](./programs/press-and-case-studies.md) — deltas vs press-kit v1 + an evidence-gated case-study template) |
| **Performance** | — (cleared) |
| **Safety** | Shield v3 (trained small-model members + a policy member — the **ensemble framework + explainable reason codes shipped** with the heuristic injection/exfil/PII members, see FEATURES) · air-gapped mode runtime *enforcement* (the **preflight verification** `maverick airgap check` shipped — audits for remote providers / non-deny-all egress / sandbox network; see FEATURES) · confidential-compute support (SEV-SNP/TDX) — attestation + memory-encryption integration (the **detection/posture check** `maverick confidential-compute` shipped; needs the hardware for the rest) · third-party pen test · LTS safety branch — *cutting the branch* (the policy + SLA tooling shipped: docs/security-backports.md + maverick.backport_tool; the branch cut/push is a maintainer act) |
| **Ecosystem** | 3-year retrospective (time-gated: run `benchmark_retrospective` + the `safety_report` annuals at the 3-year mark — the 2029-2031 plan half shipped: [`ROADMAP-2029-2031.md`](./ROADMAP-2029-2031.md); the v3 RFC closed not-warranted: [`rfcs/0002-plugin-api-v3.md`](./rfcs/0002-plugin-api-v3.md)) |

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
