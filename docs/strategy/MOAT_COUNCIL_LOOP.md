# Maverick Moat Council Loop — living document

> Orchestrated adversarial deliberation to drive the codebase to **$20M+ standalone
> value**, strong inbound customer demand, and acquisition interest. "Beyond the
> bleeding edge." Max effort. This file is the durable state across all rounds.

## North Star (the bar)
- Codebase independently worth **$20M+** (replacement cost + IP + compounding assets — see acquihire/build research already on file: build-from-scratch $1.25–2.5M, agency $0.65–0.9M, so $20M demands a *category-defining moat + IP + traction*, not more features).
- **Inbound demand** — customers banging the door down.
- **Acquisition interest** — companies trying to buy.

## Loop protocol
Each round: **Adversarial council → Idea-Generator council → Validator council**, then the
next round's Adversarial council reacts to the prior Validator output. **5 rounds.**
Every council is a research-backed multi-member panel. Between councils the orchestrator
(Claude) synthesizes into this doc: surviving ideas, unresolved attacks, rising value thesis.

- **Adversarial council** — CISO buyer, rival AI-infra founder, VC who passed, M&A technical-diligence lead, regulator. Job: why this is NOT worth $20M; why customers won't come; fatal flaws; what competitors already do better. Evidence + sources required.
- **Idea-Generator council** — frontier-AI researcher, cryptographer/ZK, distributed-systems architect, category-design strategist, contrarian inventor. Job: beyond-bleeding-edge, hard-to-replicate capabilities that neutralize the attacks and compound. SOTA research required.
- **Validator council** — staff engineer (feasibility/effort), patent attorney (defensibility/IP), market analyst (WTP/comps), design-partner/buyer proxy. Job: score each idea (feasibility, replacement cost, moat strength, demand impact, time-to-value), greenlight/kill, ground in comps.

## Seed state (v0)

**What Maverick is:** proprietary governed, self-improving AI-workforce enterprise platform.
Kernel (`maverick-core`) + optional shield + channels + dashboard + MCP + evolve + knowledge.
Thesis: **compete on governance + provable learning, never the commodity runtime.**

**Shipped assets (verified in code):**
- Governed kernel; budget caps, quotas, provider cost caps, **cluster-wide killswitch**.
- Multi-tenant world model (Postgres+SQLite), **row-level security + per-request tenant pinning**.
- Tamper-evident audit: **Ed25519-signed, hash-chained** event log; **off-host/KMS-custody signing**; **proof-pack manifest verifier** (independently verifiable provenance).
- Closed learning lifecycle: dreaming/hindsight/proof, **snapshot+rollback**, **signed learning audit**; **fleet memory**; the **Operating Record**.
- **Agent Trust Plane** (signed agent identity, narrow-only capability negotiation) + cross-swarm **federation** (gRPC, signed delegation).
- **1,118 specialist packs / 26 suites**; marketplace + **signed catalog federation**; plugin SDK (allowlisted, no silent exec).
- **Signed, fail-closed shield rule updates** (push policy to fleets w/o redeploy).
- Compliance reporting: SOC2/HIPAA/GDPR/EU-AI-Act/DPIA/ROPA; deployment verification; sandbox; canary.
- Distribution: PyPI, Docker/ghcr, Homebrew, signed binaries, desktop installers, TS SDK; Sigstore + SBOM.

**Current strategy hypotheses (to be attacked & improved):**
- M1 Proof-of-Improvement (verifiable learning) · M2 Privacy-preserving fleet learning ·
  M3 Agent Trust Fabric (inter-org agent PKI) · M4 Certified compliance + portable Operating Record
- V1 Deterministic replay + counterfactual forensics · V2 Provable safety envelope · V3 Patent crypto-governance
- D1 Killer demo (replay→evidence→killswitch→proof) · D2 OSS funnel + pack marketplace · D3 Publish research to recruit

## Scoreboard
| Idea | Moat | Replacement cost | Demand | Feasibility | Status |
|---|---|---|---|---|---|
| _(populated by Validator councils)_ | | | | | |

## Open adversarial attacks (unresolved)
_(none yet)_

## Validated / greenlit
_(none yet)_

## Killed / parked
_(none yet)_

---
# ROUND LOG
_(each round appended below)_
