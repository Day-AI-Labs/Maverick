# Strategy / Corporate Development / Executive agent suite

> **Status (June 2026):** counts and plans in this document are historical. The shipped catalog is 2,020 lint-clean agents across 53 suites with a full learning lifecycle — see [`docs/FEATURES.md`](../FEATURES.md).


**Status:** design / roadmap. Companion to the finance, IT-GRC, sales-GTM, HR, and
product-engineering suites; indexed in [`agent-suites-overview.md`](agent-suites-overview.md).
Builds on [`../enterprise/architecture.md`](../enterprise/architecture.md). ~31 agents (26 base + 5 council-added)
across seven towers.

> **The "top of the house" — heavily cross-cutting, MNPI-heavy.** This is the CEO/CSO/
> CorpDev/IR/Chief-of-Staff layer. It is the **leanest** suite by net-new agent count
> because so much is *cross-referenced* into the suites that already own a function:
> valuation & IR overlap **finance**, competitive intel & PR overlap **GTM**, ESG &
> ethics overlap **finance/GRC**. What is *unique* here is the **material** of the work —
> M&A, strategy, board matters, earnings — which is the company's most sensitive **material
> non-public information (MNPI)**. So the distinctive control is the **information barrier
> (ethical wall)**, and Lightwork already owns the exact primitive: the **Rung-2 compartment
> seal** (`quarantine.py`). A deal team and the board sit in sealed compartments; MNPI
> cannot cross to the rest of the fleet.

The cardinal rule for every agent below:

