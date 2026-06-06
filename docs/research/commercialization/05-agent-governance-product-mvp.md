# Agent-Governance Product — MVP Spec & Scope Teardown

> Workstream 05 of the commercialization teardown. Date: 2026-06-06.
> Premise (from [`../regulated-deployment-and-compliance-platform.md`](../regulated-deployment-and-compliance-platform.md)):
> the wedge is **agent governance** — a category no GRC incumbent owns. This
> doc specs the MVP, separates cheap *projection* of data Maverick already
> emits from expensive *net-new* build, and answers the make-or-break TAM
> question: can it govern **non-Maverick** agents?

## Bottom line

The MVP is an **AI/agent-governance system of record + runtime control plane**:
(1) a **registry** of every agent/model/tool (owner, purpose, risk tier,
capabilities, data access, lifecycle); (2) **runtime policy enforcement** —
already shipped as `capability.py` + `safety/tool_acl.py` + `safety/consent.py`;
(3) **framework-mapped evidence** projected from the tamper-evident audit chain
(`audit/signing.py`). **~60% of the MVP is a projection of data Maverick already
emits** — registry, evidence export, and the "where are my agents" dashboard are
read-models over the capability graph, tool registry, world model, and signed
NDJSON. The genuinely net-new build is narrow: a **control catalog + mapping
table**, an **evidence projector/renderer**, **SSO/SCIM** (the same P0 the prior
analysis flagged), and — the strategic bet — a **third-party ingestion adapter**.

The single thing that decides whether this is a company or a feature: **it must
govern third-party agents (LangGraph, CrewAI, OpenAI Assistants, MCP servers),
not just Maverick's own swarm.** If it only governs Maverick agents, the TAM is
the Maverick install base — tiny. We already have the two integration vectors in
tree (OTel span export in `observability.py`; MCP introspection in
`mcp_client.py`), so this is reachable in the 90-day window as a **read-only
observe-and-attest** plane, with enforcement on third parties deferred.

## MVP spec — three planes

### 1. Registry (system of record) — *mostly projection + thin net-new schema*

One inventory row per **agent**, **model**, and **tool/MCP server**. Fields:
`owner`, `purpose`, `risk_tier` (EU AI Act × NIST AI RMF tier), `capabilities`
(from `Capability.allow_tools`/`max_risk`), `data_access` (which connectors/MCP
servers/sandboxes it can reach), `lifecycle_state` (proposed → approved →
production → retired), `framework_tags`, `last_seen`.

- **Maverick agents auto-populate**: the registry is a read-model over the
  capability graph (`capability_from_config`, the attenuation tree), the tool
  registry (`tools/__init__.py`), MCP server specs (`MCPServerSpec`), and goal/
  episode rows in `world_model.py` (already SQLite + FTS5 + schema-versioned).
