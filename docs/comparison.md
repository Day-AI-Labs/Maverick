# How Maverick compares

Where Maverick sits among agent frameworks and coding agents. This page
describes **Maverick's** capabilities precisely (each row links to the shipped
implementation in [`FEATURES.md`](./FEATURES.md)); for other tools it states
only their well-known positioning. Vendors move fast — **verify any competitor
specifics against their own current docs** before relying on them.

## What Maverick is

A **proprietary, self-hostable, governed agent platform**: a recursive
multi-agent kernel wrapped in an oversight/compliance/fleet control plane, on a
tenant-aware substrate. It targets enterprise/regulated teams that need an
auditable agent runtime in their own environment, and technical users who want
the deepest agent framework available.

## Positioning at a glance

> Category note: coding-agent runtimes (Hermes / OpenClaw / Cline / Aider)
> are a different layer — free or commodity agent loops. They appear here
> for orientation, not because they compete with an agentic enterprise
> platform; Maverick's competitive set is Agentforce, Copilot agents,
> Gemini Enterprise, and ServiceNow AI Agents.

| | Maverick | Devin | Hermes / OpenClaw | Cline / Aider |
|---|---|---|---|---|
| Primary form | Self-hosted platform + CLI | Hosted product | Coding agents | IDE / CLI coding agents |
| Prebuilt business specialists | **1,000 across 25 suites** (lint-audited envelopes) | No | No | No |
| Learns from use (governed) | **Yes** — consolidation, regression detection, rollback, signed learning audit | No | No | No |
| Runs in your environment | **Yes** (7 sandbox backends) | Hosted | Varies | Yes (local) |
| Multi-agent swarm | **Yes** (orchestrator + specialists) | Yes | Single-agent focus | Single-agent |
| Governance / compliance plane | **Yes** (oversight, regimes, audit, DSAR, SOC2) | Limited | No | No |
| Multi-tenant hosting | **Yes** (tenancy, KMS, egress, billing) | n/a (vendor-hosted) | No | No |
| Channels (chat/voice/etc.) | **14** | No | Some | No |
| Model choice | **User-owned, 12 providers** | Vendor | Varies | User keys |
| Safety chokepoint (shield) | **Input/tool/output** | Internal | Varies | No |
| License | Proprietary (lite edition TBD) | Proprietary | Mixed | Open source |

The cells under "Maverick" are grounded in shipped code; the other columns are
deliberately coarse to avoid asserting details that may be stale.

## Where Maverick is strongest

- **Governance you can prove.** Signed append-only audit log, compliance-regime
  packs (SOX/GAAP/PCI/GLBA/…), DSAR, SOC2 readiness, per-principal quotas, and
  an oversight console with "why this action" drill-down.
- **Self-host first.** Every capability that would otherwise need a hosted
  service ships with a self-hostable path (see the
  [reference architectures](./reference-architectures.md)).
- **Breadth on a governed core.** 500+ tools, 14 channels, 7 sandbox backends,
  12 LLM providers — all behind config knobs and the shield.
- **Long-horizon multi-agent work.** Planning topologies (tree-of-thought,
  debate, speculative, latency-aware best-of-N), durable resume, reflexion.

## Where another tool may fit better

- You want a **fully managed, zero-ops hosted** experience and don't need to
  self-host or audit the runtime → a hosted product may be simpler.
- You only want an **in-editor single-file coding assistant** with no platform
  → a lightweight IDE agent is less to run.

## Migrating in

Maverick consumes the wider ecosystem rather than replacing your tools: it
speaks **MCP** (as server and client), **A2A** (Agent Card), and ships
**LangChain/LangGraph** interop and **AutoGen/CrewAI** adapters, so existing
tools and agents plug in. Start with [`getting-started.md`](./getting-started.md).