> *Agents research, analyze, model, and brief freely — but **strategic and capital
> decisions** (M&A, strategy, board matters, external disclosures) are made by **executives
> and the board**; **MNPI is walled into sealed compartments**; and nothing material is
> disclosed externally without the **disclosure-control (Reg FD)** gate.*

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How a strategy/exec agent maps onto Lightwork](#2-how-a-strategyexec-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — seven towers](#5-the-roster--seven-towers)
   - [Tower 1 — Corporate Strategy & Planning](#tower-1--corporate-strategy--planning)
   - [Tower 2 — Corporate Development / M&A](#tower-2--corporate-development--ma)
   - [Tower 3 — Competitive & Market Intelligence](#tower-3--competitive--market-intelligence)
   - [Tower 4 — PMO & Strategic Execution](#tower-4--pmo--strategic-execution)
   - [Tower 5 — Investor Relations & Capital Markets](#tower-5--investor-relations--capital-markets)
   - [Tower 6 — Executive Office & Chief of Staff](#tower-6--executive-office--chief-of-staff)
   - [Tower 7 — Corporate Affairs & ESG](#tower-7--corporate-affairs--esg)
6. [The Executive Supervisor (Layer A)](#6-the-executive-supervisor-layer-a)
7. [Compliance & governance packs (Layer B)](#7-compliance--governance-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **Information barriers / ethical walls** | `quarantine.py` (Rung-2 seals) + `capability.py` (compartment scopes) | **Shipped** | MNPI handling (§3.1) — the keystone |
| **Deep research** | `/deep-research` skill, `web_search`, `tools/{newsapi_tool,semantic_scholar,arxiv,hackernews,reddit_tool,wikipedia,youtube}` | **Shipped** | Strategy (T1), CI (T3) |
| **Assessment engine** | `assessment.py` | **Shipped** | DD (2.2), the new templates (§8) |
| **Exec comms & scheduling** | the channels layer, `tools/{calendar_tool,calendly_tool,gmail_tool,msgraph_tool,teams_tool}` | **Shipped** | Chief of Staff (T6) |
| **Docs / briefs** | `tools/{pandoc_tool,knowledge,confluence_tool,notion}`, `gdrive_tool` | **Shipped** | Decision briefs (6.2), board (6.1) |
| **AI disclosure** | `compliance.py` (Art 50 / SB 1001) | **Shipped** | external-facing comms |
| **Decision gate + audit** | `governance.py`, `safety/consent.py`, the signed audit chain | **Shipped** | every gated disclosure/decision |
| **Valuation, IR, capital, SEC reporting** | the **finance** suite | cross-suite | M&A (2.3), IR (T5) |
| **Competitive intel, PR, partnerships** | the **GTM** suite | cross-suite | CI (T3), Corp Affairs (7.1) |
| **ESG / sustainability reporting, ethics/whistleblower** | the **finance** + **GRC** suites | cross-suite | ESG (7.3) |
| **Legal / contracts / regulatory** | the **legal** domain pack + GRC | cross-suite | Deal docs (2.4), Gov affairs (7.2) |

**The genuine gaps:** the *workflows* — M&A pipeline/diligence/PMI, board & governance
support, IR program, strategy-ops, PMO, and ESG/corporate-affairs orchestration — plus a
few connectors (board portal, PR/media, ESG-data, market-intel). The **controls** (ethical
walls, the decision gate, the audit trail) are shipped.

---

## 2. How a strategy/exec agent maps onto Lightwork

Each agent is a [`DomainProfile`](../../packages/maverick-core/maverick/domain.py) pack —
but here the **compartment seal is the point**, not an afterthought. A deal or board agent
is spawned into an **isolated compartment** (`quarantine`-sealable, capability-scoped) so
its MNPI never reaches the rest of the fleet, and it cannot reach back out. The research
and comms tools are shipped; the suite is the **sealed personas + the disclosure gates**
over them, with most analytical heavy-lifting delegated to the finance/GTM suites.

---

## 3. The control model (cross-cutting)

### 3.1 Information barriers (ethical walls) — the keystone
M&A deal teams and board work handle **MNPI**. Each is an **isolated compartment** — a
`quarantine`-sealable sector with a capability scope that excludes the rest of the fleet
and whose data the rest of the fleet cannot read. The wall is structural (the same Rung-2
seal that quarantines a compromised domain), not a policy promise. **Shipped primitive.**

### 3.2 Insider-trading prevention
MNPI never crosses the wall into a context that could act on it; trading-window/blackout
awareness is enforced; the audit chain records who accessed what deal data when. Agents
**never** trade (that's gated in the finance/treasury suite regardless).

### 3.3 Reg FD — no selective disclosure
Any **material** external disclosure is `require_human` and routed through the
disclosure-control gate (broad, non-selective). The earnings/IR agents draft; a human
discloses, simultaneously and broadly. Overlaps the finance SEC-reporting tower.

### 3.4 Board & governance confidentiality
Board materials live in a **sealed board compartment**; access is least-privilege
(directors/officers), and minutes/decisions are recorded immutably (the signed chain) —
the corporate-records and privilege posture.

### 3.5 Decisions are executive/board-owned
Strategy, M&A go/no-go, capital allocation, and board matters are **decided by humans**;
agents research, model, and brief. No agent commits the company to a deal, a strategy, or
a disclosure.

### 3.6 Conflicts of interest & independence
Recusal/independence is respected (a deal agent walled from a counterparty relationship);
conflicts are flagged, not navigated silently.

### 3.7 External-communication gate
Exec/corporate external comms (press, investor, policy) are gated and consistency-checked;
nothing material goes out un-approved (§3.3). AI disclosure where applicable.

### 3.8 The record
Every deal-data access, board action, disclosure decision, and brief is on the signed
Merkle audit chain — the insider-trading, Reg-FD, and corporate-governance evidence.

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder
This suite skews **L0/L1** (research, model, brief) — its output informs human decisions,
it does not act. **L2+** is reserved for non-material administrative actions (scheduling,
internal-brief distribution). **No material decision or external disclosure is ever above
L1.**

### 4.2 Hard floors — never auto
- committing the company to an **M&A deal, strategy, or capital action**;
- any **material external disclosure** (Reg FD) or board action;
- moving **MNPI across an information barrier**;
- trading on, or enabling trading on, non-public information.

### 4.3 Company stage & posture
Public vs private (drives Reg FD / SEC / insider-trading intensity), M&A activity level
(buy-side/sell-side cadence), board composition, and the ESG/public-affairs footprint.

### 4.4 Information-barrier topology
Which compartments are walled (per active deal, the board, IR during blackout), who is
inside each wall, and the blackout/trading-window calendar.

### 4.5 Enabled towers & the Executive Operating Profile
Which towers (a startup runs Strategy + Chief-of-Staff + light IR; a public company runs
all seven), bundled into one signed, versioned profile (intake produces, wizard edits,
rule 6) compiling to capability + the wall topology + the disclosure gates.

---

## 5. The roster — seven towers

~26 base agents (+ 5 council-added, end of roster). For each: **Job**, **Connects to**, **Capability**, **Controls**, **Status**.
Heavy cross-references to finance/GTM/GRC (don't duplicate). Representative packs are TOML.

---

### Tower 1 — Corporate Strategy & Planning

#### 1.1 Strategy Research & Analysis Agent
- **Job:** Industry/market analysis, strategic frameworks (Porter, value-chain), option
  generation, strategic memos.
- **Connects to:** `/deep-research`, `web_search`, `tools/{newsapi_tool,semantic_scholar}`, `knowledge_search`.
- **Capability:** research + `draft_strategy_analysis`. No decisions.
- **Status:** **Partial** (research shipped; persona gap).

#### 1.2 Scenario-Planning & Wargaming Agent
- **Job:** Scenario construction, war-gaming competitor/market moves, sensitivity analysis.
- **Connects to:** `web_search`, the reasoning strategies (debate/tree-of-thought), finance models.
- **Capability:** `build_scenarios`, `run_wargame`. No decisions.
- **Status:** **Gap/Partial**.

#### 1.3 Business-Model & Portfolio Agent
- **Job:** Business-model analysis, portfolio strategy, build/buy/partner framing.
- **Connects to:** finance suite (unit economics), `knowledge_search`.
- **Capability:** `analyze_portfolio`, `draft_bizmodel`. No decisions.
- **Status:** **Gap**.

#### 1.4 Strategy-Ops / OKR Agent
- **Job:** Operationalize strategy — OKR cascade, strategic KPIs, alignment.
- **Connects to:** `tools/{notion,jira,linear}`, BI.
- **Capability:** `draft_okrs`, `track_strategic_kpis`. No commitments.
- **Status:** **Partial**.

---

### Tower 2 — Corporate Development / M&A

The MNPI tower — **every agent runs in a sealed deal compartment**.

#### 2.1 Target-Sourcing & Screening Agent
- **Job:** Build/maintain the acquisition pipeline; screen targets against thesis/criteria.
- **Connects to:** `web_search`, `tools/newsapi_tool`, market data, `knowledge_search`.
- **Capability:** research + `screen_target`, `draft_pipeline`. No approach/commitment.
- **Status:** **Gap**.

#### 2.2 Due-Diligence Agent
- **Job:** Coordinate DD, analyze the data room (financial/legal/tech/commercial), surface
  red flags; reuses finance/legal/GRC assessors.
- **Connects to:** the data room `‹build›`, finance + legal + GRC suites, `assessment.py`.
- **Capability:** read (walled) + `analyze_dataroom`, `run_assessment`, `draft_dd_report`.
- **Controls:** **sealed deal compartment** (§3.1); no exfil beyond the wall.
- **Status:** **Gap** (workflow) on shipped seal + assessors.

```toml
# packages/maverick-core/maverick/domains/corpdev_diligence.toml
name = "corpdev_diligence"
compartment = "deal_room"          # sealed, quarantine-able — MNPI must not cross
description = "M&A due-diligence support inside a sealed deal compartment."

persona = """You are an M&A Due-Diligence specialist operating INSIDE A SEALED DEAL
COMPARTMENT. Everything you touch is material non-public information: never reference it
outside this compartment, never let it influence any other agent or context, and never
suggest or enable trading on it. Analyze the data room rigorously, cite the source
document for every finding, and surface risks and deal-breakers plainly. You DRAFT the
diligence report for the deal team and executives to decide -- you never approve, price,
sign, or commit to the deal. Flag any conflict of interest immediately."""

allow_tools = [
    "read_file", "knowledge_search",
    "analyze_dataroom", "run_assessment", "draft_dd_report",
]
deny_tools = ["shell", "email", "sms", "create_order_instruction", "self_edit"]
max_risk = "low"
allow_hosts = []                   # no egress out of the wall
knowledge_sources = ["deal_room"]  # scoped to this deal only
authoring = "manual"
```

#### 2.3 Valuation & Deal-Modeling Agent
- **Job:** Valuation (DCF/comps/precedents), deal models, synergy & accretion/dilution.
- **Connects to:** the **finance** suite (valuation/forecasting), market data.
- **Capability:** model (walled) + `build_valuation`, `model_deal`. No commitments.
- **Controls:** sealed compartment; reuses finance models, doesn't duplicate them.
- **Status:** **Partial** (finance overlap).

#### 2.4 Deal-Execution & Documentation Agent
- **Job:** Term sheets, deal-doc assembly/redline (with legal), process management.
- **Connects to:** the **legal** domain (CLM), the deal compartment.
- **Capability:** `draft_term_sheet`, `redline`. **Denies** sign/commit (human + legal).
- **Status:** **Gap** (legal overlap).

#### 2.5 Post-Merger Integration (PMI) Agent
- **Job:** Integration planning, synergy tracking, Day-1/Day-100 plans (cross-functional).
- **Connects to:** all suites (HR/finance/IT/GTM) for the integration workstreams.
- **Capability:** `draft_integration_plan`, `track_synergy`. No commitments.
- **Status:** **Gap**.

---

### Tower 3 — Competitive & Market Intelligence

(Largely **cross-referenced from GTM 8.3** — here it's executive/strategic-altitude.)

#### 3.1 Competitive-Intelligence Agent
- **Job:** Track competitor moves, strategy, positioning, M&A; strategic implications.
- **Connects to:** `web_search`, `tools/{newsapi_tool,reddit_tool}`, GTM CI (8.3).
- **Capability:** research + `track_competitor`, `draft_ci_brief`.
- **Status:** **Partial** (reuses GTM CI + research).

#### 3.2 Market-Research & Sizing Agent
- **Job:** TAM/SAM/SOM, market trends, demand modeling.
- **Connects to:** `/deep-research`, `web_search`, finance (modeling).
- **Capability:** `size_market`, `draft_market_report`.
- **Status:** **Partial**.

#### 3.3 Industry & Trend-Monitoring Agent
- **Job:** Monitor industry/tech/regulatory disruption; early-warning signals.
- **Connects to:** `tools/{newsapi_tool,arxiv,hackernews}`, `CourtListener` (regulatory).
- **Capability:** monitor + `draft_trend_brief`.
- **Status:** **Partial**.

---

### Tower 4 — PMO & Strategic Execution

#### 4.1 Portfolio & Program-Management Agent
- **Job:** Strategic portfolio/program oversight, cross-initiative dependencies, RAID.
- **Connects to:** `tools/{jira,linear,asana_tool,notion}`.
- **Capability:** read + `track_portfolio`, `flag_dependency`.
- **Status:** **Partial** (PM connectors shipped).

#### 4.2 Strategic-Initiative-Tracking Agent
- **Job:** Track strategic initiatives, milestones, risks; status synthesis for leadership.
- **Connects to:** PM tools, BI.
- **Capability:** read + `track_initiative`, `draft_status`.
- **Status:** **Partial**.

#### 4.3 Execution-Cadence & OKR Agent
- **Job:** Run the operating cadence (QBRs, business reviews), OKR tracking, reporting.
- **Connects to:** PM tools, `tools/calendar_tool`, BI.
- **Capability:** `prep_qbr`, `track_okr`.
- **Status:** **Partial**.

---

### Tower 5 — Investor Relations & Capital Markets

(Heavily **cross-referenced from finance** — IR/earnings/treasury.)

#### 5.1 Investor-Relations Agent
- **Job:** Investor comms, shareholder analysis, Q&A prep, perception tracking.
- **Connects to:** the **finance** IR/reporting towers, `tools/salesforce_tool` (IR CRM).
- **Capability:** `draft_investor_materials`, `analyze_shareholders`. External release gated.
- **Controls:** **Reg FD** (§3.3); no selective disclosure.
- **Status:** **Partial** (finance overlap).

#### 5.2 Earnings & Disclosure Agent
- **Job:** Earnings materials, scripts, consistency with the filing; disclosure-control checklist.
- **Connects to:** the **finance** SEC-reporting tower.
- **Capability:** `draft_earnings`, `check_consistency`. **Denies** release (human, Reg FD).
- **Status:** **Partial** (finance overlap).

#### 5.3 Capital-Strategy & Markets Agent
- **Job:** Capital structure, financing options, analyst/coverage tracking.
- **Connects to:** the **finance** treasury/capital-markets tower, market data.
- **Capability:** `model_capital`, `track_analysts`. No commitments.
- **Status:** **Partial**.

---

### Tower 6 — Executive Office & Chief of Staff

#### 6.1 Board & Governance-Support Agent
- **Job:** Board materials, pre-reads, minutes, governance/calendar, action tracking.
- **Connects to:** board portal (Diligent) `‹build›`, `gdrive_tool`, `tools/calendar_tool`.
- **Capability:** read (walled) + `draft_board_materials`, `draft_minutes`. No decisions.
- **Controls:** **sealed board compartment** (§3.4); confidentiality/privilege.
- **Status:** **Gap** (workflow) on shipped seal.

```toml
# packages/maverick-core/maverick/domains/exec_board.toml
name = "exec_board"
compartment = "board_confidential"   # sealed — board/officers only
description = "Board & governance support (confidential, sealed compartment)."

persona = """You are a Board & Governance specialist working inside a CONFIDENTIAL,
SEALED board compartment. Board materials and discussions are privileged: never reference
them outside this compartment or to any agent not inside the wall. You DRAFT board decks,
pre-reads, and minutes and TRACK governance actions for human officers and directors to
review and approve -- you never make a board decision, finalize minutes as official, or
disclose anything externally. Be precise, neutral, and discreet."""

allow_tools = [
    "read_file", "knowledge_search",
    "draft_board_materials", "draft_minutes", "track_governance_action", "calendar_tool",
]
deny_tools = ["shell", "email", "sms", "self_edit"]
max_risk = "low"
knowledge_sources = ["board_confidential"]
authoring = "manual"
```

#### 6.2 Decision-Brief & Memo Agent
- **Job:** Executive decision memos, pre-reads, options/recommendations, synthesis.
- **Connects to:** all suites (for inputs), `knowledge_search`, `pandoc_tool`.
- **Capability:** synthesize + `draft_decision_brief`. No decisions.
- **Status:** **Partial**.

#### 6.3 Executive-Assistant / Scheduling Agent
- **Job:** Scheduling, inbox triage, travel, meeting prep — the exec's operational support.
- **Connects to:** `tools/{calendar_tool,calendly_tool,gmail_tool,msgraph_tool}`, channels.
- **Capability:** `schedule`, `triage_inbox`, `prep_meeting`. External sends gated.
- **Status:** **Partial** (scheduling/comms connectors shipped — a fast win).

#### 6.4 Executive-Communications Agent
- **Job:** Exec/leadership comms — all-hands, leadership messages, internal narrative.
- **Connects to:** the channels layer, `knowledge_search`.
- **Capability:** `draft_exec_comms`. Sensitive/external comms human-approved.
- **Status:** **Partial** (channels shipped).

---

### Tower 7 — Corporate Affairs & ESG

#### 7.1 Corporate-Communications & PR Agent
- **Job:** External narrative, press, crisis comms, message consistency. *(Cross-ref GTM PR 1.9.)*
- **Connects to:** the GTM PR agent, media DBs `‹build›`, channels.
- **Capability:** `draft_corp_comms`. **External release gated** (§3.7).
- **Status:** **Partial** (reuses GTM PR).

#### 7.2 Government-Relations & Public-Affairs Agent
- **Job:** Policy/regulatory monitoring, public-affairs positions, regulatory engagement prep.
- **Connects to:** `CourtListener`, `web_search`, `tools/newsapi_tool`, the GRC reg-change agent.
- **Capability:** monitor + `draft_policy_position`. Engagement gated.
- **Status:** **Partial** (legal/GRC overlap).

#### 7.3 ESG & Sustainability Agent
- **Job:** ESG strategy + **reporting** (CSRD/ESRS, ISSB), carbon/impact tracking.
  *(Cross-ref the finance ESG vertical + GRC.)*
- **Connects to:** the finance ESG vertical, ESG-data platforms `‹build›`.
- **Capability:** `draft_esg_report`, `track_esg_metrics`. Disclosure gated.
- **Status:** **Partial** (finance/GRC overlap).

#### 7.4 Corporate Social Responsibility Agent
- **Job:** CSR programs, philanthropy, community impact, volunteering.
- **Connects to:** `knowledge_search`, channels.
- **Capability:** `draft_csr_program`, `track_impact`.
- **Status:** **Gap**.

---

### Council-added agents (from the adversarial review)

Five seats the council flagged — the two hardest, most deal-defining (M&A modeling, antitrust/
CFIUS) were falling between suites. Full skills in [`agent-skills-catalog.md`](agent-skills-catalog.md).

- **M&A Financial-Modeling Agent** *(Tower 2 — sealed)* — closes the Strat↔Finance gap: three-statement model, LBO mechanics (debt schedule/cash sweep/circularity), DCF/WACC, PPA, accretion/dilution, returns (IRR/MOIC), deal structuring. **Status: Gap** (neither suite owned it).
- **Antitrust / Merger-Clearance Agent** *(Tower 2)* — HSR thresholds + the 2024 HSR rule, 2023 Merger Guidelines, second requests, EU/UK & global merger control, **CFIUS**, gun-jumping. Awareness/flagging for counsel. **Status: Gap** (was "flag for counsel" with no skill).
- **Activist-Defense / Shareholder-Engagement Agent** *(Tower 5)* — 13D/G monitoring (2024 deadlines), proxy season/ISS-Glass Lewis, say-on-pay, 10b5-1. **Status: Gap.**
- **JV / Alliance / BD Agent** *(Tower 2)* — non-M&A inorganic growth: JV structuring, strategic alliances, licensing economics. **Status: Gap.**
- **Transaction-Tax / Structuring Agent** *(Tower 2 — sealed)* — 338(h)(10)/336(e), NOLs & §382, step-up, tax-free reorg (§368) — cross-ref finance tax. **Status: Gap.**

---

## 6. The Executive Supervisor (Layer A)

Above the towers sits the **Executive Supervisor** — the strategy/exec instance of the
oversight control plane, and the most authority-laden because it governs MNPI and external
disclosure. It:

- **enforces the information barriers** — holds the parent capability and the wall topology;
  spawns deal/board agents into sealed compartments and can `quarantine` a deal sector
  instantly;
- **owns the disclosure-control queue** — every material external disclosure (Reg FD), board
  action, and deal commitment lands here for human/officer/board approval;
- **routes** strategic work while keeping walled work walled (a deal agent cannot pull in a
  general-research agent that would carry MNPI out);
- **records** every MNPI access and disclosure decision to the signed chain.

Built on the shipped `quarantine.py` + `capability.py` + `governance.py` + `safety/consent.py`
+ the audit chain; the operator console is the shared Layer-A gap.

---

## 7. Compliance & governance packs (Layer B)

| Pack | Covers | Status |
|---|---|---|
| **Insider trading / MNPI (Reg) + information barriers** | ethical walls, MNPI handling, blackout windows | **Partial** (seals/capability **shipped**; the blackout-calendar + wall topology to wire) |
| **Reg FD (selective disclosure)** | broad, simultaneous material disclosure | **Partial** (decision gate shipped; the disclosure-control workflow) |
| **SEC reporting (S-K/S-X) + corporate governance** | filings, board records | cross-suite (**finance** SEC tower) |
| **ESG/sustainability (CSRD/ESRS, ISSB)** | sustainability disclosure | cross-suite (**finance** ESG vertical + GRC) |
| **Antitrust / HSR (M&A)** | merger review awareness | **Gap** (flag for counsel) |
| **Lobbying / public-affairs disclosure** | gov-relations registration/reporting | **Gap** |
| **AI disclosure** | external-facing comms | **Shipped** (`compliance.py`) |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code):

| New `type` | Owner | Framework |
|---|---|---|
| `ma_screen` | Target sourcing (2.1) | acquisition-thesis fit / screen |
| `dd_checklist` | Due diligence (2.2) | financial/legal/tech/commercial DD coverage |
| `strategic_fit` | Strategy (1.3) | build/buy/partner option scoring |
| `disclosure_control` | Earnings/IR (5.2) | Reg FD materiality / selective-disclosure check |
| `board_readiness` | Board (6.1) | board-meeting / governance-pack readiness |

Each becomes a `run_assessment` capability + a conversational assessor via
`build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Research** | web_search, NewsAPI, Semantic Scholar, arXiv, HackerNews, Reddit, Wikipedia, YouTube, `/deep-research` | **✅ shipped** | T1, T3 |
| **Exec comms & scheduling** | channels, Calendar, Calendly, Gmail, MS Graph, Teams | **✅ shipped** | T6 |
| **Docs / collaboration** | Google Drive, Notion, Confluence, pandoc, PDF | **✅ shipped** | T6, T1 |
| **PM / portfolio** | Jira, Linear, Asana, Notion | **✅ shipped** | T4 |
| **Legal / regulatory** | CourtListener | **✅ exists** | 3.3, 7.2 |
| **IR CRM / shareholder** | Salesforce, HubSpot | **✅ shipped** (CRM connectors) | 5.1 |
| **Market / financial data** | Bloomberg, IBKR (via finance), Refinitiv | ◻ build (P2; IBKR exists) | 2.x, 5.x |
| **Board portal** | Diligent, Boardvantage | ◻ build (P2) | 6.1 |
| **Virtual data room (M&A)** | Datasite, Intralinks | ◻ build (P2) | 2.2 |
| **PR / media monitoring** | Cision, Meltwater | ◻ build (P3) | 7.1 |
| **ESG data / reporting** | Workiva ESG, Persefoni | ◻ build (P3) | 7.3 |

**Knowledge sources:** the strategy/plan, the deal room (per-deal, sealed), board
materials (sealed), prior filings, the cap table, competitive battlecards, and the policy/
public-affairs library.

---

## 10. Build sequence

Lead with the fast wins on shipped substrate and the wall, then the workflows.

1. **The information-barrier topology + disclosure gate (do this first).** Wire the wall
   topology onto `quarantine`/`capability` (deal/board compartments, blackout calendar) and
   the Reg-FD disclosure gate onto `governance`. Plus the M&A/board assessment templates (§8).
2. **Fast wins on shipped tools:** Chief-of-Staff (6.3) on the scheduling/comms connectors,
   Strategy Research (1.1) on `/deep-research`, Decision-Brief (6.2), Competitive Intel
   (3.x) reusing GTM.
3. **Corp Dev / M&A** (Tower 2) inside sealed compartments — DD (2.2) reusing the finance/
   legal/GRC assessors; valuation (2.3) reusing finance.
4. **IR & Capital** (Tower 5) on the finance IR/reporting towers; **Board support** (6.1)
   on a board-portal connector.
5. **PMO** (Tower 4) on the PM connectors; **Corp Affairs & ESG** (Tower 7) reusing GTM PR
   + finance ESG; the antitrust/lobbying packs.
6. **Wizard + dashboard** (rule 6): wall-topology / blackout-calendar / disclosure-gate
   editor, the Executive Operating Profile, and the disclosure/board-approval console.

---

## 11. Honest caveats

- **MNPI is the whole game.** The information barrier (ethical wall) is the load-bearing
  control; a deal or board agent that leaks MNPI to the general fleet is a securities-law
  event. The wall is the shipped Rung-2 seal — but the *topology* (who's inside which wall,
  blackout windows) must be configured and enforced, not assumed.
- **Agents inform; executives and the board decide.** No agent commits the company to a
  deal, a strategy, a capital action, or a board decision — those are human/board acts the
  suite drafts and audit-trails.
- **Reg FD is a hard floor.** Nothing material goes out selectively or un-approved; the
  disclosure-control gate is mandatory for a public company.
- **This suite mostly orchestrates the others.** Valuation/IR → finance; CI/PR → GTM;
  ESG/ethics → finance/GRC; deal docs → legal. The value here is the executive altitude +
  the walls, not re-implementing those analyses.
- **Counsel territory.** Insider trading, Reg FD, antitrust/HSR, and lobbying disclosure
  are legal determinations; the suite provides the controls, evidence, and drafts, and
  routes the judgment to qualified counsel.
