# Decision: freeze breadth, invest in depth — re-home the connector tail

**Status:** Decided — freeze breadth; re-home (don't delete) the 47-connector tail to the plugin/registry tier · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (the breadth-vs-depth call) · **Grounds in:** [`tool-inventory.md`](./tool-inventory.md) · **Date:** June 2026

## The question

The roadmap thesis is "the highest-value additions are **not** more breadth." The
tool inventory buckets the **103** tools in `maverick/tools/` into a **56-tool
differentiated core** (buckets 1–6: agent-internal, code/repo, system exec,
keyless research, media/doc, local data) and a **47-tool external-SaaS connector
tail** (bucket 7). Each connector independently tracks a third-party API
(auth/schema/rate-limit drift) and ships a credential path — recurring
maintenance **and** attack surface, with little differentiation (table-stakes
every agent offers). So: keep growing breadth, or freeze it and invest in depth?

## Decision

**Freeze breadth. Invest in depth.** Keep buckets 1–6 (56 tools) in the core.
**Re-home — not delete —** the 47-connector tail to the plugin/registry tier, now
that the discovery backbone exists. Tighten the default risk ceiling for the
consumer build using the inventory's risk tiers.

## Why

1. **The differentiation is depth, not connectors.** Maverick's edge is the
   long-horizon recursive swarm + the governed/provable runtime — not having a
   Salesforce tool nobody else has. The 47 connectors are table-stakes; carrying
   them in-core spends the scarcest resource (maintenance + security review) on
   the least-differentiated surface.
2. **The re-homing target now exists.** The inventory's recommendation hinged on
   "the plugin SDK + MCP **Registry** (roadmap B2) is the natural home." B2's
   **registry shipped this cycle** (`mcp_registry.py` +
   `maverick mcp-registry browse/add/remove/list` + `specs/mcp-registry.md`), so
   connectors can be discovered and installed on demand instead of bundled. The
   prerequisite that blocked this decision is cleared.
3. **It matches the commercial wedge.** The commercialization synthesis is
   explicit that the plan "deliberately does not clone OneTrust's breadth" — the
   surviving wedge is the self-hostable, provable, regulated runtime (depth).
   Breadth-as-pitch competes with everyone; depth is defensible.
4. **It shrinks the consumer attack surface.** The high-risk connectors (money:
   `stripe`/`plaid`/`shopify`; cloud-infra mutate/spend; send-as-user comms;
   `home_assistant`) are exactly the tail. Moving them out of the default build
   and behind explicit install + consent narrows what a non-technical consumer's
   default posture can do.

## Sequencing (so nothing regresses)

This is a **direction**, executed as sequenced work — not a cut to make today:

1. **Telemetry first (the one hard prerequisite).** Add opt-in, privacy-respecting
   tool-usage counts so the keep/cut call per connector is data-backed, not
   intuition. Do not cut before this exists.
2. **Registry/plugin tier — ✅ available.** B2 shipped; the plugin SDK
   ([`../plugins.md`](../plugins.md)) + MCP registry give connectors a home and a
   discovery surface.
3. **Migrate with a deprecation window.** Move connectors to the plugin tier
   behind a published deprecation window; keep them importable (with a warning)
   for that window so existing configs don't break. Per CLAUDE.md #5–#6 each
   already needs a config knob + wizard entry, which the plugin tier provides.
4. **Tighten the default risk ceiling.** Use the inventory's tiers to set the
   consumer default: high-risk tools off-by-default / consent-gated.

## Answers to the teed-up questions

- *Is "freeze breadth, invest in depth" the call, or is wide connector coverage
  part of the consumer pitch?* — **Freeze breadth.** Wide coverage is not the
  pitch; depth (long-horizon autonomy + governed runtime) is.
- *Ship the plugin tier + registry first, then migrate — deprecation window?* —
  **Yes, registry first (done).** A one-to-two-minor-release deprecation window for
  the connector re-home, gated on the telemetry data.
- *Telemetry acceptable for a privacy-positioned product?* — **Yes, if opt-in and
  privacy-respecting** (counts only, no payloads), consistent with the donation
  flywheel's opt-in posture. Without it, defer cuts rather than guess.

## What this decision does NOT do

It does not delete any tool, does not move any connector yet, and does not add
code. It sets the direction (freeze breadth; depth-first; re-home via the
registry) and the order of operations (telemetry → migrate → tighten defaults).
The migration itself is a separate, sequenced workstream.
