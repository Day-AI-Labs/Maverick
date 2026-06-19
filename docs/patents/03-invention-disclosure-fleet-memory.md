# Invention Disclosure 3 — Governed Shared-Memory Plane for Heterogeneous Third-Party Agents

> Not legal advice. Engineering disclosure prepared for patent counsel, 2026-06-19.
> Repo: `Day-AI-Labs/Maverick`. Public disclosure date (conservative): 2026-06-18.

## Administrative

- **Working title:** Governed shared learning-memory plane allowing heterogeneous
  third-party agents to read and write a common memory under provenance tagging,
  symmetric scope gating, and hard retrieval-layer isolation.
- **Inventors:** _[TO BE COMPLETED]_
- **Assignee:** _[Day AI Labs, Inc. — confirm]_
- **Public disclosure:** source public since ~2026-06-18.

## 1. Field

Multi-agent systems; shared/long-term agent memory; agent interoperability
(e.g., Model Context Protocol); data governance and access control for
retrieval-augmented systems; defense against memory poisoning.

## 2. The problem

Enterprises run agents from *different vendors* (e.g., one platform's agents plus
third-party agents). Letting them share a common, persistent learning memory
(so a lesson learned by one helps the others) raises governance problems that
existing RAG/memory systems don't solve together:

1. **Memory poisoning (write side).** An external agent could deposit adversarial
   "lessons" into a department it has no business writing to. Most access-control
   designs gate *reads* and under-protect *writes* — backwards, since writes are
   the higher-trust operation.
2. **Cross-tenant/department leakage (read side).** Ranking-based scoping (merely
   down-weighting out-of-scope hits) can still surface another department's data;
   and an agent could read across all departments simply by omitting a scope.
3. **Provenance.** When many heterogeneous agents contribute, downstream use must
   know *who/which vendor* authored each memory and how much to trust it.

## 3. Summary of the invention

A shared memory plane, exposed over an agent-interoperability protocol (e.g.,
MCP), that lets **registered heterogeneous third-party agents** ingest and recall
from a common learning store under a unified governance gate, with three
cooperating controls:

### 3.1 Symmetric scope gating — enforced on the WRITE path, not only reads
Both ingest and recall pass through the **same** access decision
(`decide_memory_access(agent_id, domain)`): the calling agent must be registered,
active, permitted for the direction (inbound/outbound), and its declared
`data_scopes` must include the requested `domain`. On **ingest** (the higher-trust
op), an external agent may deposit only into a scope its trust entry permits —
explicitly closing the memory-poisoning hole that read-only gating leaves open.

Evidence: `packages/maverick-core/maverick/fleet_memory.py:169-185` (write-path
gate; comment notes gating only reads was "backwards");
`packages/maverick-core/maverick/agent_trust.py:623-664` (`decide_memory_access`).

### 3.2 Hard retrieval-layer scope filtering (not a ranking penalty)
On recall, when the trust plane is engaged: an **empty/omitted domain is denied**
(prevents read-across-all by omission), and returned items are dropped by an
`_in_scope()` filter whose `domain != requested_domain` items are removed
**before** ranking can surface them — isolation is enforced at the retrieval
layer, not merely de-prioritized.

Evidence: `packages/maverick-core/maverick/fleet_memory.py:219-287` (recall;
unscoped-denied; `_in_scope` hard drop); `agent_trust.py:623-664`.

### 3.3 Provenance tagging + governed normalization of third-party contributions
Each external contribution is schema-validated, **secret-redacted**, shield-scanned,
size-capped, and persisted with a **provenance tag** (`source="{vendor}:{agent_id}"`,
trust tier) so it consolidates into the *same* offline learning loop as native
experience while remaining attributable and trust-weightable on later recall.
Unregistered agents are refused before any read/write; the whole plane is opt-in.

Evidence: `packages/maverick-core/maverick/fleet_memory.py:73-88` (redact +
shield + cap), `:142-217` (ingest with provenance), `:219-287` (recall with audit
of what was disclosed); MCP surface in
`packages/maverick-mcp/maverick_mcp/server.py:265-300`.

## 4. Why it is novel / non-obvious

- **Symmetric, write-side-first scope gating for a *shared* memory plane** used by
  **heterogeneous third-party** agents is the core inventive point. Typical RAG
  access control is read-centric and single-tenant; here the higher-trust write
  path is gated by the same scope decision, specifically as a memory-poisoning
  defense.
- **Hard retrieval-layer isolation with deny-on-unscoped** closes a subtle
  privilege-escalation (read-across by omitting scope) that ranking-based scoping
  leaves open.
- **Cross-vendor provenance feeding one consolidation loop** lets foreign agents'
  lessons improve the collective while staying attributable and trust-weighted —
  a governed interoperability memory, not just a shared database.

## 5. Draft claims (sketch for counsel — not final)

**Independent (system).** A system exposing a shared memory store to a plurality
of agents of different origins over an interoperability protocol, comprising
instructions to: maintain, for each agent, a registration record including
permitted data scopes and direction permissions; upon a request from an agent to
**write** an item associated with a domain, permit the write only if the agent is
registered and active and the domain is within the agent's permitted data scopes,
and otherwise refuse; upon a request to **read** for a domain, refuse the read if
no domain is specified while governance is engaged, and otherwise return only
items whose domain equals the requested domain by filtering non-matching items
prior to ranking; and store each written item with a provenance tag identifying
the contributing agent's origin and a trust level, such that written items are
consolidated into a common learning process shared across the plurality.

**Dependent (sketch).** ...wherein the same access-decision function gates both
read and write; ...wherein writing further comprises redacting secrets and
scanning content with an injection detector before persistence; ...wherein recall
records an audit entry of which items were disclosed to which agent;
...wherein provenance comprises a vendor identifier and per-source trust tier used
to weight or withhold items at recall; ...wherein an unregistered agent is refused
prior to any read or write; ...wherein the interoperability protocol is MCP and
the read/write are exposed as protocol tools.

## 6. Alternatives / variations

- Transport: MCP → A2A / REST / gRPC; "interoperability protocol" is the point.
- Scope model: department/domain → tenant / project / classification label.
- Filtering: exact-match → hierarchical scope (parent/child domains).
- Provenance: vendor:agent_id → signed attestations / verifiable credentials.
- Content controls: secret-redaction + shield → DLP / PII scan (see mvk-scan) /
  policy engine.
- Consolidation: offline "dream" loop → online incremental indexing.

## 7. Drawings to prepare

1. **Fig. 1** — heterogeneous agents (vendor A, vendor B, native) → MCP surface →
   shared memory plane.
2. **Fig. 2** — single access-decision function gating BOTH ingest and recall.
3. **Fig. 3** — ingest pipeline (registration check → scope gate → redact → shield
   → cap → provenance-tagged store).
4. **Fig. 4** — recall pipeline (deny-on-unscoped → retrieve → hard `_in_scope`
   drop → rank → disclosure audit).
5. **Fig. 5** — provenance-tagged items consolidating into the shared learning loop.

## 8. Evidence index (file:line)

- `packages/maverick-core/maverick/fleet_memory.py:73-88, 142-217, 169-185, 219-287`
- `packages/maverick-core/maverick/agent_trust.py:623-664` (`decide_memory_access`)
- `packages/maverick-mcp/maverick_mcp/server.py:265-300` (MCP read/write tools)
