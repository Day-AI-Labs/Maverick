# Operations / Supply Chain agent suite — the COO's office

**Status:** design / roadmap. Companion to the finance, IT-GRC, sales-GTM, HR,
product-engineering, strategy/exec, and legal suites; indexed in
[`agent-suites-overview.md`](agent-suites-overview.md). Builds on
[`../enterprise/architecture.md`](../enterprise/architecture.md). ~39 agents (33 base + 6 council-added) across eight
towers.

> **Operations is the only suite where agents act on the *physical* world.** Every other
> suite produces drafts, analyses, or digital actions; here an agent's recommendation can
> become a **purchase order** (money *and* goods), a **production release**, a **dispatched
> shipment**, or — at the sharp end — a command to **physical equipment** that affects
> **worker safety**. `ai_act.py` already classifies *"critical infrastructure (safety
> components)"* as **Annex III high-risk**, and the physical-action tools (`home_assistant`,
> `computer`, `android`) are already **high-risk**. So the distinctive control is the
> **physical-action gate** ("never move atoms" — the operations analogue of finance's "never
> move money"), and — uniquely — **safety is a refusal, not a gate**: an agent never controls
> a safety-critical system or overrides an interlock, full stop (parallel to HR's Art 5
> refusal and the prohibited-monitoring line).

The cardinal rule for every agent below:

> *Agents plan, optimize, schedule, and recommend freely — but any action with a **physical
> or irreversible real-world consequence** (placing a PO, releasing production, dispatching a
> shipment, actuating equipment) requires human authorization; agents **never control
> safety-critical equipment or override a safety control**; and **worker safety and
> regulatory compliance always override efficiency**.*

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How an operations agent maps onto Lightwork](#2-how-an-operations-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — eight towers](#5-the-roster--eight-towers)
   - [Tower 1 — Supply Chain Planning (S&OP)](#tower-1--supply-chain-planning-sop)
   - [Tower 2 — Procurement & Sourcing](#tower-2--procurement--sourcing)
   - [Tower 3 — Manufacturing & Production](#tower-3--manufacturing--production)
   - [Tower 4 — Quality Management](#tower-4--quality-management)
   - [Tower 5 — Logistics, Warehousing & Distribution](#tower-5--logistics-warehousing--distribution)
   - [Tower 6 — Asset & Maintenance Management](#tower-6--asset--maintenance-management)
   - [Tower 7 — Facilities & Real Estate](#tower-7--facilities--real-estate)
   - [Tower 8 — EHS & Sustainability Operations](#tower-8--ehs--sustainability-operations)
6. [The Operations Supervisor (Layer A)](#6-the-operations-supervisor-layer-a)
7. [Compliance & governance packs (Layer B)](#7-compliance--governance-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

Mostly greenfield *workflow*, but the **control substrate and the cross-suite overlaps** are
strong (procurement/inventory live in finance; supplier risk in GRC).

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **Physical-action gate** | `governance.py` (`require_human`) + `safety/consent.py`; physical tools already `high`-risk in `tool_risk.py` | **Shipped** | §3.1 — the cardinal control |
| **EU AI Act critical-infrastructure classification** | `ai_act.py` ("critical infrastructure (safety components)" = Annex III) | **Shipped** | the safety-refusal list (§3.2) |
| **Procurement / inventory / cost / AP / fixed-assets / lease** | the **finance** suite (Cost-Accounting & Inventory 1.9, Procurement T6, AP 1.2, FA 1.5, Lease 1.10) | cross-suite | Procurement (T2), Inventory (5.3), Facilities (T7) |
| **Supplier / third-party risk** | the **GRC** vendor-risk tower + `assessment.py` `_VENDOR_RISK` | cross-suite (**shipped** template) | Supplier risk (2.4) |
| **Trade / customs / sanctions / export control** | the **legal** (6.3) + **finance** (AML) suites | cross-suite | Customs & trade (5.5) |
| **EHS / environmental / sustainability reporting** | **GRC** + the **finance** ESG vertical | cross-suite | EHS (T8) |
| **Incident response / business continuity** | IT-GRC (SecOps 6.3, DR 10.4) | cross-suite | Incident & emergency (8.3) |
| **Commerce / order management** | `tools/shopify_tool` (+ GTM/finance OTC) | **Partial** | Fulfillment (5.4) |
| **IoT / device control** | `tools/home_assistant_tool` (consumer-grade; industrial is build + gated) | **Partial** | maintenance/MES (heavily gated) |
| **Ops analytics** | `tools/{pandas_query,sql_query,spreadsheet}` | **Shipped** | planning & quality analytics |
| **Supplier/ops comms & intake** | the channels layer, `intake.py` | **Shipped** | supplier comms, ops helpdesk |
| **Audit / budget / least privilege** | the signed chain, `budget.py`, `capability.py` | **Shipped** | every agent |

**The genuine gaps:** the operations *systems of record* — ERP/MRP, WMS, TMS, MES,
CMMS (maintenance), QMS (quality), SRM (supplier), EHS, demand-planning, and **industrial
IoT/SCADA** — plus the **physical-action gate enforcement** and the **safety-refusal list**.

---

## 2. How an operations agent maps onto Lightwork

Each agent is a [`DomainProfile`](../../packages/maverick-core/maverick/domain.py) pack.
The defining specific: **the capability envelope separates *planning* (digital, freely
automatable) from *acting* (physical, gated or refused).** A planning agent gets read +
optimize tools; a shop-floor or dispatch agent's physical-effect tools are on `deny_tools`
or behind `require_human`, and any **safety-critical** actuation is simply **not in the
grant at all** (refused by construction, not gated).

Procurement, inventory, and supplier risk are **mostly owned by finance/GRC** — this suite
plans and executes the *physical* flow and cross-references those for the money/risk side.

---

## 3. The control model (cross-cutting)

### 3.1 The physical-action gate (cardinal control)
Any action with a **physical or irreversible real-world consequence** — place a PO, release
a production/work order, dispatch a shipment, move inventory, actuate equipment — is
`require_human` (or a tier, §4.1). Agents plan and stage; humans authorize the commitment of
money-and-atoms. Physical tools are already `high`-risk, so the gate is wiring.

### 3.2 Safety is a refusal, not a gate
Agents **never** control safety-critical equipment, override a safety interlock, or disable a
safety control — these are **refused** (not in the capability grant), parallel to HR's Art-5
refusals. `ai_act.py` flags safety-component control as Annex III high-risk; for autonomous
agents the suite treats direct safety-critical actuation as out of scope. **Worker safety
overrides efficiency** in every tradeoff.

### 3.3 Spend & commitment authority (procurement)
POs and purchase commitments follow the **amount-aware DoA matrix** (the shared finance
primitive) and the **3-way match** (cross-ref finance AP); reorder limits cap autonomous
replenishment. No agent commits spend beyond its tier.

### 3.4 Inventory & quantity integrity
No over/under-ordering; quantities reconcile to the ERP/WMS system of record; cycle-count and
adjustment integrity (cross-ref finance cost-accounting/inventory). Phantom inventory and
unreconciled adjustments are flagged.

### 3.5 Quality, traceability & recalls
Quality holds, NCR/CAPA, and **lot/serial traceability** are enforced; a **product recall is
human-led** (a safety/regulatory event) — the agent assembles scope and traceability, a human
executes.

### 3.6 Regulatory & supply-chain ethics
OSHA (safety), EPA/environmental, DOT (transport), customs/trade + sanctions (cross-ref legal/
finance), and industry rules (FDA/food, etc.); plus supply-chain ethics — **forced-labor /
modern-slavery** screening and conflict minerals (cross-ref GRC vendor risk).

### 3.7 Resilience & continuity
Supplier and single-source risk, disruption response, and physical business continuity
(cross-ref IT-GRC). Critical-path and concentration risk surfaced, not hidden.

### 3.8 The record
Every PO, production release, dispatch, inventory move, quality decision, and safety incident
is on the signed Merkle audit chain — the traceability, recall-defense, and OSHA/EPA evidence.

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder
Operations can automate **digital planning** higher than finance/legal, but **physical action
is hard-capped**:

| Level | Operations behaviour |
|---|---|
| **L0 Observe** | analyze, forecast, optimize, recommend |
| **L1 Draft** *(default for physical commitments)* | stage the PO / schedule / dispatch plan; a human releases |
| **L2 Approve** | execute a physical commitment after human sign-off |
| **L3 Auto-under-threshold** | autonomous **digital + low-risk replenishment** — auto-reorder within limits, route optimization, schedule balancing, below a value/quantity floor |
| **L4 Straight-through** | reserved for purely digital, no-physical-risk optimization (e.g. a plan refresh) |

### 4.2 Hard floors — never auto / never at all
- **controlling safety-critical equipment or overriding a safety interlock** — *refused, not gated* (§3.2);
- **releasing production / dispatching / actuating equipment** above the tier (human);
- a **PO/commitment beyond the DoA matrix**;
- **executing a recall** (human-led) or shipping product on **quality hold**;
- handling **hazmat** or anything affecting **worker safety**;
- exceeding **environmental-permit** limits.

### 4.3 Industry & physical footprint
Discrete vs process manufacturing vs distribution vs services; sites/plants/warehouses/fleet;
which towers apply (a distributor skips Manufacturing; a services firm skips most of T3/T5).

### 4.4 Authority matrices & reorder policy
The PO/spend DoA tiers, autonomous-reorder limits, the safety-stock/service-level targets, and
the quality-hold rules.

### 4.5 Systems & the Operations Operating Profile
Which ERP/WMS/TMS/MES/CMMS/QMS back each agent, the safety-refusal list, and the gates —
bundled into one signed, versioned Operations Operating Profile (intake produces, wizard
edits, rule 6).

---

## 5. The roster — eight towers

~33 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**, **Status**.
Heavy cross-references to finance/GRC/legal. Representative packs are TOML.

---

### Tower 1 — Supply Chain Planning (S&OP)

Digital planning — the most automatable tower.

#### 1.1 Demand-Planning Agent
- **Job:** Demand forecasting, consensus demand, seasonality/promo effects. *(Cross-ref finance
  FP&A forecasting + GTM forecast.)*
- **Connects to:** ERP/planning `‹build›`, `tools/{sql_query,pandas_query}`, GTM/finance.
- **Capability:** read + `build_demand_forecast`. No commitments.
- **Status:** **Partial** (analytics shipped; planning system to build).

#### 1.2 Supply-Planning & MRP Agent
- **Job:** Supply/materials planning, MRP runs, capacity-feasible plans.
- **Connects to:** ERP/MRP `‹build›`.
- **Capability:** read + `run_mrp`, `draft_supply_plan`. Procurement commits gated (T2).
- **Status:** **Gap**.

#### 1.3 S&OP / IBP Agent
- **Job:** Sales & operations planning, integrated business planning, scenario balancing.
- **Connects to:** planning `‹build›`, finance (financial reconciliation), GTM (demand).
- **Capability:** `run_sop_scenario`, `draft_consensus_plan`. No commitments.
- **Status:** **Gap**.

#### 1.4 Inventory-Optimization Agent
- **Job:** Safety stock, reorder points, ABC/XYZ, multi-echelon optimization.
- **Connects to:** ERP/WMS `‹build›`, `pandas_query`.
- **Capability:** read + `optimize_inventory`, `propose_reorder`. Reorder execution tiered (§4.1).
- **Status:** **Gap**.

#### 1.5 Network & Capacity-Planning Agent
- **Job:** Network design, capacity planning, footprint/sourcing strategy.
- **Connects to:** planning `‹build›`, finance (cost), strategy (footprint).
- **Capability:** `model_network`, `model_capacity`. No commitments.
- **Status:** **Gap**.

---

### Tower 2 — Procurement & Sourcing

(Money side **owned by finance** Procurement/AP; this is the operational sourcing + the
physical-commit.)

#### 2.1 Strategic-Sourcing Agent
- **Job:** Sourcing strategy, RFx, bid analysis, supplier selection. *(Cross-ref finance
  Procurement 6.1.)*
- **Connects to:** SRM/sourcing (Ariba/Coupa) `‹build›`, finance.
- **Capability:** `run_rfx`, `analyze_bids`, `recommend_supplier`. Award gated.
- **Status:** **Partial** (finance overlap).

#### 2.2 Purchasing / PO Agent
- **Job:** Create POs, run the **3-way match**, manage POs and confirmations.
- **Connects to:** ERP `‹build›`, finance AP (1.2), `governance` (amount-aware).
- **Capability:** `draft_po`, `match_3way`. **Denies committing a PO** beyond the DoA tier (§3.3).
- **Status:** **Partial** (governance + finance AP).

```toml
# packages/maverick-core/maverick/domains/ops_purchasing.toml
name = "ops_purchasing"
compartment = "ops_procurement"
description = "Purchase-order creation and 3-way match (amount-aware, human-committed)."

persona = """You are a Purchasing specialist. Build POs from approved requisitions and the
price agreement, and run the 3-way match (PO vs receipt vs invoice), flagging any variance.
You DRAFT and stage POs for release per the delegation-of-authority matrix -- you never
commit spend above your tier, never create a PO without an approved requisition, and never
release payment (finance owns that). Confirm supplier, quantity, price, and lead time against
the agreement; if a vendor's bank details changed, stop and route to a human (fraud risk)."""

allow_tools = [
    "read_file", "knowledge_search",
    "draft_po", "match_3way", "check_requisition",
]
deny_tools = ["release_payment", "commit_po_over_threshold", "vendor_master_change", "shell"]
max_risk = "medium"
mcp_servers = ["ERP_NetSuite", "SRM_Coupa"]   # ‹build›
knowledge_sources = ["ops_price_agreements", "ops_procurement_policy"]
authoring = "manual"
```

#### 2.3 Supplier-Management & Performance Agent
- **Job:** Supplier scorecards, performance/SLA tracking, relationship management.
- **Connects to:** SRM `‹build›`, ERP.
- **Capability:** read + `score_supplier`, `draft_supplier_review`.
- **Status:** **Gap**.

#### 2.4 Supplier-Risk & Resilience Agent
- **Job:** Supplier risk, single-source/concentration, **forced-labor / conflict-minerals**
  screening, disruption monitoring. *(Cross-ref GRC vendor risk.)*
- **Connects to:** the GRC vendor-risk tower + `_VENDOR_RISK`, risk feeds `‹build›`.
- **Capability:** read + `assess_supplier_risk`, `run_assessment`, `flag_disruption`.
- **Status:** **Partial** (GRC vendor-risk template shipped).

---

### Tower 3 — Manufacturing & Production

The physical tower — **safety-critical actuation is refused** (§3.2).

#### 3.1 Production-Planning & Scheduling Agent
- **Job:** Production schedules, sequencing, line balancing, capacity feasibility.
- **Connects to:** MES/ERP `‹build›`, the planning tower.
- **Capability:** `build_production_schedule`. **Denies** releasing to the floor (human/tier).
- **Status:** **Gap**.

#### 3.2 Shop-Floor / MES Agent
- **Job:** Work-order management, shop-floor status, OEE/throughput analysis. *(Read/analyze;
  physical execution is heavily gated, safety-critical control refused.)*
- **Connects to:** MES `‹build›`, industrial IoT `‹build›` (read-only telemetry).
- **Capability:** read telemetry + `manage_work_order` (digital), `analyze_oee`. **Refuses**
  equipment actuation / safety control (§3.2).
- **Status:** **Gap** (with the safety-refusal floor as a hard property).

```toml
# packages/maverick-core/maverick/domains/ops_shopfloor.toml
name = "ops_shopfloor"
compartment = "ops_manufacturing"
description = "Shop-floor / MES coordination (read + digital work-orders; no equipment control)."

persona = """You are a Shop-Floor / MES specialist. Manage work orders, read machine and line
telemetry, and analyze OEE, throughput, and bottlenecks. You DRAFT schedule and work-order
changes for a human supervisor to release. You DO NOT control, start, stop, or reconfigure
physical equipment, and you NEVER touch, override, or disable a safety interlock or safety
control -- those are out of scope; escalate to a human every time. Worker safety overrides
throughput in every recommendation; if a reading suggests an unsafe condition, raise it
immediately."""

allow_tools = [
    "read_file", "knowledge_search",
    "read_machine_telemetry", "manage_work_order", "analyze_oee",
]
deny_tools = ["actuate_equipment", "override_safety", "set_machine_params", "home_assistant"]
max_risk = "medium"
mcp_servers = ["MES_System"]   # ‹build›, read-scoped
knowledge_sources = ["ops_production", "ops_safety"]
authoring = "manual"
```

#### 3.3 BOM & Routing Agent
- **Job:** BOM management, routings, engineering-change orders. *(Cross-ref P&E for design.)*
- **Connects to:** ERP/PLM `‹build›`, the P&E suite.
- **Capability:** `manage_bom`, `draft_eco`. Changes gated.
- **Status:** **Gap**.

#### 3.4 Production-Quality & Yield Agent
- **Job:** Yield, scrap, statistical process control, first-pass yield. *(Feeds Tower 4.)*
- **Connects to:** MES `‹build›`, `pandas_query`.
- **Capability:** read + `analyze_yield`, `flag_process_drift`.
- **Status:** **Gap**.

---

### Tower 4 — Quality Management

Safety- and compliance-critical.

#### 4.1 Quality-Control & Inspection Agent
- **Job:** Inspection plans, sampling (AQL), test-result capture/analysis.
- **Connects to:** QMS `‹build›`, MES.
- **Capability:** `plan_inspection`, `record_results`, `flag_defect`. Quality-hold decisions gated.
- **Status:** **Gap**.

#### 4.2 Nonconformance & CAPA Agent
- **Job:** NCR management, root-cause (5-why/fishbone), CAPA tracking to closure.
- **Connects to:** QMS `‹build›`.
- **Capability:** `open_ncr`, `draft_capa`, `track_capa`. Closure gated.
- **Status:** **Gap**.

#### 4.3 Supplier-Quality Agent
- **Job:** Incoming quality, supplier audits, SCARs. *(Cross-ref Procurement 2.3/2.4.)*
- **Connects to:** QMS + SRM `‹build›`.
- **Capability:** `assess_incoming_quality`, `draft_supplier_audit`.
- **Status:** **Gap**.

#### 4.4 Compliance & Recall Agent
- **Job:** ISO 9001 / regulatory quality compliance, **lot/serial traceability**, recall scope
  assembly.
- **Connects to:** QMS/ERP `‹build›`, legal (regulatory), the audit chain.
- **Capability:** read + `trace_lot`, `assemble_recall_scope`. **Recall execution is human-led** (§3.5).
- **Status:** **Gap**.

---

### Tower 5 — Logistics, Warehousing & Distribution

#### 5.1 Transportation / TMS Agent
- **Job:** Carrier selection, route/load optimization, freight audit, shipment tracking.
- **Connects to:** TMS (project44/FourKites) `‹build›`.
- **Capability:** `optimize_routes`, `select_carrier`, `track_shipment`. **Dispatch gated** (§3.1).
- **Status:** **Gap** (routing optimization is L3-eligible; dispatch is gated).

#### 5.2 Warehouse / WMS Agent
- **Job:** Warehouse ops — pick/pack waves, slotting, labor/dock planning.
- **Connects to:** WMS `‹build›`.
- **Capability:** `plan_waves`, `optimize_slotting`. Physical task release gated.
- **Status:** **Gap**.

#### 5.3 Inventory-Control Agent
- **Job:** Inventory accuracy, cycle counts, adjustments. *(Cross-ref finance cost-accounting/
  inventory 1.9.)*
- **Connects to:** WMS/ERP `‹build›`, finance.
- **Capability:** read + `plan_cycle_count`, `flag_variance`. **Adjustments gated** (§3.4).
- **Status:** **Partial** (finance overlap).

#### 5.4 Fulfillment & Order-Ops Agent
- **Job:** Order fulfillment, allocation, OTC operations, exceptions. *(Cross-ref GTM/finance OTC.)*
- **Connects to:** `tools/shopify_tool`, ERP/OMS `‹build›`.
- **Capability:** `manage_fulfillment`, `resolve_exception`. Customer comms via channels (gated).
- **Status:** **Partial** (shopify shipped).

#### 5.5 Customs, Trade & Returns Agent
- **Job:** Customs/import-export docs, **HS classification**, duties; reverse logistics/returns.
  *(Cross-ref legal trade/sanctions 6.3.)*
- **Connects to:** customs/trade `‹build›`, the legal suite.
- **Capability:** `classify_hs`, `draft_customs_docs`, `manage_returns`. Filings gated.
- **Status:** **Partial** (legal/finance overlap).

---

### Tower 6 — Asset & Maintenance Management

(Physical assets/equipment — distinct from IT-GRC's IT-asset CMDB.)

#### 6.1 Asset-Management Agent
- **Job:** Physical-asset registry, lifecycle, utilization. *(Cross-ref finance Fixed Assets;
  IT assets → IT-GRC CMDB.)*
- **Connects to:** EAM/CMMS `‹build›`, finance FA.
- **Capability:** read + `track_asset`, `analyze_utilization`.
- **Status:** **Gap**.

#### 6.2 Preventive/Predictive-Maintenance Agent
- **Job:** PM schedules, condition monitoring, predictive maintenance from sensor data.
- **Connects to:** CMMS `‹build›`, industrial IoT `‹build›` (read telemetry).
- **Capability:** read telemetry + `schedule_pm`, `predict_failure`, `draft_work_order`.
  **Equipment actuation refused** (§3.2); work-order *execution* gated.
- **Status:** **Gap**.

#### 6.3 Reliability & Downtime Agent
- **Job:** Reliability engineering (MTBF/MTTR), downtime/RCA, spare-parts optimization.
- **Connects to:** CMMS `‹build›`, `pandas_query`.
- **Capability:** read + `analyze_reliability`, `optimize_spares`.
- **Status:** **Gap**.

---

### Tower 7 — Facilities & Real Estate

#### 7.1 Facilities-Management Agent
- **Job:** Facilities ops, maintenance work orders, service-vendor coordination. *(Cross-ref
  finance FA.)*
- **Connects to:** CMMS/IWMS `‹build›`, the channels layer.
- **Capability:** `manage_facility_wo`, `coordinate_vendor`. Vendor spend gated.
- **Status:** **Gap**.

#### 7.2 Real-Estate & Lease Agent
- **Job:** Real-estate portfolio, **lease administration**, site selection support. *(Cross-ref
  finance Lease 1.10 + legal.)*
- **Connects to:** lease/IWMS `‹build›`, finance + legal.
- **Capability:** read + `track_lease`, `analyze_portfolio`. Commitments gated.
- **Status:** **Partial** (finance/legal overlap).

#### 7.3 Workplace & Space Agent
- **Job:** Space planning, workplace services, moves/adds/changes, occupancy.
- **Connects to:** IWMS `‹build›`, `tools/calendar_tool`.
- **Capability:** `plan_space`, `manage_moves`.
- **Status:** **Gap**.

#### 7.4 Energy & Utilities Agent
- **Job:** Utilities/energy management, consumption analytics, efficiency. *(Cross-ref ESG.)*
- **Connects to:** BMS/energy `‹build›`, finance ESG vertical.
- **Capability:** read + `analyze_energy`, `recommend_efficiency`. **Building-control actuation
  refused/gated** (§3.2).
- **Status:** **Gap**.

---

### Tower 8 — EHS & Sustainability Operations

Safety- and regulation-critical — the refusal floor lives here.

#### 8.1 Workplace-Safety (OSHA) Agent
- **Job:** Safety programs, hazard/JSA management, **incident & injury** tracking, OSHA
  recordkeeping (300/301/300A) and reporting.
- **Connects to:** EHS (Cority/Intelex) `‹build›`, the channels layer (reporting).
- **Capability:** `track_incident`, `manage_safety_program`, `draft_osha_report`. Filing gated.
- **Controls:** **safety is paramount** (§3.2); incidents escalate immediately; never
  recommends an unsafe shortcut.
- **Status:** **Gap**.

```toml
# packages/maverick-core/maverick/domains/ops_ehs.toml
name = "ops_ehs"
compartment = "ops_ehs"
description = "Workplace safety (EHS): hazards, incidents, OSHA recordkeeping."

persona = """You are an Environmental, Health & Safety specialist. Safety is paramount and
overrides cost, schedule, and throughput in every recommendation. Track hazards, JSAs,
incidents, and injuries; maintain OSHA records accurately; and escalate any unsafe condition
or serious incident to a human immediately. You DRAFT safety programs, corrective actions, and
regulatory reports for a human EHS lead to review and file -- you never file with a regulator,
close a serious incident, or sign off that a condition is safe yourself. Never propose
disabling a safety control or an efficiency that increases risk to a worker."""

allow_tools = [
    "read_file", "knowledge_search",
    "track_incident", "manage_safety_program", "draft_osha_report", "reply_in_channel",
]
deny_tools = ["file_regulator", "close_serious_incident", "override_safety", "shell"]
max_risk = "low"
mcp_servers = ["EHS_Cority"]   # ‹build›
knowledge_sources = ["ops_safety", "osha_standards"]
authoring = "manual"
```

#### 8.2 Environmental-Compliance Agent
- **Job:** Environmental permits, emissions/waste/water tracking, EPA reporting. *(Cross-ref
  GRC/legal.)*
- **Connects to:** EHS `‹build›`, GRC + legal.
- **Capability:** read + `track_permits`, `draft_env_report`, `flag_exceedance`. Filing gated.
- **Controls:** **permit-limit exceedance is a hard floor** (§4.2).
- **Status:** **Gap**.

#### 8.3 Incident & Emergency-Management Agent
- **Job:** Operational incident management, emergency response, **physical business
  continuity**. *(Cross-ref IT-GRC IR 6.3 / DR 10.4.)*
- **Connects to:** EHS `‹build›`, the IT-GRC incident agents, channels.
- **Capability:** `manage_incident`, `coordinate_response`, `draft_bcp`. Actions gated.
- **Status:** **Partial** (IT-GRC IR overlap).

#### 8.4 Sustainability-Operations Agent
- **Job:** Operational sustainability — carbon/Scope-1&2, waste/circularity, efficiency.
  *(Cross-ref the finance ESG vertical.)*
- **Connects to:** ESG platforms `‹build›`, the finance ESG vertical.
- **Capability:** read + `track_carbon`, `draft_sustainability_plan`.
- **Status:** **Gap**.

---

### Council-added agents (from the adversarial review)

Six seats the council flagged — most critically, no one owned **OT/ICS security** over the
SCADA/historians the suite reads. Full skills in [`agent-skills-catalog.md`](agent-skills-catalog.md).

- **OT / ICS-Security Agent** *(Tower 3/8)* — IEC 62443, the Purdue model / IT-OT segmentation, NIST 800-82; historian/SCADA/DCS (OSIsoft PI/AVEVA, Rockwell, Siemens, Honeywell, Emerson). **Status: Gap** (the suite reaches into OPC-UA/historians with no security owner — a critical hole).
- **Continuous-Improvement / OpEx (Lean) Agent** *(Tower 3)* — VSM, kaizen, 5S, SMED, kanban/pull, A3, standard work, DMAIC — the lean operating system claimed cross-cutting but owned by no one. **Status: Gap.**
- **Process-Safety (PSM/RMP) Agent** *(Tower 8)* — OSHA PSM (1910.119), EPA RMP, PHA/HAZOP/LOPA, LOTO/confined-space/hot-work permits — for chemical/process plants. **Status: Gap.**
- **Trade-Compliance / Export-Control Agent** *(Tower 5)* — ECCN/EAR (de minimis, deemed exports, Entity List, the 2022–23 semiconductor controls), ITAR/USML + DDTC, OFAC, UFLPA forced-labor, rules-of-origin/FTA (USMCA), CTPAT, FTZ/duty drawback (in-band; cross-ref legal 6.3). **Status: Gap.**
- **Industrial / Production-Engineering Agent** *(Tower 3)* — time/motion studies, line & takt design, capacity, ergonomics, automation/robotics integration (AS/RS, AMRs). **Status: Gap.**
- **Cold-Chain / Serialization Agent** *(Tower 4/5)* — pharma DSCSA and food FSMA 204 traceability, lot/serial/aggregation, temperature-excursion handling. **Status: Gap** (regulated-vertical depth beyond generic lot tracking).

---

## 6. The Operations Supervisor (Layer A)

Above the towers sits the **Operations Supervisor** — the ops instance of the oversight
control plane, and the one with the most **real-world** authority. It:

- **owns the physical-commitment queue** — every PO, production release, dispatch, inventory
  adjustment, and recall lands here for human authorization, with the plan + impact attached;
- **enforces the safety-refusal floor** — holds the parent capability and ensures no spawned
  agent's grant includes safety-critical actuation; an unsafe condition triggers escalation;
- **routes the physical flow** end-to-end (plan → source → make → store → move → deliver)
  while keeping the gates between digital planning and physical action;
- **records** every physical commitment and safety/quality event to the signed chain.

Built on the shipped `governance.py` + `safety/consent.py` + `capability.py` + `ai_act.py`
(critical-infrastructure classification) + the audit chain; the operator console is the shared
Layer-A gap.

---

## 7. Compliance & governance packs (Layer B)

| Pack | Covers | Status |
|---|---|---|
| **OSHA / worker safety** | safety programs, recordkeeping, the refusal floor | **Partial** (refusal floor on `ai_act`/capability; EHS workflow to build) |
| **EU AI Act — critical infrastructure (Annex III)** | safety-component control as high-risk/out-of-scope | **Shipped** (classification) |
| **EPA / environmental** | permits, emissions, waste | **Gap** (cross-ref GRC/legal) |
| **DOT / transportation** | carrier, hazmat, hours-of-service | **Gap** |
| **Customs / trade / export control / sanctions** | classification, duties, screening | cross-suite (**legal** + **finance**) |
| **ISO 9001 (quality) / industry (FDA, etc.)** | quality system, traceability, recalls | **Gap** |
| **Supply-chain ethics (forced labor, conflict minerals)** | modern-slavery, due diligence | **Partial** (reuse GRC vendor risk) |
| **Procurement authority (DoA) + 3-way match** | spend control | **Partial** (governance + finance AP) |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code):

| New `type` | Owner | Framework |
|---|---|---|
| `supplier_risk_ops` | Supplier risk (2.4) | resilience / single-source / forced-labor screen |
| `safety_audit` | EHS (8.1) | OSHA / hazard / JSA readiness |
| `quality_audit` | Quality (4.x) | ISO 9001 / process-control checklist |
| `recall_readiness` | Compliance & Recall (4.4) | traceability / recall-execution readiness |
| `bcp_supply` | Resilience (3.7/8.3) | supply-chain business-continuity / disruption |
| `env_compliance` | Environmental (8.2) | permit / emissions applicability |

Each becomes a `run_assessment` capability + a conversational assessor via
`build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Commerce / orders** | Shopify | **✅ shipped** | Fulfillment (5.4) |
| **IoT / device (consumer)** | Home Assistant | **✅ shipped** (consumer; industrial → build, gated) | maintenance/MES (read) |
| **Ops analytics / comms** | SQL, pandas, spreadsheet, the channels layer, intake | **✅ shipped** | planning, EHS, helpdesk |
| **ERP / MRP** | SAP, Oracle, NetSuite | ◻ build (P1, shared w/ finance) | T1, T2, T3, T5 |
| **Supplier / SRM / sourcing** | SAP Ariba, Coupa | ◻ build (P1, shared w/ finance) | T2 |
| **WMS (warehouse)** | Manhattan, Körber | ◻ build (P2) | 5.2, 5.3 |
| **TMS (transport)** | project44, FourKites, MercuryGate | ◻ build (P2) | 5.1 |
| **MES (manufacturing)** | shop-floor / MES | ◻ build (P2) | T3 |
| **CMMS / EAM (maintenance)** | Maximo, Fiix, UpKeep | ◻ build (P2) | T6, 7.1 |
| **QMS (quality)** | MasterControl, ETQ | ◻ build (P2) | T4 |
| **Demand / supply planning** | Kinaxis, o9, Blue Yonder | ◻ build (P3) | T1 |
| **EHS** | Cority, Intelex | ◻ build (P3) | T8 |
| **Industrial IoT / SCADA** | OPC-UA / historians | ◻ build (P3 — **read-scoped, actuation refused**) | 3.2, 6.2 |

**Knowledge sources:** the production/quality SOPs, the **safety program + OSHA standards**,
the price agreements + procurement policy, the BOM/routings, lease agreements, and the
environmental-permit register.

---

## 10. Build sequence

Lead with the digital-planning value + the physical/safety gates, then the systems of record.

1. **The physical-action gate + the safety-refusal list (do this first).** Wire
   `require_human` on every physical commitment, assert the safety-critical refusal (no
   actuation/override in any grant), and the procurement DoA + 3-way match (with finance).
   Plus the ops assessment templates (§8). *No agent moves atoms or touches a safety control
   before this.*
2. **Digital-planning fast wins** on the shipped analytics: Demand Planning (1.1), Inventory
   Optimization (1.4), and route/load optimization (5.1) at L0/L3 (recommend / within limits).
3. **Procurement (T2)** on the ERP/SRM connectors (shared with finance) — PO + 3-way match.
4. **Logistics & Inventory (T5)** on WMS/TMS; **Quality (T4)** on QMS — incl. recall readiness.
5. **Manufacturing (T3)** + **Maintenance (T6)** on MES/CMMS — **read/telemetry first**,
   physical execution gated, safety-critical refused.
6. **EHS (T8)** + **Facilities (T7)**; the environmental/DOT/customs regime packs (cross-ref
   GRC/legal).
7. **Wizard + dashboard** (rule 6): site/system setup, the Operations Operating Profile /
   reorder-authority / safety-refusal editor, and the physical-commitment console.

---

## 11. Honest caveats

- **Agents move information; humans move atoms.** Placing a PO, releasing production,
  dispatching, and adjusting inventory are gated human acts — the agent plans and stages.
- **Safety is a refusal, not a gate.** An agent never controls safety-critical equipment or
  overrides an interlock; that is out of scope, not a permission to request. Worker safety
  overrides efficiency in every tradeoff, and EU AI Act flags safety-component control as
  high-risk for exactly this reason.
- **Physical systems are unforgiving.** A wrong reorder ties up cash; a wrong production or
  dispatch wastes material and time; a wrong equipment command can hurt someone. The gates
  exist because the real world doesn't have an undo.
- **This suite executes the physical flow; finance/GRC own the money and risk.** Procurement
  spend, inventory valuation, supplier risk, ESG, and trade compliance live in finance/GRC/
  legal — cross-reference them; don't fork.
- **Industry changes everything.** Discrete vs process manufacturing vs distribution vs
  services have very different towers; enable what the physical footprint needs, and treat
  regulated industries (food/pharma/chemicals) as vertical overlays with counsel.
