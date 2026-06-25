# Enterprise agent suites — quick reference

At-a-glance index of the business-function agent suites designed for the platform.
Full detail lives in the per-suite docs below; this is the summary to skim later.
**Fifty-two suites, 1,734 shipped agents** — the original eight functional
suites below plus customer experience, marketing, procurement, data &
analytics, security ops, executive office, facilities/EHS, tax preparation
(CPA firms), and ten industry verticals (healthcare, insurance, banking,
retail, manufacturing, construction, logistics, professional services,
government contracting, education/nonprofit), with jurisdiction packs in
HR/legal/finance. Run
`maverick domains-lint` for the live count and quality gate. Historical
note — the original plan was eight suites, ~346 agents (301 base + 45 added in
the adversarial-council review; counts below are base **+ council-added**).

- **Finance** → [`finance-agent-suite.md`](finance-agent-suite.md) — 38 + 5 = **43** agents, 7 towers (+ vertical packs)
- **IT / GRC / Privacy / Security / AI-Governance** → [`it-grc-agent-suite.md`](it-grc-agent-suite.md) — 47 + 8 = **55** agents, 10 towers
- **Sales / GTM (the revenue engine)** → [`sales-gtm-agent-suite.md`](sales-gtm-agent-suite.md) — 45 + 5 = **50** agents, 8 towers
- **HR / People** → [`hr-people-agent-suite.md`](hr-people-agent-suite.md) — 41 + 5 = **46** agents, 8 towers
- **Product & Engineering** → [`product-engineering-agent-suite.md`](product-engineering-agent-suite.md) — 40 + 6 = **46** agents, 8 towers
- **Strategy / Corp Dev / Executive** → [`strategy-corpdev-exec-agent-suite.md`](strategy-corpdev-exec-agent-suite.md) — 26 + 5 = **31** agents, 7 towers
- **Legal (the GC's office)** → [`legal-agent-suite.md`](legal-agent-suite.md) — 31 + 5 = **36** agents, 8 towers (extends `legal.toml`)
- **Operations / Supply Chain (the COO's office)** → [`operations-supply-chain-agent-suite.md`](operations-supply-chain-agent-suite.md) — 33 + 6 = **39** agents, 8 towers

**Per-agent skills** — a job description + the deep, named competencies each agent needs
(from Word/Excel to "query an Oracle DB for the trial balance", "stand up Oracle 23ai",
"fix data/automation errors in Salesforce", "the finer points of litigation procedure") —
are catalogued in [`agent-skills-catalog.md`](agent-skills-catalog.md). *(All eight suites
catalogued; the seven non-finance suites' council-added seats now carry full profiles.)*

**Platform architecture** — how the roster comes alive and adapts:
- [`self-extending-agent-factory.md`](self-extending-agent-factory.md) — the platform
  synthesizes its own agents & skills per customer and ships them through a human
  promotion gate ("genetic" self-extension, never self-modification).
- [`agent-to-agent-protocol.md`](agent-to-agent-protocol.md) — agent identity, handoffs,
  authorization, and verification (the trust fabric: signed, attenuating capabilities).

All build on [`../enterprise/architecture.md`](../enterprise/architecture.md)
(the three-layer control plane) and [`agent-factory.md`](agent-factory.md)
(domain packs). Status: draft design, on branch `claude/amazing-davinci-4Gw6P`.

---

## The shared design model (all suites)

- **Each agent is one `DomainProfile` pack** — `compartment` seal + `persona` +
  attenuating `allow_tools`/`deny_tools` + `max_risk` + `allow_hosts` +
  `mcp_servers` + `knowledge_sources`, plus the consumption + governance surface:
  an `[output]` contract (deliverable/consumers/cadence/gate), an editable
  `[[workflow]]` playbook, an `effort` tier (right-sized reasoning), and a
  `refuse` list of hard, no-approval-path prohibitions. All 1,734 carry these.
- **Tooling over the roster** — `maverick domains-lint` (well-formedness +
  envelope/gate/effort/deny-floor rules), `domains-audit` (governance-posture
  inventory: what's reachable, what's denied, refusals, sign-off — `--json` for
  GRC), `domains-eval` (behavioral golden cases + rubric scorer), and a
  query-based router (`list_specialists query=<task>`, hybrid lexical +
  embeddings) that narrows the roster to a shortlist.
- **The platform's own primitives *are* the controls.** Capabilities = access
  control (segregation of duties); the signed Ed25519 **Merkle audit chain** = the
  tamper-evident record; `governance.py` = the policy engine (allow/deny/**require_human**);
  consent/HITL = sign-off; `quarantine.py` = blast-radius containment;
  `killswitch.py` = the kill switch; `enterprise.py` = egress/residency lock.
- **Agents draft; humans approve, post, pay, file, certify.** No agent attests,
  certifies, moves money, files with a regulator, or signs off its own work.
- **Independence is structural** — assurance/audit/assessor agents get read-only
  capability over what they review and cannot remediate it (`Capability.attenuate()`
  is narrow-only).
- **Customization without forks** — one set of agents tuned per client via a signed,
  versioned **Operating Profile** that compiles to capability + governance policy +
  consent config + enabled regimes.

### The automation ladder (per action class, both suites)

| Level | Behaviour |
|---|---|
| **L0 Observe** | analyze & recommend; no write tools |
| **L1 Draft** *(default for systems of record)* | agent stages; a human posts/releases |
| **L2 Approve (maker-checker)** | agent executes only after per-action human sign-off |
| **L3 Auto-under-threshold** | auto below a $/risk/confidence floor; above → L2 *(needs the amount/severity-aware policy build)* |
| **L4 Straight-through** | autonomous within policy + budget; humans review after the fact |

Plus **hard floors** the profile compiler refuses to lower below L2 — e.g. money
movement / bank-detail changes / period close / filings (finance), and disabling a
security control / granting privileged access / closing a finding / notifying a
regulator (IT-GRC).

---

## Finance suite — at a glance

Greenfield domain, so it's a build plan. ~40 core agents in seven towers:

| Tower | Agents (selected) |
|---|---|
| **1 Controllership** | GL/Close · AP · AR · Payroll · Fixed Assets · Revenue Rec (ASC 606) · Intercompany/Consolidations · Expense/T&E · Cost Accounting & Inventory · Lease (ASC 842) · Account Reconciliation · Master-Data/CoA |
| **2 FP&A** | Management Reporting · Forecasting · Cash-Flow/Liquidity · CapEx/Capital Planning · Workforce/Headcount-Cost |
| **3 Treasury** | Cash Management · Investments (IBKR) · FX/Hedging · Capital Markets/Debt |
| **4 Tax** | Provision (ASC 740) · Compliance/Filing · Transfer Pricing |
| **5 Risk/Controls/Assurance** | SOX/ICFR · Internal Audit · External-Audit/PBC · Fraud · Anomaly · ERM · Credit Risk · AML/Financial-Crime |
| **6 Procurement & Vendor** | Spend Analysis · Vendor Master/Risk |
| **7 External Reporting** | SEC/Financial Reporting · IR/Earnings · Equity/Stock-Comp · Statutory/Local-GAAP |

Plus **vertical packs**: SaaS unit economics · project/WIP costing · fund/grant ·
regulatory capital · cost-allocation/ABC · insurance · ESG · escheatment.

**Control mapping:** SoD = disjoint capabilities · maker-checker = the
`require_human` gate · SOX book of record = the signed Merkle chain · money tools
are already `high`-risk so they auto-pause.

**Amount-aware authorization — shipped.** `governance.evaluate()` now takes an
`amount`/`currency` and gates on the policy's dollar tiers (`deny_above` /
`require_human_above`), and the agent chokepoint extracts the transaction amount
from tool args (`agent._governance_amount`), so the L3 / DoA dollar thresholds
are live. Remaining refinement (not a blocker): per-pack DoA thresholds — today
the tiers are org-level config, and every pack denies its irreversible tools
outright, so a per-role authority matrix only matters once a pack carries L3
automation.

---

## IT / GRC suite — at a glance

**This domain is largely already built**, so the doc leads with a reuse map and
marks every agent **Shipped / Partial / Gap / Process-only** (**38 / 26 / 24 / 5**).

### Ten towers (47 agents)

1. **AI Governance & Agent Oversight** — AI inventory · AIRA · EU AI Act conformity · model/agent cards · bias eval · **the Supervisor (Layer A)** · AI incident
2. **Privacy / Data Protection** — DPIA/PIA · ROPA · DSAR+erasure · data mapping/classification · consent · breach/notification · transfers/TIA · retention
3. **GRC core** — multi-framework compliance · evidence/audit-readiness · risk register/ERM · policy lifecycle · control testing/monitoring · regulatory change
4. **Internal Audit & Assurance** — internal audit · controls/SoD assurance · external-audit/PBC liaison
5. **Third-Party / Vendor Risk** — vendor risk assessment · subprocessor/DPA registry · continuous vendor monitoring
6. **Security Operations** — the Agent Shield (runtime) · SIEM/alert triage · security incident response · threat intel
7. **AppSec & Supply Chain** — secret scanning · SCA/dependency/license · SAST/secure code review · MCP/plugin supply-chain trust
8. **Vulnerability & Threat Mgmt** — vuln management · patch management · attack-surface/pen-test
9. **Identity & Access Mgmt** — joiner-mover-leaver · access review/recertification · privileged access (PAM) · auth/SSO posture
10. **IT Ops & Resilience** — CMDB/config · change management · observability/SRE · backup/DR · service desk/ITSM

### What's already shipped (wrap it, don't rebuild it)

- **AI gov:** `ai_act.py` (tiering + Art 50), `_AIRA` template
- **Privacy:** `dpia.py`, `ropa.py`, `dsar.py` + `audit/erase.py`, `audit/retention.py`, `_PIA`
- **GRC/compliance:** `soc2.py` (evidence), `compliance.py` (coverage report), `governance.py` (policy engine)
- **Vendor:** `_VENDOR_RISK` template
- **Security:** the Agent Shield (`safety/*`), signed Merkle audit, `capability.py`, `quarantine.py`, `killswitch.py`, `enterprise.py` (egress lock), `crypto_at_rest.py`, `oidc.py`, `fleet.py`

Towers 1–3 and 5 are mostly **thin personas over these engines** (the proven
pattern from the shipped conversational compliance assessor).

### The genuine gaps (actually new to build)

AI inventory · model cards · bias eval · AI-incident & breach-notification
workflows · risk register/ERM · policy lifecycle · regulatory-change tracking ·
internal-audit workflow · subprocessor registry · SIEM forwarder/correlation (CEF
export exists) · security-IR workflow · threat intel · CVE/SBOM vuln scanning ·
patch mgmt · IAM joiner-mover-leaver · CMDB · change-mgmt workflow · backup/DR ·
ITSM. Two **primitive** gaps: a **mid-session capability-revocation sweep + revocation list**
(expiry itself is already enforced at `permits()`) and the **SoD/access-conflict linter**.

Many IT-ops items are **Process-only** — the agent orchestrates and *evidences* a
human/org workflow (provisioning, access reviews, change control), it doesn't
replace the people or the systems of record.

### The throughline

**Lightwork's own primitives are the GRC controls, so the fleet governs itself** —
Tower 1 oversees the very agents it runs among, which is exactly why the
un-lowerable hard floors live in the profile compiler, not per-tenant config. The
strongest already-built story is the **GRC Supervisor (Layer A)**: governance +
consent + quarantine + killswitch + fleet all ship — only the operator console is
the gap.

---

## Sales / GTM suite — at a glance

The full go-to-market motion (Marketing → SDR → Sales/AE → CS → Support, with RevOps
+ Enablement). **Rich substrate, greenfield workflow** — the *engagement* layer ships;
the *business systems* don't.

### Eight towers (~45 agents)
1. **Marketing & Demand Gen** — campaigns · content/SEO · social · product marketing · brand/creative · lifecycle/nurture · marketing ops · events · PR
2. **Sales Development** — inbound qual · outbound SDR · enrichment/research · cadence · meeting booking
3. **Sales / AE & Deal Desk** — account plans · discovery · CPQ/quoting · deal desk · sales engineering · negotiation · contract/order form
4. **Revenue Operations** — pipeline & forecasting · territory/quota · commissions · CRM hygiene · lead routing · GTM systems
5. **Customer Success** — onboarding · health scoring · renewals · expansion · churn/save · QBRs · advocacy
6. **Customer Support** — triage/deflection · KB · escalation · voice-of-customer
7. **Partnerships & Channel** — recruitment · co-sell · marketplace
8. **Enablement, Strategy & Intelligence** — enablement · call coaching · competitive/win-loss · GTM strategy

### What's shipped (the substrate)
The 13-adapter **channels layer** (email/SMS/voice/social/messaging), **AI/bot
disclosure** (Art 50 / CA SB 1001, `compliance.py`), send-tools = `high`-risk + the
**consent gate**, **scheduler/worker** (cadences), **intake** (lead intake), rate/spend
caps, and PII/egress/DSAR. Live connectors: Gmail, Calendar, Drive, Figma, Wix.

### Genuine gaps
The systems of record + workflow: CRM, MAP, CPQ, CLM/e-sign, sales-engagement,
conversation intelligence, enrichment/intent, ads, CS & support platforms; plus lead
scoring, attribution, deal-desk workflow, forecast roll-up, commissions, territory/
quota, churn models, and partner/PRM.

### The control story
Outward-facing, so the controls gate **what leaves the building**: the outbound gate,
the **consent/suppression hard floor** (CAN-SPAM / GDPR-PECR / CASL / TCPA — never
contact an opted-out party), AI disclosure, **discount / deal-desk authority**
(amount-aware, shared with finance), brand/claims governance (FTC), and forecast
integrity. Agents draft; humans send, sign, and commit price.

---

## HR / People suite — at a glance

The CHRO org — decisions *about people*, using the most sensitive data, under the
heaviest anti-discrimination regime. The convergence of three already-built control
stories: **privacy** (employee special-category PII), **AI governance** (employment =
EU AI Act Annex III high-risk + NYC LL144), and **need-to-know access control**.

### Eight towers (~41 agents)
1. **Talent Acquisition** — sourcing · resume screening/ranking · candidate engagement · interview design · offers · employer brand · recruiting analytics
2. **Onboarding & Offboarding** — onboarding · I-9/work-auth · offboarding/exit · internal mobility
3. **HR Operations** — helpdesk · HRIS/records · employment verification · policy/docs · compliance reporting (EEO-1/OSHA/ACA)
4. **Total Rewards** — comp analysis/bands · pay equity · benefits · leave/accommodation · payroll liaison
5. **Performance & Talent** — goals/OKRs · reviews · calibration/promotion · succession · PIP/coaching
6. **Learning & Development** — content · skills/career · LMS · compliance training
7. **Employee Relations & Investigations** — ER · investigations · employment-law · EEO/AAP/accommodations · labor relations · ethics/whistleblower
8. **People Analytics & Engagement** — analytics/attrition · workforce planning · engagement surveys · DEI analytics · internal comms

### What's shipped (the substrate)
EU AI Act classification (`ai_act.py` flags employment = Annex III, **emotion inference =
Art 5 prohibited**), the **privacy suite** (employee PII/Art 9, DSAR/erase/ROPA, egress,
encryption), the **consequential-decision human gate** (governance + consent),
**need-to-know access** (capability path scopes), AI/bot disclosure, channels + intake,
the assessment engine, and the audit chain.

### Genuine gaps
The keystone **employment-decision pack** (decision records + mandatory human review +
bias-audit export — named in the architecture) and the **bias-eval** engine (shared with
AI-Gov); plus HRIS/ATS/LMS/benefits/background-check connectors and the recruiting/perf/
comp/ER workflows.

### The control story
The convergence point — and the **only suite with prohibited (refused) uses**, not just
gated ones. Cardinal rule: agents screen/rank/draft/recommend, but a **human decides
every consequential employment action** (hire/fire/promote/pay/discipline) with a
documented, bias-audited rationale; **no protected-class data or proxies** in a decision;
and the suite **refuses what the EU AI Act prohibits** (e.g. workplace emotion inference).
Confidentiality is structural (ER/investigations/comp/medical compartments). Cross-suite
SoD: HR decides people, finance owns payroll, IT owns provisioning.

---

## Product & Engineering suite — at a glance

The inverse of the others: **Lightwork is itself a coding agent**, so the engineering core
and the connector layer are the most mature in the platform. *"The tools are nearly all
there; the role personas aren't."*

### Eight towers (~40 agents)
1. **Product Management** — discovery · roadmap · PRDs · backlog · product analytics · feedback synthesis · launch
2. **Design & UX** — UX research · UI design · design system · accessibility · UX writing
3. **Software Engineering (the kernel)** — implementation · code review · refactor · debug · test authoring · docs
4. **Quality Engineering** — test strategy · automation · eval/benchmark · bug triage · release+chaos
5. **DevOps / Platform / Release** — CI/CD · IaC · release/deploy · observability/SRE · dependency/supply-chain
6. **Data & ML Engineering** — pipelines · data quality · ML dev · MLOps · BI
7. **Developer Experience** — tech docs · internal tooling · DORA metrics · codebase Q&A
8. **Technical Research & Architecture** — design docs/ADRs · spikes · tech evaluation

### What's shipped (the most of any suite)
The coding kernel, 7 sandbox backends (+ a network-policy egress layer), code review + the test-driven verifier + the
SWE-bench eval harness, VCS/CI tools, the swarm/orchestrator — plus ~140 connectors incl.
the full PM stack (Jira/Linear/Asana/ClickUp/Notion/Confluence), product analytics
(GA4/Mixpanel/PostHog), DevOps (Datadog/Sentry/PagerDuty/Vercel/Cloudflare), Figma + a11y.

### Genuine gaps & control story
Gaps are the **role personas** (PM/designer/data-eng as packs), DORA metrics, MLOps, formal
QA test-mgmt. Cardinal control: agents write/test/review in the **sandbox**, but code ships
only through the **verifier + review** gates, **humans approve every merge/release/deploy**,
and — uniquely — **an agent never modifies its own runtime/safety without human
authorization** (`self_edit` ships off by default; *Lightwork builds Lightwork*).

---

## Strategy / Corp Dev / Executive suite — at a glance

The "top of the house" — leanest and most cross-referenced (valuation/IR → finance, CI/PR →
GTM, ESG → finance/GRC). What's unique is the **material**: MNPI.

### Seven towers (~26 agents)
1. **Corporate Strategy** — research/analysis · scenario/wargaming · business-model/portfolio · strategy-ops
2. **Corp Dev / M&A** — sourcing · due diligence · valuation · deal execution · PMI *(sealed deal compartments)*
3. **Competitive & Market Intelligence** — CI · market sizing · trend monitoring
4. **PMO & Strategic Execution** — portfolio/program · initiative tracking · cadence/OKR
5. **Investor Relations & Capital** — IR · earnings/disclosure · capital strategy *(Reg FD)*
6. **Executive Office & Chief of Staff** — board/governance *(sealed)* · decision briefs · exec scheduling · exec comms
7. **Corporate Affairs & ESG** — corp comms/PR · government relations · ESG · CSR

### What's shipped & the control story
Research (deep-research + the research tools), exec comms/scheduling (Calendar/Gmail/MS
Graph/Teams), docs, and — the keystone — **information barriers via `quarantine.py`
compartment seals**. Cardinal control: agents research/model/brief, but **executives and
the board decide**; **MNPI is walled into sealed compartments** (deal rooms, the board);
**nothing material is disclosed externally without the Reg-FD gate**. Gaps are the
workflows (M&A/board/IR/ESG) + connectors (board portal, data room, market data).

---

## Legal suite — the GC's office — at a glance

Horizontal — it touches every other suite — and the riskiest for AI (a fabricated citation
gets lawyers sanctioned). Extends the shipped `legal.toml` research pack into a full office.

### Eight towers (~31 agents)
1. **Legal Research & Knowledge** — research · citation verification · KM *(the shipped core)*
2. **Commercial Contracts (CLM)** — drafting · review/redline · negotiation · obligations/renewals · repository
3. **Corporate, Governance & Securities** — entity mgmt · board *(sealed)* · securities/SEC · equity *(cross-ref finance/strategy)*
4. **Litigation, Disputes & E-Discovery** — case mgmt · e-discovery *(sealed)* · legal hold · briefs · settlement
5. **Intellectual Property** — patent · trademark · copyright/trade-secret · licensing/infringement
6. **Regulatory, Antitrust & Trade** — regulatory counsel · antitrust/HSR · trade/sanctions
7. **Employment & Privacy Law** — employment law *(cross-ref HR)* · data-protection law *(cross-ref privacy)*
8. **Legal Operations** — matter mgmt · outside-counsel/e-billing · intake/triage · legal-tech · conflicts check

### What's shipped & the control story
The `legal.toml` research persona, **CourtListener** (case law / citation source), the doc
tools, and — the keystone — **privilege/conflict ethical walls via `quarantine.py`** (the
same seal Strategy uses for MNPI). Three distinctive controls: **citation integrity** (every
authority verified or marked unverified — never fabricated), **"research, not legal advice"**
(an attorney owns every position), and **privilege/conflicts** (sealed matter compartments;
legal holds beat erasure). Agents draft; **attorneys file, sign, serve, and own the
position**. The deep legal-owned towers are Contracts, Litigation, and IP; the rest is the
legal lens on work another suite performs.

---

## Operations / Supply Chain suite — the COO's office — at a glance

The only suite where **agents act on the physical world** — POs commit money *and* goods,
schedules move atoms, equipment control touches **worker safety**. Mostly greenfield (the
physical systems of record aren't wired as connectors yet).

### Eight towers (~33 agents)
1. **Supply Chain Planning (S&OP)** — demand · supply/MRP · S&OP/IBP · inventory optimization · network/capacity
2. **Procurement & Sourcing** — sourcing · purchasing/PO (3-way match) · supplier mgmt · supplier risk *(cross-ref finance/GRC)*
3. **Manufacturing & Production** — scheduling · shop-floor/MES *(read; actuation refused)* · BOM/routing · yield
4. **Quality Management** — QC/inspection · NCR/CAPA · supplier quality · compliance & recall
5. **Logistics, Warehousing & Distribution** — TMS · WMS · inventory control · fulfillment · customs/trade/returns
6. **Asset & Maintenance** — asset mgmt · preventive/predictive maintenance · reliability
7. **Facilities & Real Estate** — facilities · lease *(cross-ref finance/legal)* · workplace · energy
8. **EHS & Sustainability Ops** — workplace safety/OSHA · environmental · incident/emergency · sustainability

### What's shipped & the control story
The physical-action gate substrate (governance + consent; physical tools = `high`-risk), the
EU AI Act critical-infrastructure classification (`ai_act.py`), Shopify (orders), Home
Assistant (consumer IoT), ops analytics, and channels/intake. Two distinctive controls: the
**physical-action gate** ("never move atoms" — POs/production/dispatch/actuation are human-
authorized) and — uniquely — **safety is a refusal, not a gate** (agents never control safety-
critical equipment or override an interlock; worker safety overrides efficiency). Procurement/
inventory/supplier-risk/trade/ESG cross-reference finance/GRC/legal. Gaps are the systems of
record (ERP/MRP/WMS/TMS/MES/CMMS/QMS/EHS) + industrial IoT (read-scoped).

---

## Suggested first builds (highest leverage)

1. **Persona-wrapper packs** for the shipped engines — finance assessors and IT-GRC
   Towers 1–3/5 (fast wins, little new code).
2. **The amount/severity-aware policy** + the **Operating Profile compiler** with
   hard-floor validation — unlocks L3 automation and the DoA/discount matrix across all three suites.
3. **The SoD/access-conflict linter** + **mid-session capability-revocation sweep** (expiry already enforced) —
   the two cross-cutting primitive gaps.
4. **The Supervisor operator console** (Layer A) — the keystone for live oversight (GRC + Revenue).
5. **The outbound gate + consent/suppression hard floor** (GTM) — must precede any
   sending agent; rides the shipped channels + consent + AI-disclosure layer.
6. **The employment-decision pack + bias-eval engine** (HR + AI-Gov) — consequential-
   decision records + mandatory human review + bias-audit export; gates every consequential
   HR agent and satisfies NYC LL144 / EEOC / EU AI Act Annex III.
7. **Role-persona packs over the kernel + the self-modification floor** (P&E) — fast wins
   (SWE/code-review/PM/codebase-Q&A are persona+tool-scope over shipped tools); assert that
   `self_edit` stays off and safety-substrate changes route through a human.
8. **The information-barrier topology + Reg-FD disclosure gate** (Strategy/Exec) — wire deal/
   board compartments onto `quarantine`/`capability` and the disclosure gate onto `governance`.
9. **Citation-integrity pipeline + privilege/conflict walls** (Legal) — verify-every-cite on
   CourtListener + the conflicts check / ethical-wall setup on `quarantine`/`capability`.

10. **The physical-action gate + safety-refusal list** (Operations) — `require_human` on
    every physical commitment; safety-critical actuation excluded from every grant.

> **The convergence.** Across all eight suites, the keystone builds reduce to **three shared
> primitives**: (a) the **amount/severity/physical-aware policy + Operating-Profile compiler**
> (gates finance discounting, HR comp, GTM deal-desk, ops POs, and the L0–L4 tiers); (b) the
> **`quarantine`/`capability` compartment walls** (finance SoD, HR confidentiality, Strategy
> MNPI, Legal privilege — all the same Rung-2 seal); and (c) **refusal lists** carried by the
> profile compiler (HR's Art-5 prohibitions, Ops' safety-critical refusals). Build those once
> and every suite's load-bearing control lands.
