# How Lightwork compares

Where Lightwork sits among agent frameworks and coding agents. This page
describes **Lightwork's** capabilities precisely (each row links to the shipped
implementation in [`FEATURES.md`](./FEATURES.md)); for other tools it states
only their well-known positioning. Vendors move fast — **verify any competitor
specifics against their own current docs** before relying on them.

## What Lightwork is

A **proprietary, self-hostable, governed agent platform**: a recursive
multi-agent kernel wrapped in an oversight/compliance/fleet control plane, on a
tenant-aware substrate. It targets enterprise/regulated teams that need an
auditable agent runtime in their own environment, and technical users who want
the deepest agent framework available.

## Positioning at a glance

> Category note: coding-agent runtimes (Hermes / OpenClaw / Cline / Aider)
> are a different layer — free or commodity agent loops. They appear here
> for orientation, not because they compete with an agentic enterprise
> platform; Lightwork's competitive set is Agentforce, Copilot agents,
> Gemini Enterprise, and ServiceNow AI Agents.

| | Lightwork | Devin | Hermes / OpenClaw | Cline / Aider |
|---|---|---|---|---|
| Primary form | Self-hosted platform + CLI | Hosted product | Coding agents | IDE / CLI coding agents |
| Prebuilt business specialists | **2,020 across 53 suites** (lint-audited envelopes) | No | No | No |
| Primary-source data grounding | **Yes** — 37 read-only public-data connectors (SEC EDGAR, FRED, Treasury, Census, BLS, openFDA, CourtListener, ...) auto-granted per suite, on by default | No | No | No |
| Roster-wide governance invariants | **Yes** — 6 invariants (tool-reachability, autonomy dial, capability attenuation, compartment isolation, hard refusals, budget caps) verified across all 2,020 packs, fault-injected at 1M iterations | No | No | No |
| Learns from use (governed) | **Yes** — consolidation, regression detection, rollback, signed learning audit | No | No | No |
| Runs in your environment | **Yes** (9 sandbox backends) | Hosted | Varies | Yes (local) |
| Multi-agent swarm | **Yes** (orchestrator + specialists) | Yes | Single-agent focus | Single-agent |
| Governance / compliance plane | **Yes** (oversight, regimes, audit, DSAR, SOC2) | Limited | No | No |
| Multi-tenant hosting | **Yes** (tenancy, KMS, egress, billing) | n/a (vendor-hosted) | No | No |
| Channels (chat/voice/etc.) | **17** | No | Some | No |
| Model choice | **User-owned, 12 providers** | Vendor | Varies | User keys |
| Safety chokepoint (shield) | **Input/tool/output** | Internal | Varies | No |
| License | Proprietary (lite edition TBD) | Proprietary | Mixed | Open source |

The cells under "Lightwork" are grounded in shipped code; the other columns are
deliberately coarse to avoid asserting details that may be stale.

## Where Lightwork is strongest

- **Governance you can prove.** Signed append-only audit log, compliance-regime
  packs (SOX/GAAP/PCI/GLBA/…), DSAR, SOC2 readiness, per-principal quotas, and
  an oversight console with "why this action" drill-down.
- **Self-host first.** Every capability that would otherwise need a hosted
  service ships with a self-hostable path (see the
  [reference architectures](./reference-architectures.md)).
- **Breadth on a governed core.** 286 tool modules, 17 channels, 9 sandbox backends,
  12 LLM providers — all behind config knobs and the shield.
- **Long-horizon multi-agent work.** Planning topologies (tree-of-thought,
- **Provable governance at roster scale.** A governance invariant test suite
  verifies six invariants across all 2,020 packs — no drafting agent can reach
  a state-mutating tool, no onboarding/high-risk action is autonomous, a child
  capability can never exceed its parent, quarantine seals never bleed across
  compartments, the refusal floor is unstrippable, and no budget cap is
  silently exceeded — each fault-injected at 1,000,000 iterations with a
  non-vacuity control, plus hostile-argument fuzzing of every connector and tool.
  debate, speculative, latency-aware best-of-N), durable resume, reflexion.

## Where another tool may fit better

- You want a **fully managed, zero-ops hosted** experience and don't need to
  self-host or audit the runtime → a hosted product may be simpler.
- You only want an **in-editor single-file coding assistant** with no platform
  → a lightweight IDE agent is less to run.

## Migrating in

Lightwork consumes the wider ecosystem rather than replacing your tools: it
speaks **MCP** (as server and client), **A2A** (Agent Card), and ships
**LangChain/LangGraph** interop and **AutoGen/CrewAI** adapters, so existing
tools and agents plug in. Start with [`getting-started.md`](./getting-started.md).