- **Net-new**: a `registry` table (owner/purpose/risk_tier/lifecycle are human-
  or policy-assigned metadata that doesn't exist today), an approval/lifecycle
  state machine (reuse the `approvals` table + consent queue), and the dashboard
  surface. Risk-tier *defaults* can be derived from `tool_risk` + data sensitivity.

### 2. Runtime policy enforcement — *100% reuse, zero net-new for Maverick agents*

Already shipped, opt-in, fail-open:
- **Least privilege / identity** → `capability.py` (signed, attenuating; child ≤ parent).
- **Tool RBAC + risk ceiling** → `safety/tool_acl.py` (global/channel/user, `max_risk`).
- **Human oversight / HITL** → `safety/consent.py` (ledger + dashboard approval queue).
- **Kill-switch** → `killswitch.py`.
The MVP's job is to **expose and report** these as governed controls, not rebuild
them. Net-new is only **policy-as-code framework tags** on each rule (the Q1→Q2
bridge the prior analysis names).

### 3. Framework-mapped evidence — *projection of the signed audit chain*

The audit chain (`audit/events.py` → `audit/writer.py` → `audit/signing.py`)
already emits attributable, scoped, tamper-evident, signed events
(`tool_call`, `capability_denied`, `consent_prompt/result`, `secret_redacted`,
`erase`, `halt`). The product is a **projector** that filters/maps these into
per-control evidence packs and renders an auditor-facing report with the
verification status from `verify_chain`/`verify_anchors`.

Concrete control mappings (cite these in the product):

| Framework / control | Maverick evidence (already emitted) | Source |
|---|---|---|
| **EU AI Act Art. 12 (logging / record-keeping)** | signed append-only event chain, per-action attribution | `audit/signing.py` |
| **EU AI Act Art. 14 (human oversight)** | `consent_prompt`/`consent_result`, `halt` (kill-switch), HITL queue | `safety/consent.py`, `killswitch.py` |
| **EU AI Act Art. 50 (transparency)** | first-turn AI disclosure | `compliance.py` |
| **NIST AI RMF — MAP/MEASURE/MANAGE** | registry (MAP), audit metrics + risk tier (MEASURE), capability/ACL controls (MANAGE) | registry + `capability.py` |
| **ISO/IEC 42001 (AIMS controls)** | inventory of AI systems, roles/owners, operational controls + records | registry + audit |
| **SR 11-7 (model risk: inventory, monitoring, override)** | model registry, per-run cost/outcome audit, override = consent record | `world_model.py`, `audit/events.py`, `safety/consent.py` |
| **SOC 2 (CC7/CC8 audit trail, change mgmt)** | tamper-evident audit, capability-denied + ACL changes, lifecycle transitions | `audit/signing.py`, registry |

Frameworks (cite as URLs in the UI/docs):
- EU AI Act — <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689> (Arts. 12, 14, 50)
- NIST AI RMF 1.0 — <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf>
- ISO/IEC 42001:2023 — <https://www.iso.org/standard/81230.html>
- SR 11-7 — <https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- SOC 2 (AICPA TSC) — <https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2>
- OWASP Agentic Top 10 — <https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/>

## Projection-vs-net-new

| Capability | Projection (cheap, weeks) | Net-new (expensive) |
|---|---|---|
| Agent/model/tool **inventory** | read-model over capability graph + tool registry + MCP specs + world model | `registry` table for owner/purpose/risk_tier/lifecycle metadata |
| **Risk tiering** | defaults from `tool_risk` + data-access | human-assignable tier + per-framework tier mapping |
| **Lifecycle / approvals** | reuse `approvals` table + consent queue | proposed→approved→production→retired state machine + UI |
| **Runtime enforcement (own agents)** | `capability.py` + `tool_acl.py` + `consent.py` (done) | framework **tags** on each policy rule |
| **Evidence packs** | filter/map signed audit events; reuse `verify_chain`/`verify_anchors` | **control catalog + mapping table**; PDF/JSON **renderer**; control-coverage gaps view |
| "**Where are my agents**" dashboard | query registry read-model + `last_seen` | dashboard views/pages |
| **Identity** for the buyer's org | — | **SSO/OIDC + SCIM** (`identity/`) — net-new, P0 |
| **Govern third-party agents** | OTel span ingest (`observability.py` exists); MCP introspection (`mcp_client.py` exists) | **ingestion adapter / collector** mapping foreign telemetry → registry + audit schema; lightweight **SDK** |

Rule of thumb: **registry + evidence + dashboard = projection** (the audit/
capability substrate already emits the data). **Control catalog, SSO/SCIM, and
third-party ingestion = net-new** and are where the real cost sits.

## Third-party agent strategy (the TAM question)

If Maverick governs only its own agents, the buyer must run their AI workloads
*on Maverick* — a tiny, self-selecting market. The category ("where are my
agents, what can they do, what did they do, prove it") demands governing the
estate the buyer **already runs**: LangGraph, CrewAI, OpenAI Assistants, raw MCP
servers. Three ingestion vectors, in build order:

1. **MCP introspection (ship first; nearly free).** `mcp_client.py` already
   connects to arbitrary MCP servers, lists tools, and SHA-pins binaries
   (`pin_sha256`) against the 2026 supply-chain attack class. Every MCP server +
   its tools becomes a registry entry with data-access edges — **zero new
   protocol work**, just a registry projection of `tools/list`.
2. **OTel collector (the breadth play).** `observability.py` already *emits*
   OTel spans for tool calls, LLM turns, and provider dispatches. Invert it:
   stand up a **collector that ingests** spans from any OTel-instrumented agent
   framework (LangGraph, CrewAI, and OpenAI Assistants all support OTel /
   GenAI semconv) and maps `gen_ai.*` span attributes → registry rows + audit
   events. This is the one bet that unlocks the TAM. **Read-only/observe-and-
   attest** at MVP: we record and map foreign actions into the evidence chain;
   we do **not** enforce on them yet.
3. **Lightweight governance SDK (defer to v2).** A decorator/callback
   (`@governed`) for frameworks to *call into* capability checks + consent +
   audit before a tool fires — the only path to **runtime enforcement** on third
   parties. Higher integration cost (the customer instruments their code), so it
   follows the read-only collector.

**Honest scoping:** at MVP we can **observe, inventory, and attest** third-party
agents via MCP + OTel (read-only). We **cannot enforce** policy on a LangGraph
agent until they adopt the SDK or route tools through our MCP/A2A proxy. Selling
"system of record + evidence for your whole agent estate" is true on day one;
selling "runtime control plane for third-party agents" is a v2 claim. Do not
oversell enforcement.

## 90-day cut

Ship a **read-only system of record + evidence pack** for the agent estate:

1. **Registry table + projection** over capability graph, tool registry, MCP
   specs, world model. Owner/purpose/risk_tier/lifecycle editable; Maverick
   agents auto-discovered. (~projection + thin schema)
2. **Control catalog + mapping table** for the seven controls above (EU AI Act
   12/14/50, NIST AI RMF, ISO 42001, SR 11-7, SOC 2 trail). Net-new, but it's a
   data file, not an engine.
3. **Evidence projector + renderer**: filter signed audit events per control,
   embed `verify_chain`/`verify_anchors` status, export JSON + PDF.
4. **"Where are my agents" dashboard**: inventory, capabilities, data-access
   edges, `last_seen`, control-coverage gaps.
5. **Third-party read-only ingest, MVP slice**: MCP-server introspection into
   the registry **+** a minimal OTel-span collector mapping `gen_ai.*` → audit
   events. Proves "governs non-Maverick agents."
6. **Policy-as-code framework tags** on existing ACL/capability/consent rules
   (small; the Q1→Q2 bridge).
7. **SSO/OIDC + SCIM** (`identity/`) — required for any org buyer; reuse the
   prior analysis's P0.

Each item is config-gated, wizard-surfaced, fail-open (house rules).

## Defer

- **Runtime enforcement on third-party agents** (governance SDK / MCP-proxy
  interception). Observe-and-attest first; enforce in v2.
- **Compliance-as-agentic-labor** (DSAR/ROPA/vendor-questionnaire automation) —
  the prior analysis's Phase 2; independent and later.
- **Certifications & legal** (SOC 2 Type II, ISO 42001 cert, HIPAA BAA, DPA/SCCs,
  FedRAMP) — process/legal clock, not MVP engineering.
- **Encryption-at-rest/KMS, multi-tenant quotas, SIEM/WORM export** — Governed-
  Runtime track; needed for regulated *deployment*, not for the governance read-
  model demo. Pull in right after MVP.
- **OneTrust breadth not agent-shaped**: cookie/consent CMP, ethics hotline,
  55-framework regulatory-content library. Partner or skip; never clone.
- **Conformity-doc / model-card generators, drift/eval monitoring** — v2 of the
  evidence plane.

## What would kill us

1. **Maverick-only governance.** If the third-party MCP/OTel ingest slips, TAM
   collapses to the Maverick install base. This is the **#1 must-ship**, not a
   nice-to-have — the collector slice is non-negotiable in the 90-day cut.
2. **Evidence an auditor won't accept.** A projection that *looks* like a control
   map but doesn't survive audit scrutiny is worse than nothing. The mappings
   need a compliance SME's sign-off; "we emit a signed log" ≠ "this satisfies
   EU AI Act Art. 12." Tamper-evidence is real (`verify_chain`); the *mapping*
   claims are the risk.
3. **Overselling enforcement.** Claiming runtime control over third-party agents
   we can only observe will burn trust on first POC. Be precise: observe/attest
   now, enforce later.
4. **Incumbents close the gap from above.** OneTrust's AI-governance pillar,
   Vanta/Drata extending evidence automation into AI, and Microsoft's open-source
   Agent Governance Toolkit + Okta (identity side) are all moving. Our edge is
   *runtime, tamper-evident, agent-native* evidence vs. their *documentation/
   questionnaire* posture — but the window is months, not years.
5. **No commercial entity to sell it.** Per the prior analysis Part 6, this
   contradicts the OSS-only positioning. The engineering is option-neutral
   (Phase-0 controls help regardless), but the **A/B/C business-model call must
   precede** investing in the control catalog, SSO/SCIM, and a sales motion —
   otherwise we build a product with no one to ship it.
