# Press kit v2 + case-study template

**Roadmap ref:** 2028-H2 Distribution — "press kit v2 + case studies" (the
2028-H1 "press push to major outlets" runs on this kit).
**Status:** kit complete. The boilerplate below supersedes the counts in
[`docs/press-kit.md`](../press-kit.md) v1 (written when the catalogue
listed 14 channels); when adopted, a maintainer syncs that page to match.
Logos/assets and the press contact remain **maintainer placeholders** —
unchanged from v1, still true.

Standing rule, v1 and v2 alike: every count and capability claim on this
page is grounded in [`FEATURES.md`](../FEATURES.md), the catalogue of
shipped features. If a number here disagrees with `FEATURES.md`,
`FEATURES.md` wins and this page is the bug.

## Boilerplate v2 (verified against FEATURES.md)

Lightwork is a proprietary, commercially licensed agent runtime for
enterprises and regulated teams that need AI agents they can govern, audit,
and run entirely in their own environment. Hand it a goal and its
orchestrator decomposes the work and spawns specialist sub-agents —
researcher, coder, writer, verifier — that work in parallel under hard
dollar, wall-clock, and tool-call caps, with every input, tool call, and
output screened by the Agent Shield safety layer and every action recorded
in a signed, append-only audit log. The runtime is self-hosted — laptop,
Docker, VPS, Kubernetes, or air-gapped — and model-agnostic: 12 LLM
providers, routable per role, so customers pick the models. It ships 100+
built-in tools, 17 wired messaging/voice/wearable channels, and 9
selectable sandbox backends, runs as a multi-tenant platform (tenant
isolation, per-tenant encryption keys and egress policy, metering and
quotas), and can be driven from other languages over MCP and gRPC.
Lightwork is developed by Day AI Labs.

### 50-word version

Lightwork is a proprietary, self-hosted AI agent runtime for enterprises. A
recursive orchestrator spawns specialist sub-agents that work in parallel
under hard budget caps, behind a safety shield, with a signed audit log
and a multi-tenant control plane. 100+ tools, 17 channels, 9 sandbox
backends, 12 LLM providers.

### 25-word version

Unchanged from v1 (still accurate): Lightwork is a proprietary, self-hosted
multi-agent runtime for enterprises: a recursive swarm under hard budget
caps, a safety shield, and a signed, append-only audit log.

### Key-facts deltas vs. v1

| Fact | v1 said | v2 says (per `FEATURES.md`) |
|---|---|---|
| Channels | 14 | **17 wired** (adds WhatsApp Cloud API, Threads, RCS to the v1 set; IRC and the glasses/wearable adapter included) |
| Sandboxes | 7 | **9 selectable backends**: local subprocess, Docker, SSH, Podman, devcontainer, Firecracker, Kubernetes, plus Modal cloud sandboxes and a gVisor hardened-runtime Docker variant |
| Platform | (not stated) | Multi-tenant control plane: tenant lifecycle + quotas, per-tenant envelope encryption (KMS), per-tenant egress policy, metering → invoices |
| Interop | MCP + gRPC | MCP (server **and** client) + gRPC v1 (contract-gated) + A2A Agent Card + LangChain/AutoGen/CrewAI adapters |
| Everything else | — | v1 facts stand: proprietary license (lite edition a stated possibility, not a commitment); Python 3.10-3.12, 2000+ tests in CI; alpha, installable today; maker: Day AI Labs (Christopher Day) |

Naming/trademark rules: unchanged — see press kit v1 and
[`TRADEMARK.md`](../../TRADEMARK.md).

## Embargo / briefing checklist

For any pre-announcement briefing (release, partnership, case study):

- [ ] **Embargo terms in writing** before any material moves: date/time
      (UTC stated), what's covered, who's bound. No written acceptance =
      no briefing.
- [ ] **Briefing pack**: boilerplate above, the announcement draft, a
      fact sheet where every claim carries its grounding (a `FEATURES.md`
      anchor, a `RESULTS.md` measured row, or a quote owner) — reporters
      get the same evidence standard the repo holds itself to.
- [ ] **Demo**: live per the [booth-kit](./conference-booth.md) station
      rules (real install, budget-capped, fallback recording) or a
      published trace; never a staged screen.
- [ ] **Claims review**: someone who didn't write the draft checks every
      number against `FEATURES.md`/`RESULTS.md`; benchmark mentions
      carry the multi-seed caveat; competitor mentions follow the
      [`comparison.md`](../comparison.md) discipline (coarse, verify-with-
      vendor).
- [ ] **License clarity**: the proprietary position stated in the
      materials; "open source" corrected on sight, including in draft
      headlines; lite edition described only as a stated possibility.
- [ ] **Spokesperson named**; everyone else (including
      [ambassadors](./ambassadors.md)) routes inquiries to the press
      contact. Security topics: only what [`SECURITY.md`](../../SECURITY.md)
      and published advisories already say.
- [ ] **Day-of**: assets staged, links live at embargo lift, corrections
      contact monitored for 48h. Factual errors in coverage get one polite
      correction request with evidence; opinions get nothing.

## Case-study template

The bar is the showcase wall's, raised for commercial use: **no invented
customers, no composite customers, no anonymized vibes**. A case study
ships only when a real, named customer signs off and the evidence table is
fully populated. "Anonymous F500 company saves 80%" stories are
disqualified by construction.

### Structure (1-2 pages)

1. **Who** — customer name, industry, size band; named sign-off contact.
2. **The job** — what work the deployment does, in their words.
3. **The setup** — deployment shape (from the evidence table), which
   surfaces are load-bearing.
4. **What happened** — outcomes with the measurement stated for each
   (their measurement, their attribution, quoted not paraphrased).
5. **What didn't work** — at least one honest limitation or abandoned
   approach. A case study without this section reads as the ad it would
   be; this section is mandatory.
6. **Quote** — attributed by name and title.

### Evidence table (must be complete before drafting)

| Evidence | What qualifies | Filled in |
|---|---|---|
| Customer identity | Legal name + named contact who approves publication in writing | |
| License status | Active commercial/evaluation agreement with the Licensor (case studies are for licensed deployments, definitionally) | |
| Deployment shape | Self-reported: target (desktop/Docker/VPS/K8s/air-gapped), sandbox backend(s), providers/models in use, channels in use | |
| Scale & duration | Months in production; goals/period from their `maverick budget` / dashboard cost reporting, or stated as estimate | |
| Run evidence | A redacted trace/`maverick export`, **or** a written attestation naming what was demonstrated to us live — which one it was is stated in the study | |
| Outcome metrics | Customer-measured numbers with method ("measured by X over Y period"); we publish their attribution, never our extrapolation | |
| Safety/governance posture (if claimed) | Which controls are on (audit signing, capability enforcement, shield mode) — only if the study claims governance value | |
| Review trail | Customer-approved final text (dated); our claims check (dated, by whom) | |

### Process

Candidate (often via the showcase wall or a license engagement) → evidence
table populated → draft → customer legal/comms sign-off → our claims check
→ publish under `docs/` with the date and a revision note if ever amended.
Customers may withdraw; withdrawal removes the study within a week, no
argument. Until the first real one exists, the honest state is **zero case
studies published** — and this kit waits, populated template and all.
