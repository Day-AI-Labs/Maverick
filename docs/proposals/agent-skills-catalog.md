# Agent skills catalog

**Status:** in progress — the per-agent skill profiles for the eight agent suites
([overview](agent-suites-overview.md)). For **each agent**: a one-line job description and
the **skills it should have** — from baseline (Word/Excel/email) to deep, named competencies
(query an Oracle DB for the trial balance, stand up Oracle 23ai, the finer points of
litigation procedure, fix data/automation errors in Salesforce). This installment covers the
**Finance** suite; the remaining seven follow (§ Remaining suites).

> **How a "skill" is delivered in Maverick.** Each skill below maps to one (or more) of three
> real mechanisms the platform already has:
> - an installable **`SKILL.md`** (procedural know-how — the skills system, `skills.py` +
>   the marketplace index) — *e.g. "3-way-match procedure", "ASC 606 5-step recognition"*;
> - an **MCP connector / tool** (system access) — *e.g. NetSuite, Salesforce, Oracle DB,
>   IBKR*;
> - a **knowledge source** (domain/regulatory expertise via RAG) + the pack **persona** —
>   *e.g. the GAAP library, the litigation playbook, OSHA standards*.
>
> So this catalog doubles as a backlog: every entry becomes a SKILL.md to author, a connector
> to build (see each suite's integrations table), or a knowledge pack to load.

---

## How to read an entry

```
#### <id> <Agent name>   [baseline bundles]
JD: <one-line job description>
- Systems:    named platforms/tools it must operate (incl. admin/troubleshooting depth)
- Technical:  data/query/coding/quant skills
- Domain:     the body of knowledge + methods/frameworks
- Regulatory: the laws/standards it must know
- Maverick:   the control-discipline skills specific to its risk (the gates it must respect)
```
Not every line applies to every agent. **Baseline bundles** (below) are assumed and not
repeated per agent — an entry lists only what it *adds* on top.

**Skill dimensions (added in council review).** Deep skills may carry a **delivery tag** —
`[S]` an installable SKILL.md, `[C]` an MCP connector/tool, `[K]` a knowledge source + persona
— and a **proficiency** `{working | strong | expert}`. An entry may add: **Prereq:** (skills
this seat presupposes), **Verified:** (how competence is checked — `assessment.py` / the eval
harness / `continuous_benchmark`), **Judgment:** (the professional-judgment skills the seat
can't be without), and **Cert:** (the human-credential-equivalent knowledge). These are
applied to the council-added and updated entries below and roll out to the rest incrementally.

---

## Baseline bundles (assumed; referenced by tag)

**[UB] Universal baseline — every agent**
- **Docs & comms:** MS Word / Google Docs · PowerPoint / Slides · Outlook/Gmail + Calendar ·
  business writing · meeting notes/summaries.
- **Spreadsheets:** Excel / Google Sheets (formulas, pivot tables, charts) · basic data viz ·
  reading dashboards.
- **Research & knowledge:** web research **with source citation** · the company knowledge base
  (RAG retrieval) · PDF/document extraction (OCR).
- **Collaboration:** the company chat (Slack/Teams) · the relevant ticketing/PM tool ·
  file management (SharePoint/Drive).
- **Maverick platform fluency:** using tools correctly within its capability scope ·
  respecting the **consent/HITL gates** · producing **drafts for human review** · writing to
  the **audit trail** · saying **"unverified"** when evidence is missing rather than guessing.

**[+Data] Data-analyst bundle** — SQL (Postgres/MySQL/SQL Server/Oracle/Snowflake/BigQuery) ·
Python + pandas · one BI tool (Power BI / Tableau / Looker) · data modeling & joins ·
advanced Excel (Power Query, XLOOKUP, dynamic arrays).

**[+Build] Builder bundle** — Git/GitHub · ≥1 language (Python/TS/…) · CI/CD basics · running
work in a **sandbox** · reading/writing tests · code review.

**[+Reach] Outreach bundle** — the channels layer (email/SMS/chat) · email deliverability &
list hygiene · a CRM (Salesforce/HubSpot) · **AI-disclosure + consent/suppression discipline**.

**[+Assess] Assessor bundle** — the `assessment.py` engine · running a structured questionnaire ·
evidence-cited findings + risk rating · the **"unknown is the honest answer"** discipline.

---

## Adversarial council review (applied)

This catalog was put through a **five-member adversarial council** (ex-CFO/CPA/CIA · ex-CISO/DPO/GRC ·
RevOps/CHRO/GC · ex-CTO/COO · a cross-cutting honesty/platform auditor). Their findings are
applied throughout; the headline changes:

- **Accuracy fixes (verified against source).** Sandbox count is **7 backends + a `network_policy`
  egress layer** (not 8). Capability **expiry is enforced at `permits()`** — the real gap is a
  *mid-session revocation sweep + revocation list*, not "expiry isn't enforced." `governance.py`
  is a **risk-floor** gate today; **DoA/amount thresholds are a build**, not a shipped primitive.
  The assessment flow is `start_assessment`→`answer_question`→`finalize_assessment` (there is no
  `run_assessment` tool; shipped templates are `pia`/`aira`/`vendor_risk`; `sox_control`/`itgc`
  are to author). **Figma/Wix are session-MCP, not in-repo** ("(MCP)", not "(live)").
  `safety/consent.py` path corrected. Finance count = **38**.
- **Staleness sweep** on dead endpoints / superseded standards: USPTO **Patent Public Search**
  (PatFT retired) & **Trademark Search** (TESS retired); Salesforce **Flow** (Process Builder
  retired) + **SOQL/governor limits**; **Marketing Cloud Account Engagement** (ex-Pardot);
  **ASC 740-10** + **Pillar Two/GILTI/BEAT/CAMT** (ex-"FIN 48"); **ASC 958 / ASU 2016-14**
  (ex-"FASB 116/117"); **FCCS** + **ASC 805/323/VIE** (HFM legacy); **SOFR / post-LIBOR**;
  **NIST CSF 2.0 · ISO 27001:2022 · PCI-DSS v4.0.1 · IIA Global Internal Audit Standards 2024 ·
  Colorado AI Act SB 24-205 · MECM (ex-SCCM)**.
- **~45 council-recommended agents added** — each suite gains a **"Council-added agents"** block
  for seats the reviewers found missing. Roster grows **301 → ~346**.
- **New skill dimensions** (delivery `[S]/[C]/[K]`, proficiency, Prereq, Verified, Judgment, Cert)
  per the "How to read" legend, applied to the council-added/updated entries.

The full per-reviewer findings (every CRITICAL/IMPORTANT item) drove the edits below; remaining
MINOR depth items are tracked for the incremental rollout.

---

## Finance suite

38 agents ([finance-agent-suite.md](finance-agent-suite.md)). Cross-cutting finance skills
every agent here also carries: double-entry accounting fluency; the **FASB ASC codification +
GAAP hierarchy (ASC 105) / IFRS structure** and the accounting-research workflow (Big-4
technical guides, SEC C&DIs); the **financial-statement assertions** (existence, completeness,
rights/obligations, valuation, cutoff, presentation); **materiality computation** (overall /
performance / clearly-trivial, **SAB 99 & SAB 108** quantitative *and* qualitative, rollover
vs iron-curtain); **functional-currency literacy (ASC 830 / IAS 21)**; the company **chart of
accounts**; **EUC / spreadsheet-control** discipline; and the **stage-not-post /
require_human-for-money** discipline. *(Per-system note: cloud ERPs are queried through their
native layer — NetSuite SuiteQL/saved-searches, S/4HANA CDS/OData, Oracle Fusion OTBI/BICC —
not by direct SQL against the system-of-record DB, which is itself an ITGC finding.)*

### Tower 1 — Controllership

#### 1.1 General Ledger & Close Agent  [UB +Data]
JD: Owns the period-end close — drafts journal entries, runs reconciliations and flux analysis, assembles the close binder.
- Systems: NetSuite · SAP S/4HANA · Oracle Fusion/EBS · QuickBooks/Xero (GL) · **BlackLine, FloQast** (close & recon) · OneStream/FCCS (consolidation; Hyperion HFM = legacy).
- Domain (added): **ASC 450** loss contingencies · **ASC 250** error correction (Big-R/little-R restatement) · accrual methodologies · management-review-control (MRC) evidence.
- Technical: **SQL against the GL/sub-ledger DB (Oracle, SQL Server)** to pull the trial balance & JE detail · the CoA/dimension data model · advanced Excel (Power Query, pivots).
- Domain: US GAAP / IFRS · R2R close mechanics (accruals, prepaids, reclasses) · balance-sheet reconciliations · **flux/variance analysis** · close-checklist management.
- Regulatory: **SOX §404 (ICFR)** · audit-trail/evidence discipline.
- Maverick: stage-not-post · SoD vs AP/AR · cite the source document for every entry.

#### 1.2 Accounts Payable Agent  [UB +Data]
JD: Procure-to-pay — ingests invoices, runs the 3-way match, codes and stages payment batches.
- Systems: **Bill.com, Coupa, Tipalti, Ramp, SAP Ariba** · ERP AP module · **OCR/IDP** (ABBYY, Ocrolus) for invoice capture.
- Technical: SQL AP queries · **3-way-match logic** (PO↔receipt↔invoice) · duplicate/anomaly detection · vendor-bank-change detection.
- Domain: P2P cycle · expense recognition (GAAP) · 1099/W-9, W-8 · accruals at close.
- Regulatory: **OFAC payee screening** · SOX AP controls.
- Maverick: payment-staging gate · ghost-vendor/duplicate checks · invoices ingested through the shield (poisoned-PDF defense).

#### 1.3 Accounts Receivable & Collections Agent  [UB +Data +Reach]
JD: Order-to-cash — invoices, cash application, AR aging, dunning, bad-debt flags.
- Systems: NetSuite · **Stripe, Chargebee, Zuora** (billing) · bank feeds (Plaid, Modern Treasury) · CRM (customer context).
- Technical: SQL AR · **cash-application matching** · aging analysis · DSO computation.
- Domain: O2C · ASC 606 basics · **CECL / allowance for doubtful accounts** · collections/dunning strategy.
- Maverick: collections comms gated (outbound) · write-offs `require_human` · SoD vs cash custody.

#### 1.4 Payroll Agent  [UB +Data]
JD: Gross-to-net — validates pay changes, computes payroll, reconciles the register, drafts payroll-tax filings.
- Systems: **Workday, ADP, Gusto, Rippling, Paychex** (payroll/HCM) · ERP payroll JE.
- Technical: **gross-to-net calculation** · garnishment & 401(k)/benefits deductions · payroll-register-to-GL reconciliation · multi-state allocation.
- Domain: **FLSA** (wage/hour) · payroll tax (941, W-2, state/local) · off-cycle & retro pay.
- Regulatory: IRS, state payroll tax, FLSA, garnishment law.
- Maverick: **highest-PII compartment** (encryption) · run-payroll & bank-detail edits `require_human` · SoD.

#### 1.5 Fixed Assets Agent  [UB +Data]
JD: Asset accounting — register, depreciation, capitalization, impairment, disposals.
- Systems: ERP FA modules (**SAP Asset Accounting, NetSuite FAM, Oracle Assets**) · asset/lease systems.
- Technical: **book depreciation** (SL/DDB/units-of-production) · **parallel tax book — MACRS, bonus §168(k), §179** + book-tax difference (feeds 4.1) · CWIP & **capitalized interest (ASC 835-20)**.
- Domain: capitalization policy & useful lives · **ASC 360 impairment (two-step recoverability)** vs **ASC 350 goodwill** · **ASC 410 ARO** · disposals/transfers.
- Maverick: capitalize-vs-expense threshold · disposal `require_human`.

#### 1.6 Revenue Recognition Agent  [UB +Data]
JD: ASC 606 — reads contracts, runs the 5-step model, builds deferred-revenue schedules.
- Systems: Salesforce/CPQ · **Zuora / Stripe Billing / Zuora Revenue (RevPro)** · ERP rev JE · contract repository.
- Technical: contract analysis · **deferred-revenue & rev-waterfall schedules** · SSP allocation · variable-consideration estimates.
- Domain: **ASC 606 / IFRS 15 (5-step)** · **ASC 340-40 (capitalized commissions / costs to obtain & fulfill)** · variable-consideration constraint · significant financing component · material right/breakage · bill-and-hold · contract mods · principal-vs-agent.
- Maverick: cite the contract clause · flag judgmental calls (SSP, variable consideration).

#### 1.7 Intercompany & Consolidations Agent  [UB +Data]
JD: Multi-entity consolidation — eliminations, FX translation, minority interest, consolidated statements.
- Systems: **Oracle FCCS, OneStream, SAP Group Reporting, Workiva** · multi-book ERP *(Hyperion HFM / SAP BPC = legacy)*.
- Technical: **intercompany eliminations** · **FX translation (CTA)** · allocations · entity-tree roll-up.
- Domain: **ASC 810** (consolidation — **voting-interest *and* VIE** models) · **ASC 805** (business combinations / PPA / goodwill / NCI at FV) · **ASC 323** (equity method) · **ASC 350** (goodwill impairment) · **ASC 830 / IAS 21** (FX, incl. CTA recycling on disposal).
- Maverick: intercompany nets to zero or it's a finding · tenancy-respecting cross-entity reads.

#### 1.8 Expense & T&E Agent  [UB +Data]
JD: Audits expense reports & corporate-card spend against policy; drafts the accrual.
- Systems: **Concur, Expensify, Ramp, Brex** · corporate-card feeds.
- Technical: policy-rule checking · card-statement reconciliation · duplicate/personal-spend detection.
- Domain: T&E policy · IRS **accountable-plan** rules · per-diem.
- Regulatory: **PCI-DSS** (card tokens, never PAN).
- Maverick: reimbursement `require_human` · SoD vs AP.

#### 1.9 Cost Accounting & Inventory Agent  [UB +Data]
JD: Standard/actual costing, inventory valuation, manufacturing variances, COGS.
- Systems: ERP cost modules (**SAP CO/Product Costing, NetSuite, Oracle Cost Mgmt**) · MES/WMS (read).
- Technical: **standard- & actual-cost roll-ups** (BOM/routing) · **variance analysis** (PPV, usage, labor, overhead absorption) · inventory valuation calc.
- Domain: **ASC 330** cost accounting · **FIFO/weighted-avg (lower-of-cost-or-NRV); LIFO (US-only, LIFO reserve + conformity rule, LCM)** · absorption costing + abnormal-idle-capacity expensing · variance capitalization · **E&O reserves** · landed cost.
- Maverick: write-downs/revaluations & cycle-count adjustments `require_human` · SoD vs warehouse custody.

#### 1.10 Lease Accounting Agent  [UB +Data]
JD: ASC 842 / IFRS 16 — classification, ROU/liability schedules, remeasurement.
- Systems: **LeaseQuery, Visual Lease, Nakisa** · ERP lease JE.
- Technical: **ROU-asset & lease-liability schedules** · incremental-borrowing-rate (IBR) determination · remeasurement on modification.
- Domain: **ASC 842 / IFRS 16** · finance-vs-operating classification · **embedded-lease** detection · short-term/low-value elections.
- Maverick: classification judgment flagged · modifications gated.

#### 1.11 Account Reconciliation Agent  [UB +Data]
JD: The independent "reconcile" duty — reconciles BS accounts, ages items, certifies completeness.
- Systems: **BlackLine, FloQast** · bank portals · ERP + all sub-ledgers (read both sides).
- Technical: **reconciliation matching** · reconciling-item aging · subledger-to-GL tie-outs · bank reconciliation.
- Domain: balance-sheet reconciliations · suspense/clearing accounts · escheatment-trigger awareness.
- Maverick: **independence — cannot post the adjustments it finds** (closes the SoD loop) · stale items escalate.

#### 1.12 Financial Master-Data & CoA Governance Agent  [UB +Data]
JD: Integrity of financial master data — CoA, cost/profit centers, dimensions, entities, bank master.
- Systems: ERP master data · **MDM (SAP MDG, Reltio)** · mapping tables.
- Technical: dedup · **local↔group CoA mapping** · validation rules · dimension governance.
- Domain: chart-of-accounts design · cost/profit-center hierarchies · legal-entity structure.
- Maverick: all master-data changes `require_human` (drives every report) · SoD vs transaction recording.

### Tower 2 — FP&A

#### 2.1 FP&A / Management-Reporting Agent  [UB +Data]
JD: Budget vs actuals, variance analysis with narrative, board/management reporting, KPIs.
- Systems: **Anaplan, Workday Adaptive, Pigment** (EPM) · ERP actuals · BI (Power BI/Tableau/Looker).
- Technical: **variance/bridge analysis** · driver-based models · SQL + advanced Excel · board-deck building (PowerPoint).
- Domain: budgeting/planning · **unit economics & KPIs** · management reporting · cohort analysis.
- Maverick: cite the source query · state assumptions · read-only on the plan of record.

#### 2.2 Forecasting Agent  [UB +Data]
JD: Driver-based revenue/expense/headcount forecasts, scenario & sensitivity modeling, backtesting.
- Systems: EPM (Adaptive/Anaplan) · FRED / market-data feeds.
- Technical: **driver-based & statistical forecasting** (Python: statsmodels/Prophet) · scenario/sensitivity modeling · **backtesting & error reporting**.
- Domain: forecasting methodology · seasonality · confidence intervals.
- Maverick: label estimates · methodology + confidence stated · sandboxed compute.

#### 2.3 Cash-Flow & Liquidity Forecasting Agent  [UB +Data]
JD: The 13-week cash forecast, working-capital analysis, liquidity/runway.
- Systems: bank feeds (Plaid, Modern Treasury) · TMS · AP/AR sub-ledgers.
- Technical: **13-week direct cash-flow model** · working-capital metrics (**DSO/DPO/DIO/CCC**) · burn/runway.
- Domain: liquidity management · cash-conversion cycle.
- Maverick: cannot sweep/transfer (feeds Treasury) · assumptions explicit.

#### 2.4 CapEx & Capital-Planning Agent  [UB +Data]
JD: Capital budgeting & appraisal — business cases, ROI, capex tracking, post-investment review.
- Systems: EPM/capital-planning · ERP (capex) · procurement (capex POs).
- Technical: **NPV / IRR / payback / discounted-payback** · business-case modeling · capex-vs-actual tracking.
- Domain: capital budgeting · capex-vs-opex classification · hurdle rates / WACC.
- Maverick: capital approval `require_human` per DoA · hands assets to FA.

#### 2.5 Workforce & Headcount-Cost Planning Agent  [UB +Data]
JD: People-cost planning — headcount plans, comp modeling, attrition, plan-to-actual.
- Systems: HRIS (read — Workday/BambooHR) · EPM · payroll actuals.
- Technical: **compensation modeling** (salary/bonus/benefits/payroll-tax/equity loading) · hiring-plan phasing · attrition modeling.
- Domain: workforce planning · span-of-control · cost-per-head.
- Maverick: high-PII · read-only HRIS · comp data least-privilege.

### Tower 3 — Treasury

#### 3.1 Treasury & Cash-Management Agent  [UB +Data]
JD: Daily cash positioning, proposes sweeps/funding, monitors debt covenants.
- Systems: **Kyriba** (TMS) · **Modern Treasury, Plaid** (bank aggregation) · bank portals · payment rails (**Fedwire, ACH/NACHA, RTP, SWIFT MT→ISO 20022 / MX**).
- Technical: **cash positioning** across accounts · covenant calculation · short-term liquidity forecasting · **bank-fee analysis (AFP codes)** · pooling (ZBA/notional).
- Domain: liquidity & working capital · **debt covenants** · **SOFR / post-LIBOR (term SOFR, ARRC fallbacks)** · bank-account management (BAM) / FBAR · **ISO 20022 migration**.
- Regulatory: bank KYC.
- Maverick: **propose-not-send** (denies wire/ACH/release) · dual approval over DoA threshold · covenant breach → alert.

#### 3.2 Investments / Portfolio Agent  [UB +Data]
JD: Manages the corporate investment portfolio per the IPS — researches, prices, proposes allocations.
- Systems: **Interactive Brokers (IBKR — already wired)** · **Bloomberg Terminal** · custodian APIs.
- Technical: **portfolio analytics** (yield, **duration & convexity, OAS, yield-to-worst**, credit) · pricing · **investment accounting (ASC 320 HTM/AFS/trading, ASC 321 equity, ASC 326-30 AFS credit losses)** · **MMF Rule 2a-7**.
- Domain: money-market & **fixed-income** instruments · the **Investment Policy Statement** · FINRA/SEC basics for corporate investing.
- Maverick: **trade-propose-not-execute** (denies order tools, verbatim from `finance.toml`) · IPS limit enforcement · egress pinned to IBKR hosts.

#### 3.3 FX & Hedging Agent  [UB +Data]
JD: Quantifies currency exposure, proposes hedges, supports hedge-accounting docs.
- Systems: IBKR/bank FX · ERP exposure data · FX-rate feeds.
- Technical: **exposure quantification** (transaction, translation/**net-investment**, economic) · **hedge-effectiveness testing** · instruments (forwards, options, collars, **cross-currency swaps, NDFs**).
- Domain: **ASC 815 / IFRS 9 hedge accounting + ASU 2017-12** (the three hedge types; portfolio-layer; contemporaneous designation) · SOFR transition.
- Maverick: hedge execution `require_human` · effectiveness method cited.

#### 3.4 Capital Markets & Debt Agent  [UB +Data]
JD: Debt/lease schedules, interest/amortization, covenant compliance, refinancing models.
- Systems: debt register · market-rate feeds · agent/bank statements.
- Technical: **effective-interest amortization** · refinancing/issuance models · covenant tests (**leverage, FCCR, DSCR/ICR**) · borrowing-base/maturity-ladder.
- Domain: **ASC 470 (modification vs extinguishment 10% test, issuance costs), ASC 470-20 + ASU 2020-06 (convertibles), ASC 815-15 (embedded derivatives)** · SOFR · capital structure · credit ratings.
- Maverick: covenant breaches escalate · any draw/issuance `require_human`.

### Tower 4 — Tax

#### 4.1 Tax Provision Agent  [UB +Data]
JD: ASC 740 — current/deferred provision, ETR reconciliation, deferred-tax balances, tax footnote.
- Systems: **ONESOURCE Tax Provision, Corptax** · ERP trial balance · prior returns.
- Technical: **current & deferred tax computation** · **effective-tax-rate reconciliation** · DTA/DTL roll-forward · valuation-allowance analysis.
- Domain: **ASC 740 / IAS 12** · book-tax differences · **uncertain tax positions (ASC 740-10)** · **OECD Pillar Two / GloBE 15% min tax, GILTI/FDII/BEAT, §163(j), CAMT** · valuation-allowance (4 sources) · intraperiod allocation (740-20) · APB 23.
- Maverick: positions cite authority · uncertain positions flagged · ties to the GL provision JE.

#### 4.2 Tax Compliance & Filing-Prep Agent  [UB +Data]
JD: Prepares (not files) income, sales & use, VAT/GST returns; validates nexus/taxability.
- Systems: **Avalara, Vertex, Sovos** (indirect tax) · ONESOURCE · ERP.
- Technical: **nexus & taxability determination** · return preparation · tax-collected-vs-remitted reconciliation.
- Domain: **sales & use / VAT / GST / income tax** · jurisdiction rules · filing calendar.
- Regulatory: IRS, state & local, multi-jurisdiction indirect tax.
- Maverick: **filing & remittance always `require_human`** · jurisdiction rule cited.

#### 4.3 Transfer Pricing Agent  [UB +Data]
JD: Tests intercompany pricing for arm's-length, maintains BEPS documentation.
- Systems: benchmarking DBs (**TP Catalyst / RoyaltyStat**) · intercompany ledger.
- Technical: **arm's-length / comparables analysis** · TP-method selection · adjustment modeling.
- Domain: **OECD BEPS** · master file / local file / **CbCR** · TP methods (CUP, TNMM, etc.).
- Maverick: method & comparables cited · adjustments routed to Consolidations.

### Tower 5 — Risk, Controls & Assurance

#### 5.1 SOX / Internal Controls (ICFR) Agent  [UB +Assess]
JD: Maintains the RCM, tests control operating effectiveness, tracks deficiencies, monitors SoD/ITGCs.
- Systems: **AuditBoard, Workiva, ServiceNow GRC** · the **Maverick audit log** (as control evidence).
- Technical: **control testing & sampling** · evidence evaluation · **SoD-conflict analysis** · ITGC testing (access/change/ops).
- Domain: **SOX §302/§404** · **COSO 2013** (5 components/17 principles) · the Risk-Control Matrix · COBIT/ITGC.
- Maverick: **independence (read-only)** · the assessment flow (`start_assessment`→`answer_question`→`finalize_assessment`) — *today's shipped templates are `pia`/`aira`/`vendor_risk`; `sox_control`/`itgc` are templates to author* · deficiency = finding for a human owner.

#### 5.2 Internal Audit Agent  [UB +Assess]
JD: Risk-based audit planning, fieldwork, workpapers, findings, follow-up.
- Systems: **AuditBoard, TeamMate+** · all finance systems (read).
- Technical: risk-based audit planning · workpaper drafting · sampling & testing.
- Domain: **IIA Global Internal Audit Standards (2024/2025)** · audit methodology · three-lines model · CAATs / data analytics · QAIP · root-cause analysis.
- Maverick: read-only (no operational capability) · evidence-cited · risk-ranked.

#### 5.3 External-Audit / PBC Liaison Agent  [UB +Assess]
JD: Manages the prepared-by-client list, packages evidence, tracks open items.
- Systems: auditor data-request portals · the evidence collector (`soc2.py`) · the signed audit chain (`maverick audit verify`).
- Technical: evidence extraction & packaging · PBC tracking.
- Domain: **PCAOB / external-audit support** · audit-readiness.
- Maverick: external send `require_human` · data minimization in shares.

#### 5.4 Fraud Detection Agent  [UB +Data]
JD: Hunts financial fraud — ghost vendors/employees, duplicate/split payments, expense abuse.
- Systems: GL/AP/payroll (read) · vendor/employee master · case management.
- Technical: **Benford's Law · Beneish M-score · Altman Z-score** · duplicate/round-dollar/just-under-threshold detection · SQL forensics · vendor-bank-change detection.
- Domain: **occupational fraud (ACFE fraud tree)** · fraud triangle · **AU-C 240 / SAS 145** (ex-SAS 99) · FSF screens (Beneish, **Dechow F-score**, Altman) vs transactional tests · link analysis/entity resolution (shared bank/address).
- Maverick: outputs are **risk-ranked leads, never accusations** · base rates stated · routed to a human investigator.

#### 5.5 Anomaly Detection Agent  [UB +Data]
JD: Continuous unsupervised monitoring of transaction streams for statistical outliers.
- Systems: GL/AP/AR transaction feeds (read/stream) · the audit log.
- Technical: **unsupervised outlier detection** (statistical/ML) · time-series analysis · baseline modeling · SQL/streaming.
- Domain: transaction-monitoring patterns (manual-JE spikes, post-close/weekend entries).
- Maverick: tuned to reviewable alert volume (budget-bounded) · every alert carries its baseline.

#### 5.6 Financial Risk / ERM Agent  [UB]
JD: Maintains the enterprise risk register + KRIs, quantifies exposure, drafts risk reporting.
- Systems: GRC risk register · BI.
- Technical: **risk scoring** · KRI design · exposure quantification (VaR basics).
- Domain: **COSO ERM / ISO 31000** · financial risks (liquidity, credit, market, concentration).
- Maverick: read-only over operations · methodology cited.

#### 5.7 Credit Risk Agent  [UB +Data]
JD: Sets/recommends customer credit limits, scores creditworthiness, drafts allowance estimates.
- Systems: AR sub-ledger · **credit bureaus (D&B, Experian)** · payment history.
- Technical: **credit scoring** · **CECL allowance modeling** · AR-portfolio risk analysis.
- Domain: credit analysis · trade-credit terms.
- Regulatory: **FCRA fairness** if consumer credit data (routes to privacy bias checks).
- Maverick: limit changes `require_human`.

#### 5.8 AML / Financial-Crime Agent  [UB +Assess]
JD: Customer-side financial-crime — KYC/CDD, transaction monitoring, SAR drafting.
- Systems: **OFAC SDN, Dow Jones, ComplyAdvantage** (screening) · transaction-monitoring platform · case management.
- Technical: **ML-typology / transaction monitoring** · alert triage · KYC/CDD/EDD · PEP screening.
- Domain: **BSA/AML 5 pillars** · **FinCEN CDD rule + CTA beneficial-ownership (BOI)** · OFAC (SDN, 50% rule, licenses) · **SAR (30/60-day) / CTR ($10k aggregation, structuring)** · 314(a)/(b) · FATF typologies · TM engines (Actimize, Verafin).
- Regulatory: FinCEN.
- Maverick: **SAR filing is a human act** · customer blocking gated · independent of the business line.

### Tower 6 — Procurement & Vendor

#### 6.1 Procurement & Spend-Analysis Agent  [UB +Data]
JD: Spend cube, savings/consolidation, contract-compliance, PO drafting.
- Systems: **Coupa, SAP Ariba, Ramp** · ERP spend.
- Technical: **spend-cube analysis** · maverick-spend/off-contract detection · SQL.
- Domain: P2P · category sourcing · savings/should-cost.
- Maverick: PO issuance `require_human` · SoD vs AP & vendor master.

#### 6.2 Vendor Master & Vendor-Risk Agent  [UB +Assess]
JD: Vendor onboarding & master-data integrity — dedup, bank-detail validation, sanctions screening.
- Systems: ERP vendor master · **OFAC / Dow Jones / ComplyAdvantage (KYB)** · tax-ID validation (W-9/W-8).
- Technical: dedup · **bank-detail validation** · **sanctions/PEP screening** · `start/answer/finalize_assessment` (vendor_risk).
- Domain: TPRM · vendor onboarding · beneficial-ownership.
- Maverick: **bank-detail changes always `require_human`** (BEC-fraud intercept) · sanctions hit blocks onboarding · SoD vs AP.

### Tower 7 — External & Investor Reporting

#### 7.1 Financial / SEC Reporting Agent  [UB]
JD: Drafts financial statements + footnotes, the 10-K/10-Q, and XBRL tagging.
- Systems: **Workiva** · SEC **EDGAR** · consolidation output.
- Technical: **XBRL / iXBRL tagging** · disclosure-checklist execution · financial-statement assembly · tie-to-trial-balance.
- Domain: US GAAP · **Reg S-X / S-K** · 10-K/10-Q (MD&A, risk factors, footnotes).
- Regulatory: SEC reporting.
- Maverick: filing `require_human` · §302/§906 certification is a human act.

#### 7.2 Investor-Relations / Earnings Agent  [UB]
JD: Earnings releases, board/investor decks, non-GAAP reconciliations, Q&A prep.
- Systems: IR CRM · market-data feeds · prior IR materials.
- Technical: earnings-materials drafting · **non-GAAP reconciliation (Reg G)** · consensus/estimate tracking.
- Domain: IR · **Reg FD** (no selective disclosure) · non-GAAP measures.
- Maverick: external release `require_human` · Reg FD discipline · forward-looking statements flagged.

#### 7.3 Equity & Stock-Based-Comp Agent  [UB +Data]
JD: Cap-table maintenance, ASC 718 stock-comp expense, dilution, 409A support.
- Systems: **Carta, Pulley** (cap table) · payroll (RSU/ESPP tax) · ERP comp JE.
- Technical: **ASC 718 expense** (Black-Scholes / lattice valuation) · forfeiture-rate estimation · dilution & waterfall analysis.
- Domain: **ASC 718 / IFRS 2** · options/RSUs/ESPP · **409A** valuation support.
- Maverick: ties to payroll-tax on vesting · 409A human-owned.

#### 7.4 Statutory & Local-GAAP Reporting Agent  [UB]
JD: Per-jurisdiction statutory statements, GAAP-to-local adjustments, local filings.
- Systems: statutory-reporting tools · local filing portals · per-entity ledgers.
- Technical: **GAAP-to-local-GAAP/stat adjustments** · entity-by-entity mapping.
- Domain: **local GAAP** per jurisdiction · statutory filing requirements & calendars.
- Maverick: filing `require_human` · ties to Consolidations & Master-Data mapping.

### Vertical packs (skills delta when enabled)

- **SaaS unit economics:** ARR/MRR/NRR & churn math · product analytics (Amplitude/Mixpanel) · usage-billing systems.
- **Project / WIP costing:** percentage-of-completion accounting · project-accounting ERP (e.g., Procore, Sage Intacct Construction).
- **Fund & grant accounting:** **ASC 958 / ASU 2016-14** (NFP; ex-"FASB 116/117") · **GASB 34** (gov) · **Uniform Guidance 2 CFR 200 / Single Audit** · restricted-fund tracking.
- **Regulatory capital (banks/insurers):** **Call Reports / FR Y-9C / FINREP-COREP** · **Basel / Solvency II** capital math · regulatory-reporting tools.
- **Cost allocation (ABC):** activity-based costing · driver modeling.
- **Escheatment:** multistate unclaimed-property rules · UPExchange-style filing.

---

### Council-added agents
*(Finance seats the council flagged as missing; folded into the roster. New dimension tags shown: delivery `[S]`/`[C]`/`[K]`, `{proficiency}`.)*

- **Treasury Payments / Disbursements Agent — the custody node** — executes/releases *approved* payments; positive-pay, sanctions-at-payment, payment-rail ops. *Systems:* Kyriba / Modern Treasury / bank portals `[C]` · Fedwire/ACH-NACHA/RTP/SWIFT-ISO 20022. *Maverick:* the **custody** seat in the four-way SoD — `release_payment`/`wire` is `require_human`, sealed from AP (records) and the GL. *Cert:* CTP-equivalent.
- **Model Risk Management / Validation Agent (SR 11-7)** `[+Data]{expert}` — independently validates the suite's models (CECL, VaR, ASC 718, forecasting, anomaly ML). *Domain:* **SR 11-7** validation, conceptual-soundness review, backtesting/benchmarking, outcome analysis. *Maverick:* independent of the model owners.
- **Pension & Benefits-Accounting Agent (ASC 715)** — DB/OPEB obligation, actuarial gain/loss, funded status, 401(k) **Form 5500** + plan audit. *Domain:* ASC 715/712, ERISA plan accounting.
- **ESG Controllership Agent** — the controllership/data side of sustainability (dedup with Strategy 7.3, which owns external disclosure). *Domain:* **GHG Protocol Scope 1/2/3**, CSRD/ESRS data, **limited-vs-reasonable assurance** readiness, controls over non-financial data.
- **Government-Contract & Cost-Accounting Agent** — for gov contractors. *Domain:* **FAR Part 31, CAS, DCAA** incurred-cost & indirect-rate, provisional/final rates.

---

## IT / GRC / Privacy / Security / AI-Governance suite

47 agents ([it-grc-agent-suite.md](it-grc-agent-suite.md)). Cross-cutting: these mostly
**operate the platform's own shipped engines** (the Shield, capabilities, signed audit,
governance, `ai_act`/`dpia`/`ropa`/`dsar`/`soc2`/`compliance`) — a baseline skill here is
fluency in those primitives and their CLIs.

### Tower 1 — AI Governance & Agent Oversight

#### 1.1 AI Inventory & Registry Agent  [UB]
JD: Inventory of AI systems/models/agents — owner, purpose, data, risk tier, lifecycle.
- Systems: model registries (MLflow, HF Hub) · `fleet.py` (the live roster) · `domain.py` packs · CMDB.
- Technical: metadata harvesting · model/agent lineage · the DomainProfile schema.
- Domain: AI inventory practice · EU AI Act system definitions · NIST AI RMF "Map".
- Maverick: read-only over fleet/packs/configs.

#### 1.2 AI Risk Assessment (AIRA) Agent  [UB +Assess]
JD: NIST AI RMF / EU AI Act risk assessment of an AI system.
- Systems: the assessment engine (`_AIRA`).
- Technical: `start/answer/finalize_assessment` scoring · evidence-cited findings.
- Domain: **NIST AI RMF** (Govern/Map/Measure/Manage) · EU AI Act risk tiers · bias/robustness/security concepts.
- Maverick: drafts findings; never approves.

#### 1.3 EU AI Act Conformity Agent  [UB +Assess]
JD: Classify risk tier, report Art 12/14/50 posture, assemble the high-risk conformity scaffold.
- Systems: `ai_act.py`, `compliance.py`.
- Technical: risk-tier classification · **Annex IV technical-documentation** assembly · conformity checklist.
- Domain: **EU AI Act** (Art 5 prohibited, Annex III high-risk, Art 50 transparency, GPAI).
- Regulatory: EU AI Act, GPAI Code of Practice.
- Maverick: classifies; a human attests conformity.

#### 1.4 Model & Agent Card / Transparency Agent  [UB]
JD: Model/agent cards — intended use, limitations, data provenance, eval results; AI-content marking.
- Systems: HF model cards · model registry.
- Technical: model-card authoring · eval-result reporting · training-data provenance documentation.
- Domain: **Model Cards / Datasheets for Datasets** · Art 50 transparency.
- Maverick: AI-generated-content marking.

#### 1.5 Bias & Fairness Evaluation Agent  [UB +Data]
JD: Evaluate consequential-decision systems for bias; produce the bias-audit export.
- Systems: fairness toolkits (**Fairlearn, AIF360**) · the eval harness.
- Technical: **disparate-impact metrics** (four-fifths, demographic parity, equalized odds) · statistical significance testing.
- Domain: fairness definitions · adverse impact.
- Regulatory: **NYC LL144** (independent bias audit; **impact-ratio**, incl. intersectional), **Colorado AI Act (SB 24-205)**, **Illinois (amended IHRA)**, EEOC (Title VII/ADA), **EU AI Act Annex III**, **ISO 42001**.
- Maverick: bias-audit export; no protected-class proxies.

#### 1.6 Agent Oversight / Supervisor Agent  [UB]
JD: The live operator over the fleet — monitor, approve/deny/pause/kill, quarantine.
- Systems: `governance.py`, `fleet.py`, `quarantine.py`, `killswitch.py`, the consent dashboard.
- Technical: policy evaluation · approve/deny/pause/kill · seal/quarantine ops · audit reading.
- Domain: **human oversight (Art 14)** · the control-plane model · the three-rung seal model.
- Maverick: holds the parent capability; cannot widen any grant.

#### 1.7 AI Incident Response Agent  [UB]
JD: Triage AI incidents (harmful output, jailbreak, drift), contain, run the PIR.
- Systems: Shield events + the audit log · `quarantine.py`/`killswitch.py`.
- Technical: incident triage/severity · containment · post-incident review.
- Domain: AI-incident taxonomy · jailbreak/drift patterns · the OWASP LLM Top 10.
- Maverick: containment `require_human`; independent of the incident's cause.

### Tower 2 — Privacy / Data Protection

#### 2.1 DPIA / PIA Agent  [UB +Assess]
JD: GDPR Art 35 DPIA + ISO 29134 PIA — processing description, risk register, measures.
- Systems: **OneTrust** · `dpia.py` + `_PIA`.
- Technical: `generate_dpia` · necessity/proportionality analysis · risk-register construction.
- Domain: **GDPR Art 35**, ISO 29134 · the agent-on-personal-data risk set.
- Maverick: residual-risk sign-off is the DPO's.

#### 2.2 ROPA / Records Agent  [UB]
JD: GDPR Art 30 Records of Processing Activities.
- Systems: OneTrust · `ropa.py`.
- Technical: `generate_ropa` · data-flow capture.
- Domain: **GDPR Art 30** · data categories/recipients/transfers/retention.

#### 2.3 Data-Subject Rights (DSAR) Agent  [UB]
JD: Access/portability (Art 15/20) and erasure (Art 17) fulfillment.
- Systems: `dsar.py`, `audit/erase.py` · DSAR portals.
- Technical: `export_subject_data` · `erase_subject` · identity verification · cross-system data location.
- Domain: **GDPR Art 15/17/20**, CCPA access/delete.
- Maverick: erasure `require_human` (irreversible); legal-hold overrides erasure.

#### 2.4 Data Mapping & Classification Agent  [UB +Data]
JD: Discover & classify personal/sensitive data; map data flows.
- Systems: data-discovery (**BigID**, OneTrust) · `safety/pii_detector.py`.
- Technical: PII discovery/classification · data-flow mapping · sensitivity tagging.
- Domain: data-classification schemes · **special-category data (Art 9)**.

#### 2.5 Consent Management Agent  [UB]
JD: Data-subject consent by purpose/category, withdrawal, cookie consent.
- Systems: consent platforms (**OneTrust CMP**) · `safety/consent.py`.
- Technical: purpose/category consent records · withdrawal handling · cookie scanning.
- Domain: GDPR/ePrivacy consent · CCPA opt-out.
- Regulatory: GDPR, ePrivacy/PECR, CCPA/CPRA.

#### 2.6 Breach Response & Notification Agent  [UB]
JD: Assess a breach, run the 72-hour clock, draft regulator + subject notices.
- Systems: incident/case mgmt · the audit log.
- Technical: breach-severity assessment · the 72h clock · notification drafting.
- Domain: **GDPR Art 33/34** · state breach laws · harm assessment.
- Maverick: notifying a regulator/subject is a hard-floor human act.

#### 2.7 Cross-Border Transfer Agent  [UB]
JD: Map transfers, check adequacy/SCCs, run the Transfer Impact Assessment.
- Systems: `enterprise.py` egress lock · `ropa.py`.
- Technical: transfer mapping · TIA · SCC selection.
- Domain: **GDPR Chapter V** · adequacy · **SCCs / Schrems II / TIA**.

#### 2.8 Retention & Minimization Agent  [UB]
JD: Retention schedules, deletion enforcement, anonymization.
- Systems: `audit/retention.py`, `privacy.py`.
- Technical: schedule design · enforcement · anonymization/pseudonymization.
- Domain: **GDPR 5(1)(c)/(e)**; the retention-vs-legal-hold interplay.

### Tower 3 — GRC core: Risk, Policy & Compliance

#### 3.1 Multi-Framework Compliance Agent  [UB +Assess]
JD: Posture across SOC 2 / ISO 27001 / HIPAA / PCI / NIST; control mapping + gap analysis.
- Systems: **Vanta, Drata, AuditBoard** · `soc2.py`, `compliance.py`.
- Technical: control mapping · framework crosswalks · gap analysis · evidence collection.
- Domain: **SOC 2 TSC · ISO 27001:2022 (Annex A) · HIPAA Security Rule · PCI-DSS v4.0.1 · NIST CSF 2.0 / 800-53 · HITRUST CSF · ISO 42001 (AI MS) · CIS Controls v8.1**.
- Maverick: never marks a control effective without seeing evidence.

#### 3.2 Evidence / Audit-Readiness Agent  [UB +Assess]
JD: Continuously collect control evidence; assemble the auditor package.
- Systems: GRC platforms · `collect_soc2_evidence`, `audit/export` (CEF).
- Technical: continuous evidence collection · auditor-package assembly.
- Domain: audit readiness · evidence types/sufficiency.
- Maverick: external send gated.

#### 3.3 Risk Management / ERM Agent  [UB]
JD: Enterprise risk register + KRIs; scoring; treatment tracking.
- Systems: GRC risk register (**ServiceNow GRC, LogicGate, Archer**).
- Technical: risk scoring (likelihood×impact) · KRI design · heat maps.
- Domain: **COSO ERM, ISO 31000, NIST RMF**.

#### 3.4 Policy Management Agent  [UB]
JD: Policy lifecycle — author, review, version, attestation, exceptions.
- Systems: policy mgmt (PolicyTech, Confluence).
- Technical: policy lifecycle · attestation tracking · policy-to-control mapping.
- Domain: policy frameworks · exception governance.

#### 3.5 Control Testing & Monitoring Agent  [UB +Assess]
JD: Test control operating effectiveness; continuous control monitoring + drift detection.
- Systems: GRC · `governance.py`, `soc2.py` probes.
- Technical: control testing · sampling · continuous control monitoring · drift detection.
- Domain: design vs operating effectiveness · ITGC · COBIT.
- Maverick: reads the platform's own controls as evidence.

#### 3.6 Regulatory Change Management Agent  [UB]
JD: Track regulatory changes; map to affected controls; assess impact.
- Systems: reg-intelligence feeds (Thomson Reuters Regulatory Intelligence) · `CourtListener` · `web_search`.
- Technical: change tracking · control-impact mapping.
- Domain: horizon scanning · regulatory taxonomies.

### Tower 4 — Internal Audit & Assurance

#### 4.1 Internal Audit Agent  [UB +Assess]
JD: Risk-based planning, fieldwork, workpapers, findings, follow-up.
- Systems: **AuditBoard, TeamMate+**.
- Technical: risk-based planning · workpaper drafting · sampling & testing.
- Domain: **IIA Global Internal Audit Standards (2024) · COBIT 2019 · three-lines model** · CAATs (IDEA/ACL→Diligent, Alteryx) · root-cause analysis.
- Maverick: read-only, independent.

#### 4.2 Controls Assurance & SoD Agent  [UB]
JD: Independent control verification + SoD/access-conflict monitoring across the fleet.
- Systems: `capability.py` grants · IAM.
- Technical: **SoD-conflict scanning** · access-grant review · control verification.
- Domain: SoD matrices · least-privilege.
- Maverick: read-only.

#### 4.3 External-Audit / PBC Liaison Agent  [UB +Assess]
JD: Manage the SOC 2 / ISO PBC list, package evidence, track open items.
- Systems: evidence collector · auditor data-request portals.
- Technical: PBC management · evidence packaging.
- Domain: SOC 2 / ISO 27001 audit process · `maverick audit verify` as tamper-evidence.
- Maverick: external send gated.

### Tower 5 — Third-Party / Vendor Risk

#### 5.1 Vendor Risk Assessment Agent  [UB +Assess]
JD: TPRM assessment — security, privacy, resilience.
- Systems: TPRM (**OneTrust, Whistic, SecurityScorecard**) · `_VENDOR_RISK`.
- Technical: `start/answer/finalize_assessment` · **SIG/CAIQ** questionnaire review · SOC 2/ISO report analysis.
- Domain: TPRM · fourth-party risk · concentration risk.

#### 5.2 Subprocessor & DPA Agent  [UB]
JD: Subprocessor registry + change-notification; DPA terms.
- Systems: subprocessor registry · CLM (DPAs).
- Technical: subprocessor tracking · change-notification · DPA-term extraction.
- Domain: **GDPR Art 28** · subprocessor obligations.

#### 5.3 Continuous Vendor Monitoring Agent  [UB +Data]
JD: Monitor vendors for breaches, SOC 2 expiry, posture changes.
- Systems: security ratings (**SecurityScorecard, BitSight**) · breach feeds.
- Technical: posture monitoring · expiry tracking · re-assessment triggers.

### Tower 6 — Security Operations

#### 6.1 Runtime Threat Detection (Agent Shield)  [UB]
JD: Prompt-injection/jailbreak/exfil detection at runtime; canaries; unicode filtering.
- Systems: the Agent Shield (`safety/{jailbreak_heuristics,remote_scan,canaries,unicode_filter}.py`).
- Technical: injection/jailbreak/exfil detection · canary tokens · unicode-attack filtering.
- Domain: **OWASP LLM Top 10** · prompt-injection taxonomy · RAG poisoning.
- Maverick: kernel chokepoint (fail-open per rule 1).

#### 6.2 SIEM / Detection & Alert-Triage Agent  [UB +Data]
JD: Forward events to the SIEM, correlate, triage alerts, enrich.
- Systems: **Splunk, Microsoft Sentinel, Elastic** · `audit/export` (CEF).
- Technical: **SPL / KQL** detection rules · log correlation · alert triage · enrichment.
- Domain: **detection engineering · MITRE ATT&CK** · SOC operations.
- Maverick: suppress/close gated (hard floor).

#### 6.3 Security Incident Response Agent  [UB]
JD: IR lifecycle — triage → contain → eradicate → recover → PIR.
- Systems: SOAR (**Splunk SOAR, Tines**) · `quarantine.py`/`killswitch.py`.
- Technical: IR lifecycle · severity matrix · containment · forensics · chain-of-custody.
- Domain: **NIST 800-61 · SANS IR · MITRE ATT&CK**.
- Maverick: containment `require_human`.

#### 6.4 Threat Intelligence Agent  [UB]
JD: Ingest threat intel/IOCs/advisories; correlate; brief the SOC.
- Systems: **MISP** · threat feeds · VirusTotal.
- Technical: IOC analysis · TTP mapping · threat correlation.
- Domain: CTI · MITRE ATT&CK · the Diamond Model.

### Tower 7 — AppSec & Supply Chain

#### 7.1 Secret Scanning Agent  [UB +Build]
JD: Detect secrets in code/logs/config; redact before egress.
- Systems: `safety/secret_detector.py` · GitHub secret scanning · **TruffleHog, Gitleaks**.
- Technical: secret detection/redaction · entropy analysis · pre-commit hooks.
- Domain: secret types · rotation hygiene.

#### 7.2 SCA / Dependency & License Agent  [UB +Build]
JD: Dependency CVEs + license risk + SBOM.
- Systems: **Snyk, Dependabot, OWASP Dependency-Check** · `license_scan.py` · **CycloneDX/SPDX** SBOM.
- Technical: CVE triage (**CVSS/EPSS** + reachability) · SBOM generation · license classification.
- Domain: **supply-chain security · SLSA** · license families (copyleft/permissive).

#### 7.3 SAST / Secure Code Review Agent  [UB +Build]
JD: Static analysis + secure code review of diffs.
- Systems: **Semgrep, CodeQL, SonarQube** · `reviewer.py`, `/security-review`, Copilot review.
- Technical: SAST rule authoring · secure code review · vuln-class detection (injection/authz/crypto).
- Domain: **OWASP Top 10 / ASVS · CWE** · secure SDLC.

#### 7.4 Supply-Chain / MCP & Plugin Trust Agent  [UB +Build]
JD: Vet MCP servers & plugins before install — pinning, manifest, provenance.
- Systems: `mcp_registry.py` (`pin_sha256`), `plugin_manifest.py` · **Sigstore/cosign**.
- Technical: dependency/plugin vetting · signature/provenance verification · pinning.
- Domain: **SLSA** · supply-chain attacks (typosquatting, dependency confusion).
- Maverick: install gated.

### Tower 8 — Vulnerability & Threat Management

#### 8.1 Vulnerability Management Agent  [UB +Data]
JD: Aggregate scanner findings, prioritize, track remediation.
- Systems: **Tenable, Qualys, Wiz, Rapid7** · cloud CSPM.
- Technical: vuln aggregation · prioritization (**CVSS/EPSS + reachability + KEV**) · remediation-SLA tracking.
- Domain: vuln-management lifecycle · CISA KEV.

#### 8.2 Patch Management Agent  [UB]
JD: Patch cadence/compliance, maintenance windows, remediation verification.
- Systems: **MECM (ex-SCCM), Intune / Windows Autopatch, Tanium, BigFix** · Linux patching (**Ansible, Red Hat Satellite**) · the asset inventory.
- Technical: patch-compliance tracking · maintenance-window planning.
- Domain: patch cadence · change control.
- Maverick: patching `require_human`.

#### 8.3 Attack-Surface & Pen-Test Agent  [UB +Build]
JD: Map external attack surface, coordinate pen tests, red-team the agents' own controls.
- Systems: ASM (**Censys, Shodan**) · `safety/remote_scan.py`, `chaos.py`.
- Technical: attack-surface mapping · pen-test coordination · recon.
- Domain: offensive-security basics · **threat modeling (STRIDE)**.

### Tower 9 — Identity & Access Management

#### 9.1 Joiner-Mover-Leaver (Provisioning) Agent  [UB]
JD: Orchestrate access provisioning/deprovisioning on lifecycle events.
- Systems: **Okta, Microsoft Entra ID, SailPoint** · HRIS · SCIM.
- Technical: provisioning/deprovisioning · **SCIM** · role assignment · JML automation.
- Domain: identity lifecycle · **RBAC/ABAC**.
- Maverick: grant/revoke `require_human` (hard floor); orchestrates an org process.

#### 9.2 Access Review / Recertification Agent  [UB]
JD: Periodic access recertification + least-privilege review (humans *and* agents).
- Systems: IGA (**SailPoint, Saviynt**) · `capability.py` grants.
- Technical: certification campaigns · least-privilege review · SoD scanning.
- Domain: access governance · entitlement review.
- Maverick: revoke is human.

#### 9.3 Privileged Access (PAM) Agent  [UB]
JD: Just-in-time privileged access, session control, expiry enforcement.
- Systems: **CyberArk, HashiCorp Vault, Teleport** · `capability.py` (`max_risk`/`expires_at`).
- Technical: JIT access · session management · secret/credential vaulting.
- Domain: privileged-access governance.
- Maverick: capability **expiry is enforced at `permits()`** (an expired grant is denied at use-time); the gap to build is a **mid-session revocation sweep + a revocation list** for un-expired grants.

#### 9.4 Authentication / SSO Agent  [UB]
JD: SSO/MFA coverage & configuration; auth posture.
- Systems: Okta/Entra · `oidc.py`, `proxy_auth.py`, `mcp_oauth.py`.
- Technical: **SAML / OIDC / OAuth2 / SCIM** · MFA config · SSO troubleshooting (alg-confusion, token validation).
- Domain: federation · Zero Trust.

### Tower 10 — IT Operations & Resilience

#### 10.1 Asset & Configuration (CMDB) Agent  [UB +Data]
JD: Asset/config inventory, baselines, drift — incl. database infrastructure.
- Systems: **ServiceNow CMDB** · cloud inventory · **Oracle/PostgreSQL/SQL Server** estates.
- Technical: asset/config discovery · drift detection · **DBA basics — install & configure Oracle 23ai, backup/restore, query, index/tune**.
- Domain: ITIL configuration management · infrastructure topology.

#### 10.2 Change Management Agent  [UB]
JD: Change request → impact → approval → audit → rollback.
- Systems: ServiceNow/Jira Change · `governance.py` (approval) · `checkpoint.py` (rollback).
- Technical: change-request workflow · impact assessment · CAB support.
- Domain: **ITIL change management**.
- Maverick: approval `require_human`.

#### 10.3 Observability / SRE Agent  [UB +Build]
JD: Monitor health/SLOs, tune alerts, drive reliability.
- Systems: **Datadog, Grafana, Prometheus, Sentry, PagerDuty** · `observability.py`, `health.py`, `circuit_breaker.py`.
- Technical: **SLO/SLI design** · alerting · dashboards · on-call/runbooks.
- Domain: **SRE practices** · error budgets.

#### 10.4 Backup & Disaster-Recovery Agent  [UB]
JD: Backup policy, point-in-time recovery, DR drills, BCP.
- Systems: backup (**Veeam, Rubrik**) · cloud snapshots · `checkpoint.py`/`job_queue.py`.
- Technical: backup policy · PITR · DR drills · **RPO/RTO** design.
- Domain: BC/DR · **ISO 22301**.
- Maverick: restore/failover gated.

#### 10.5 Service Desk / ITSM Agent  [UB +Reach]
JD: Ticketing, request fulfillment, KB, SLA — the employee IT front door.
- Systems: **ServiceNow, Jira Service Management, Zendesk** · channels · `intake.py`.
- Technical: ticket triage/deflection · request fulfillment · KB authoring · SLA tracking.
- Domain: **ITIL service management**.
- Maverick: AI disclosure; escalate sensitive.

### Council-added agents
*(GRC/security seats the council flagged as missing. Full profiles below.)*

#### C1 Cloud Security / CSPM-CNAPP Agent  [UB +Build]
JD: Owns cloud and Kubernetes security posture — assesses misconfiguration, drift, and attack paths across clouds and recommends remediation to the owner.
- Systems: **Wiz, Prisma Cloud, Orca, Microsoft Defender for Cloud** `[C]` · cloud-native (AWS Security Hub/GuardDuty, Azure Defender, GCP SCC) · IaC (Terraform/CloudFormation).
- Technical: **CSPM / CIEM / CWPP** · **CIS Benchmarks** · IaC drift detection · **Kubernetes security (OPA/Gatekeeper, Falco), container image scan (Trivy/Grype)** · multi-cloud config review · attack-path analysis.
- Domain: cloud shared-responsibility model · identity-first cloud security · workload/network segmentation.
- Regulatory: **CIS · NIST 800-53 · SOC 2 · FedRAMP** control mappings.
- Maverick: read + recommend; **remediation is human-gated** (no auto-change to cloud config); assurance stays independent and read-only.

#### C2 DLP / Data-Protection Agent  [UB]
JD: Designs and tunes data-loss-prevention policy across channels and surfaces insider-risk for a human owner.
- Systems: **Microsoft Purview, Forcepoint, Netskope** `[C]` · CASB/SSE/SASE platforms · email/endpoint/cloud DLP.
- Technical: **DLP policy across email/endpoint/cloud/SaaS** · **CASB/SSE/SASE** architecture · data classification/labeling · exfiltration-pattern detection · insider-risk/UEBA tuning.
- Domain: data classification · egress control (complements the platform's own enterprise egress-lock).
- Regulatory: **GDPR/CCPA** data-protection · **PCI-DSS** cardholder-data flows · HIPAA ePHI.
- Maverick: policy drafted for a human owner; **blocking/quarantine actions are gated**; never reads protected data outside its scope.

#### C3 DFIR / Digital-Forensics Agent  [UB +Build]
JD: Memory/disk forensics and triage collection on a confirmed incident; preserves the evidentiary record.
- Systems: **Velociraptor, Volatility 3, Plaso, KAPE** `[S]` · EDR telemetry · SIEM.
- Technical: **memory/disk forensics · triage collection · timeline analysis · chain-of-custody · malware triage** · IOC extraction · forensic imaging (hashing/write-blocking).
- Domain: **NIST 800-86** · incident forensics · evidence integrity.
- Regulatory: chain-of-custody / evidentiary standards · breach-investigation discipline.
- Maverick: read + collect only — **no remediation**; chain-of-custody recorded on the signed audit chain; containment proposals go to the human (quarantine/kill is gated).

#### C4 Business-Continuity / Resilience Agent  [UB]
JD: Owns BIA and resilience governance — RTO/RPO targets, crisis playbooks, and tabletop/DR-test orchestration.
- Systems: BC/DR planning tooling · the platform's `checkpoint.py`/`job_queue.py` (durable recovery) · the DR-tech agent (10.4) for execution.
- Technical: **business-impact analysis (BIA)** · **RTO/RPO** governance · crisis-management runbooks · tabletop & DR-test orchestration · dependency mapping.
- Domain: operational resilience · **ISO 22301 · NIST 800-34 · DORA** (financial-sector resilience).
- Regulatory: **DORA, ISO 22301** attestations · sector continuity mandates.
- Maverick: plans drafted for human ownership; a declared invocation of continuity/failover is human-gated; recovery uses durable checkpoints.

#### C5 GRC-Automation / Continuous-Compliance Agent  [UB +Build]
JD: The engineering side of GRC — builds automated evidence collectors and continuous-compliance scoring so controls are tested continuously, not at audit time.
- Systems: **Vanta/Drata-style** automation · the platform `soc2.py` (evidence) + `compliance.py` (coverage) · cloud/SaaS/identity APIs.
- Technical: **automated evidence collectors · control-to-test mapping · integration health monitoring · continuous-compliance scoring** · drift alerting.
- Domain: control automation · evidence sufficiency · the control-to-framework crosswalk.
- Regulatory: **SOC 2, ISO 27001:2022, NIST CSF 2.0** continuous-monitoring expectations.
- Maverick: builds collectors in the sandbox; **never disables or closes a control/finding**; collected evidence is immutable and human-attested.

#### C6 Email-Security / Phishing & Insider-Threat Agent  [UB]
JD: Triages phishing/BEC, tunes email authentication, and surfaces insider-risk signals (phishing is the #1 initial-access vector).
- Systems: **Proofpoint, Abnormal, Mimecast** `[C]` · the secure email gateway · UEBA platforms.
- Technical: **BEC/phishing triage** · **DMARC/DKIM/SPF** alignment · header/URL/attachment analysis · **UEBA/insider-risk** tuning · quarantine-policy review.
- Domain: social-engineering TTPs · email authentication · insider-threat indicators.
- Regulatory: anti-phishing/BEC reporting · evidence handling for insider cases.
- Maverick: triage + recommend; **release/quarantine/block is human-gated**; insider signals inform, never auto-discipline (HR/legal own consequences).

#### C7 AI Red-Team / Model-Security Agent  [UB +Build]
JD: The offensive counterpart to the defensive Shield — adversarially tests models and agents for jailbreak, injection, extraction, and poisoning.
- Systems: **garak · Microsoft PyRIT · promptfoo** `[S]` · the eval/benchmark harness · the Shield (as the system-under-test).
- Technical: **adversarial-ML** — jailbreak/prompt-injection/extraction/model-inversion/data-poisoning · attack-prompt corpora · automated red-team runs · finding write-ups.
- Domain: **MITRE ATLAS** · **NIST AI 100-2** (adversarial ML taxonomy) · OWASP LLM Top 10.
- Regulatory: AI-safety testing expectations (EU AI Act robustness, NIST AI RMF measure).
- Maverick: tests in an isolated compartment; findings go to a human owner; **never weaponizes findings against production**; respects the kernel's self-modification floor.

#### C8 SaaS Security Posture (SSPM) Agent  [UB]
JD: Assesses SaaS misconfiguration, risky OAuth grants, and least-privilege across the SaaS estate.
- Systems: **AppOmni, Obsidian** `[C]` · SaaS admin APIs (M365, Google Workspace, Salesforce, Slack) · the IdP.
- Technical: **SaaS misconfiguration scanning · OAuth-grant / third-party-app risk · least-privilege review across SaaS** · shadow-SaaS discovery · token/secret hygiene.
- Domain: SaaS shared-responsibility · OAuth scope risk · SaaS-to-SaaS integration risk.
- Regulatory: **SOC 2 / ISO 27001** SaaS-control mappings · data-residency in SaaS.
- Maverick: read + recommend; **revoking a grant or changing SaaS config is human-gated**; assurance independent.

---

## Sales / GTM suite

45 agents ([sales-gtm-agent-suite.md](sales-gtm-agent-suite.md)). Cross-cutting: every
customer-facing agent carries the **[+Reach]** bundle — and the **consent/suppression +
AI-disclosure discipline** is a baseline skill, not optional.

### Tower 1 — Marketing & Demand Generation

#### 1.1 Demand-Gen & Campaign Agent  [UB +Reach +Data]
JD: Plan/orchestrate multi-channel campaigns, draft assets, measure pipeline contribution.
- Systems: **Marketo, HubSpot, Marketing Cloud Account Engagement (ex-Pardot), Salesforce Marketing Cloud** (MAP/ESP) · **Google/Meta/LinkedIn Ads** · the channels layer.
- Technical: campaign building · audience segmentation · UTM/attribution setup · A/B testing.
- Domain: demand gen · funnel math · channel mix · budget pacing.
- Maverick: spend cap; launch `require_human`; consent/suppression floor.

#### 1.2 Content & SEO Agent  [UB +Reach]
JD: Content briefs/drafts (blog/landing/whitepaper), SEO, the content calendar.
- Systems: CMS / **Wix** (MCP) · **Semrush, Ahrefs, Google Search Console** · GA4.
- Technical: keyword research · on-page SEO · content optimization · schema markup.
- Domain: SEO/SEM · content strategy · E-E-A-T.
- Maverick: brand/claims review before publish; WCAG.

#### 1.3 Social & Community Agent  [UB +Reach]
JD: Draft/schedule social, monitor mentions, moderate community.
- Systems: **Sprout Social, Hootsuite** · Bluesky/Mastodon/Discord (shipped) · LinkedIn/X.
- Technical: social scheduling · listening/sentiment · engagement.
- Domain: social strategy · community management · platform norms.
- Maverick: post gated; brand voice; AI disclosure.

#### 1.4 Product Marketing Agent  [UB]
JD: Positioning, messaging, launch plans, battlecards, competitive framing.
- Systems: `knowledge_search` · the competitive-intel agent (8.3).
- Technical: messaging frameworks · battlecard authoring · win/loss synthesis.
- Domain: positioning · segmentation/personas · pricing/packaging input.

#### 1.5 Brand & Creative Agent  [UB]
JD: Brand-voice guardrails, creative briefs, design production.
- Systems: **Figma** (MCP) · Google Drive · Adobe Creative Cloud.
- Technical: creative-brief authoring · design generation · brand-asset management.
- Domain: brand systems · visual/voice consistency.

#### 1.6 Lifecycle & Nurture Agent  [UB +Reach]
JD: Lifecycle/nurture email sequences; deliverability & list hygiene.
- Systems: the email channel (shipped) · MAP (Marketo/HubSpot).
- Technical: sequence building · **deliverability** (SPF/DKIM/DMARC, warmup, bounce/spam management) · list segmentation.
- Domain: lifecycle marketing · email best practice.
- Maverick: **consent/suppression hard floor**; CAN-SPAM/GDPR; rate caps.

#### 1.7 Marketing Ops & Analytics Agent  [UB +Data]
JD: Attribution, funnel analytics, lead scoring, MAP hygiene.
- Systems: MAP · CRM · BI (Looker/Tableau) · GA4.
- Technical: attribution modeling · **lead-scoring models** · MAP/CRM data hygiene · SQL.
- Domain: marketing analytics · MQL/SQL definitions.

#### 1.8 Events & Webinar Agent  [UB +Reach]
JD: Event/webinar planning, invites, registration, follow-up.
- Systems: **Google Calendar** (live) · event platforms (ON24, Cvent, Zoom Webinars).
- Technical: event setup · invite/registration flows · follow-up sequences.
- Domain: field/event marketing.
- Maverick: sends gated; suppression honored.

#### 1.9 PR & Comms Agent  [UB +Reach]
JD: Press materials, announcements, media monitoring.
- Systems: **Cision, Meltwater** · `web_search`.
- Technical: press-release drafting · media-list building · monitoring.
- Domain: PR · crisis comms · messaging.
- Maverick: external release gated.

### Tower 2 — Sales Development

#### 2.1 Inbound Qualification Agent  [UB +Reach]
JD: Qualify inbound leads (MQL→SQL), respond fast, route, book meetings.
- Systems: **Salesforce / HubSpot** (CRM) · Google Calendar · the channels layer · `intake.py`.
- Technical: lead qualification (BANT/MEDDIC-lite) · routing · meeting booking.
- Domain: inbound SDR motion · SLAs.
- Maverick: AI disclosure; consent on follow-up.

#### 2.2 Outbound Prospecting (SDR) Agent  [UB +Reach]
JD: Research accounts/contacts, draft personalized outreach, run sequences.
- Systems: **ZoomInfo, Apollo, 6sense** (enrichment/intent) · **Outreach, Salesloft** · the channels layer.
- Technical: account/contact research · personalization · multi-touch sequencing.
- Domain: outbound motion · ICP targeting.
- Maverick: **consent/suppression hard floor** + AI disclosure are the whole game; lead-source provenance.

#### 2.3 Lead Enrichment & Account-Research Agent  [UB +Data]
JD: Enrich firmographic/technographic data, intent signals, account/stakeholder research.
- Systems: **ZoomInfo, Clearbit, Apollo, 6sense** · `web_search`.
- Technical: enrichment · technographic/intent analysis · stakeholder mapping.
- Domain: account research · data provenance/privacy.

#### 2.4 Sequencing & Cadence Agent  [UB +Reach]
JD: Orchestrate multi-touch cadences, A/B test, protect deliverability.
- Systems: `scheduler.py`/`worker.py` · **Outreach, Salesloft** · the channels layer.
- Technical: cadence design · A/B testing · deliverability protection.
- Maverick: sends only inside the gated sequence.

#### 2.5 Meeting-Booking Agent  [UB +Reach]
JD: Book demos, hand off to the AE with context.
- Systems: **Google Calendar** (live), Calendly/Chili Piper · CRM.
- Technical: scheduling · round-robin routing · handoff prep.

### Tower 3 — Sales / AE & Deal Desk

#### 3.1 Account-Plan & Research Agent  [UB]
JD: Account intelligence, stakeholder maps, account/territory plans.
- Systems: **Salesforce** · `web_search` · enrichment.
- Technical: account planning · stakeholder/org mapping · whitespace analysis.
- Domain: enterprise-sales methodology.

#### 3.2 Discovery & Solution Agent  [UB]
JD: Discovery prep, qualification, solution mapping, demo scripts.
- Systems: CRM · `knowledge_search` (product).
- Technical: discovery frameworks (**MEDDIC/MEDDPICC, SPIN, Challenger**) · solution mapping.
- Domain: value selling · the product.

#### 3.3 Proposal & Quoting (CPQ) Agent  [UB]
JD: Generate quotes/proposals, configure products, apply the price book.
- Systems: **Salesforce CPQ, DealHub, Conga** · `knowledge_search` (pricing).
- Technical: product configuration · quote generation · proposal assembly.
- Domain: pricing/packaging · discounting rules.
- Maverick: list-price auto; discounts → Deal Desk (3.4).

#### 3.4 Deal Desk & Approvals Agent  [UB +Data]
JD: Enforce the discount/term approval matrix, check margin, route approvals.
- Systems: CPQ · `governance.py` (risk-floor gate today; **DoA/amount-aware policy to build**) · the legal domain.
- Technical: **margin analysis** · approval-matrix routing · non-standard-term detection.
- Domain: deal desk · DoA matrices · revenue/margin policy.
- Maverick: discounts beyond floor `require_human`; never approves itself.

#### 3.5 Sales Engineering / POC Agent  [UB]
JD: Technical Q&A, POC plans, security questionnaires.
- Systems: `knowledge_search` · the GRC compliance agent (security Qs) · CRM.
- Technical: technical demos · POC design · **security-questionnaire response (SIG/CAIQ)**.
- Domain: the product architecture · integration patterns.

#### 3.6 Negotiation & Closing-Support Agent  [UB]
JD: Negotiation prep, objection handling, mutual close plans.
- Systems: CRM · `knowledge_search`.
- Technical: negotiation prep · objection libraries · mutual-action-plan drafting.
- Domain: negotiation tactics · closing methodology.

#### 3.7 Contract / Order-Form Agent  [UB]
JD: Assemble the order form, redline vs standard, hand off to CLM.
- Systems: **DocuSign, Ironclad** (CLM/e-sign) · the legal domain.
- Technical: order-form assembly · redline vs standard.
- Domain: commercial terms · the contract playbook.
- Maverick: never signs; non-standard terms → legal/human.

### Tower 4 — Revenue Operations

#### 4.1 Pipeline Analytics & Forecasting Agent  [UB +Data]
JD: Pipeline health, deal inspection, forecast roll-up.
- Systems: **Salesforce** · BI (Tableau/Looker) · **Clari/BoostUp** (forecasting).
- Technical: pipeline analytics · deal inspection · **forecast methodology** (weighted/commit) · SQL.
- Domain: forecasting discipline · pipeline hygiene.
- Maverick: forecast commit is human; feeds finance.

#### 4.2 Territory, Quota & Capacity Agent  [UB +Data]
JD: Territory design, quota setting, capacity/coverage modeling.
- Systems: CRM · territory-planning (Fullcast, Anaplan) · the finance headcount agent.
- Technical: territory modeling · quota setting · capacity/coverage analysis.
- Domain: sales-capacity planning.

#### 4.3 Commissions & Incentive-Comp Agent  [UB +Data]
JD: Calculate commissions/attainment against the comp plan; disputes.
- Systems: **Xactly, CaptivateIQ, Spiff** · CRM · finance payroll.
- Technical: commission calculation · attainment tracking · dispute resolution.
- Domain: incentive-comp plans · SPM.
- Maverick: payout gated (finance); SoD vs closing.

#### 4.4 CRM Data Hygiene & Governance Agent  [UB +Data]
JD: Dedup, enrich, validate, and govern CRM fields & data quality — **fix Salesforce errors**.
- Systems: **Salesforce** (Admin) · HubSpot · enrichment · `pii_detector`.
- Technical: **fixing Salesforce errors — Flow (record-triggered/scheduled/screen) + fault paths & Process-Builder→Flow migration, SOQL/SOSL, governor limits (CPU/SOQL-101/DML), Apex triggers & async (Batch/Queueable/Future), debug logs + Developer Console, validation & duplicate rules + dedup, Data Loader, deployment (change sets/SFDX/unlocked packages/Gearset), sharing model (OWD/roles/FLS), Optimizer/Health Check** · CRM data modeling. *(Admin + Developer depth; see also the council-added Salesforce Admin/Dev agent.)*
- Domain: CRM data governance · field/object model.
- Maverick: bulk writes gated; privacy; change audit.

#### 4.5 Lead Routing & Assignment Agent  [UB]
JD: Route leads/accounts by rules, round-robin, enforce SLAs.
- Systems: **Salesforce, LeanData, Chili Piper**.
- Technical: routing-rule configuration · round-robin · SLA tracking.
- Domain: lead-to-account matching.

#### 4.6 GTM Systems & Process Agent  [UB +Build]
JD: Manage the GTM tech stack, workflow automation, RevOps process.
- Systems: the GTM stack APIs · **Zapier/Workato/Tray** · Salesforce admin.
- Technical: integration/automation building · process documentation.
- Domain: RevOps architecture.
- Maverick: config changes gated.

### Tower 5 — Customer Success & Account Management

#### 5.1 Onboarding & Implementation Agent  [UB +Reach]
JD: Onboarding plans, kickoff, time-to-value.
- Systems: **Gainsight, Catalyst, ChurnZero** · PM tools · the channels layer.
- Technical: onboarding-plan design · TTV tracking · milestone management.
- Domain: customer onboarding · adoption.

#### 5.2 Adoption & Health-Scoring Agent  [UB +Data]
JD: Usage/adoption analytics, health scores, risk signals.
- Systems: **Amplitude, Pendo** · CS platform.
- Technical: **health-score modeling** · usage analytics · risk-signal detection.
- Domain: product-usage analytics · CS metrics.

#### 5.3 Renewals Agent  [UB +Reach]
JD: Renewal forecasting, notices, paperwork prep.
- Systems: CRM/CS · finance.
- Technical: renewal forecasting · notice/paperwork drafting.
- Domain: renewals motion · NRR/GRR.
- Maverick: never auto-renew or commit price (→ Deal Desk).

#### 5.4 Expansion / Upsell Agent  [UB +Reach]
JD: Whitespace analysis, expansion plays, upsell timing.
- Systems: CS + product analytics.
- Technical: whitespace analysis · expansion-play design · propensity modeling.
- Maverick: outreach gated.

#### 5.5 Churn-Risk & Save Agent  [UB +Data]
JD: Churn prediction, save plays, escalation.
- Systems: CS + product analytics.
- Technical: **churn prediction** · save-play design · escalation.
- Domain: retention analytics.

#### 5.6 QBR & Business-Review Agent  [UB]
JD: QBR decks, success plans, executive business reviews.
- Systems: BI · Google Drive/Figma (decks) · CS platform.
- Technical: QBR-deck building · success-plan drafting · ROI/value storytelling.

#### 5.7 Advocacy & References Agent  [UB +Reach]
JD: Identify advocates, manage references, case studies, reviews.
- Systems: CS platform · review sites (G2) · the channels layer.
- Technical: advocate identification · case-study drafting · review generation.
- Maverick: outreach gated + consented.

### Tower 6 — Customer Support & Service

#### 6.1 Support Triage & Deflection Agent  [UB +Reach]
JD: Tier-1 support — triage, KB answers, deflect, escalate.
- Systems: **Zendesk, Intercom, Salesforce Service Cloud** · the channels layer · `knowledge_search` · `intake.py`.
- Technical: ticket triage · KB-grounded answering · escalation routing.
- Domain: support operations · CSAT drivers.
- Maverick: AI disclosure; escalate the novel; no commitments.

#### 6.2 Knowledge-Base & Self-Service Agent  [UB]
JD: Author/maintain the KB & help content from tickets + product changes.
- Systems: support platform + CMS · `knowledge_search`.
- Technical: KB authoring · gap detection · content maintenance.
- Maverick: publish gated.

#### 6.3 Escalation & Customer-Incident Agent  [UB +Reach]
JD: Manage escalations + customer-facing status comms during incidents.
- Systems: support + **Statuspage** · the GRC incident agent.
- Technical: escalation management · status-comms drafting.
- Maverick: external posts gated.

#### 6.4 Voice-of-Customer & CSAT Agent  [UB +Data]
JD: Run CSAT/NPS, synthesize sentiment, route to product.
- Systems: survey tools (Delighted, Qualtrics) · product.
- Technical: survey design · **sentiment analysis** · feedback synthesis.
- Maverick: surveys gated + consented.

### Tower 7 — Partnerships & Channel

#### 7.1 Partner Recruitment & Onboarding Agent  [UB +Assess]
JD: Recruit, vet, and onboard partners.
- Systems: **PRM (Crossbeam, PartnerStack)** · the GRC vendor-risk assessment.
- Technical: partner research · `start/answer/finalize_assessment` (vendor_risk) · onboarding.
- Domain: channel/partner programs.

#### 7.2 Partner Enablement & Co-Sell Agent  [UB +Reach]
JD: Enable partners, support co-sell, manage deal registration.
- Systems: PRM · **Crossbeam** (account mapping) · CRM.
- Technical: enablement-content delivery · co-sell support · deal-registration management.
- Domain: co-sell motion.

#### 7.3 Marketplace & Alliance Agent  [UB]
JD: Manage marketplace listings (AWS/Azure/GCP/app stores) and alliances.
- Systems: cloud marketplace consoles · app-store consoles.
- Technical: listing management · private-offer setup.
- Domain: marketplace/alliance strategy.
- Maverick: listing changes gated.

### Tower 8 — GTM Enablement, Strategy & Intelligence

#### 8.1 Sales Enablement & Content Agent  [UB]
JD: Playbooks, battlecards, enablement content, rep onboarding/certification.
- Systems: **Highspot, Seismic** (enablement) · LMS · `knowledge_search`.
- Technical: playbook/battlecard authoring · enablement-content management · certification design.

#### 8.2 Conversation Intelligence & Coaching Agent  [UB +Data]
JD: Analyze recorded calls, coach reps, track talk-track adherence.
- Systems: **Gong, Chorus** · the voice channel · CRM.
- Technical: call analysis · coaching-insight extraction · talk-track/risk-language detection.
- Domain: sales coaching · methodology adherence.
- Maverick: **call-recording consent** (two-party-consent states) — hard floor.

#### 8.3 Competitive & Market-Intelligence Agent  [UB +Data]
JD: Track competitors, win/loss analysis, market/TAM, ICP research.
- Systems: **Klue, Crayon** · `web_search` · CRM (win/loss).
- Technical: competitor tracking · **win/loss analysis** · TAM sizing.
- Domain: competitive strategy · market research.

#### 8.4 GTM Strategy & Planning Agent  [UB +Data]
JD: GTM planning, segmentation, ICP, pricing/packaging analytics.
- Systems: BI · CRM · finance.
- Technical: GTM modeling · segmentation · pricing analytics.
- Domain: GTM strategy · ICP definition.

### Council-added agents
*(the three the brief named — Salesforce-dev, deliverability, RevOps-data — were under-built. Full profiles below.)*

#### C1 Salesforce Admin / Developer Agent  [UB +Build] {expert}
JD: The seat that can actually "fix Salesforce errors" — diagnoses and repairs Flow/Apex/data issues and ships configuration safely.
- Systems: **Salesforce** (Sales/Service Cloud, CPQ→Revenue Cloud/RLM) · **SFDX / unlocked packages / Gearset** · Developer Console / debug logs.
- Technical: **Flow (record-triggered/scheduled/screen) + fault paths · Apex (triggers + async Batch/Queueable/Future) · SOQL/SOSL · governor limits (CPU/SOQL-101/DML) · LWC · deployment (change sets/SFDX/Gearset) · security model (OWD/roles/FLS/sharing)** · validation/duplicate rules · Data Loader · Optimizer/Health Check.
- Domain: CRM data modeling · CPQ→Revenue Cloud migration · org-health remediation.
- Prereq: CRM data model fluency.
- Maverick: config/code ships through the sandbox + review gate; **bulk data writes and destructive deploys are human-gated**; never edits production directly without approval.

#### C2 Marketing-Ops / MarTech Engineer Agent  [UB +Build]
JD: Builds and maintains the marketing-automation and measurement plumbing — programs, scoring, and privacy-safe tracking.
- Systems: **Marketo / HubSpot / Marketing Cloud Account Engagement (MCAE)** · **GA4** · server-side GTM · Meta/Google ads APIs.
- Technical: **MAP program build · lead scoring / lifecycle · GA4 + Consent Mode v2 · server-side GTM · Meta CAPI / enhanced conversions · attribution plumbing** · webhook/API integrations.
- Domain: lifecycle marketing · attribution modeling · martech architecture.
- Regulatory: **consent-mode / cookie-consent** integration · CAN-SPAM/CASL plumbing.
- Maverick: builds in the sandbox; **sends and ad-spend changes are gated**; consent/suppression is wired in by construction, never bypassed.

#### C3 Deliverability / Email-Infrastructure Agent  [UB]
JD: Protects sender reputation and inbox placement — the owner the brief named that was smeared across other seats.
- Systems: DNS / email-auth records · **Google Postmaster Tools / Microsoft SNDS** · seed-list/inbox-placement tools (GlockApps/Litmus) · the ESP.
- Technical: **SPF/DKIM/DMARC enforcement (p=reject) · BIMI/VMC · Google/Yahoo 2024 bulk-sender rules (one-click unsub RFC 8058, <0.3% complaint rate) · IP warmup · seed-list/inbox-placement testing** · bounce/complaint analysis.
- Domain: deliverability engineering · reputation management · list hygiene.
- Regulatory: **CAN-SPAM / CASL** · one-click-unsubscribe mandates.
- Maverick: the **consent/suppression floor is absolute** — never sends to an opted-out party; reputation changes are recommended, sends stay gated.

#### C4 Revenue / GTM Data-Engineering Agent  [UB +Build +Data]
JD: The "RevOps engineering" seat — warehouse-native GTM data, models, and activation.
- Systems: **Snowflake / BigQuery** · **reverse-ETL (Census/Hightouch)** · **CDP (Segment/RudderStack)** · dbt · the CRM/MAP.
- Technical: **warehouse-native GTM modeling · reverse-ETL activation · CDP pipelines · dbt funnel models · lead-to-account identity resolution** · data-quality tests on GTM data.
- Domain: funnel/attribution data models · identity resolution · GTM semantic layer.
- Regulatory: PII handling in the warehouse · consent propagation to activation.
- Maverick: builds pipelines in the sandbox; **bulk writes back to systems-of-record are gated**; honors suppression/consent on every activation.

#### C5 Marketing-Privacy / Consent Agent  [UB]
JD: Owns marketing-side consent and privacy — the CMP, do-not-sell, and suppression sync.
- Systems: **CMP (OneTrust)** · **Global Privacy Control (GPC)** signal handling · cookie banners · the MOPS suppression list.
- Technical: **consent capture by purpose/category · GPC · CCPA Do-Not-Sell/Share · cookie consent · suppression sync** across MAP/CRM/ads.
- Domain: consent management · cookie/tracker governance · preference centers.
- Regulatory: **GDPR/ePrivacy · CCPA/CPRA · GPC** · state-privacy wave.
- Maverick: enforces consent/suppression as a hard floor across the GTM suite; **never contacts an opted-out party**; AI disclosure where applicable.

---

## HR / People suite

41 agents ([hr-people-agent-suite.md](hr-people-agent-suite.md)). Cross-cutting baseline:
**special-category-PII handling** (employee data), the **consequential-decision gate**
(agents screen/draft; a human decides hire/fire/promote/pay/discipline), **bias-aware
language + no protected-class proxies**, and the **EU AI Act Art-5 refusal** (no workplace
emotion inference).

### Tower 1 — Talent Acquisition & Recruiting

#### 1.1 Sourcing & Talent-Research Agent  [UB +Reach]
JD: Source candidates, build pipelines, market/talent mapping.
- Systems: **Greenhouse, Lever, Ashby** (ATS) · LinkedIn Recruiter · job boards.
- Technical: Boolean/X-ray sourcing · pipeline building · talent-market mapping.
- Domain: sourcing strategy · candidate-data privacy.
- Maverick: outreach gated; no protected-class targeting.

#### 1.2 Resume Screening & Ranking Agent  [UB +Assess]
JD: Screen/rank applications against job-related criteria; draft a shortlist (Annex-III/LL144).
- Systems: ATS (**Greenhouse, Lever, Workday Recruiting**) · the bias-eval engine.
- Technical: structured screening against **job-related** criteria · **proxy detection/exclusion** · evidence-cited rationale.
- Domain: **structured hiring** · validity · adverse impact (four-fifths).
- Regulatory: **NYC LL144, EU AI Act Annex III, EEOC (Title VII/ADA/ADEA)**.
- Maverick: **L1 ceiling** (drafts only); bias-evaluated; no demographic inference.

#### 1.3 Candidate Engagement & Scheduling Agent  [UB +Reach]
JD: Candidate comms, interview scheduling, status updates, candidate experience.
- Systems: the channels layer + **Google Calendar** (live) · ATS.
- Technical: candidate messaging · interview scheduling/coordination.
- Maverick: AI disclosure; consent on outreach; no commitments.

#### 1.4 Interview & Assessment-Design Agent  [UB]
JD: Structured interview kits, scorecards, job-related assessments, interviewer prep.
- Systems: ATS · assessment platforms (HackerRank, Codility).
- Technical: structured-interview-kit authoring · scorecard design · job-related assessment selection.
- Domain: **structured interviewing** · validity/reliability · bias reduction by design.

#### 1.5 Offer Management Agent  [UB]
JD: Draft offers within comp bands, route approvals, manage acceptance.
- Systems: ATS + comp tools · Total Rewards (4.1).
- Technical: offer drafting · band-compliance checking.
- Domain: offer strategy · comp bands · pay-transparency law.
- Maverick: comp commitment gated (DoA).

#### 1.6 Employer Brand & Recruitment-Marketing Agent  [UB +Reach]
JD: Careers content, job postings, candidate nurture.
- Systems: career-site CMS · the channels layer · ATS.
- Technical: job-posting authoring · **inclusive-language checking** · candidate nurture.
- Regulatory: **EEO** (no discriminatory language in postings).
- Maverick: publish gated.

#### 1.7 Recruiting Ops & Analytics Agent  [UB +Data]
JD: Funnel metrics, time-to-fill, source quality, adverse-impact monitoring.
- Systems: ATS + BI.
- Technical: funnel analytics · **adverse-impact monitoring** (four-fifths across the funnel) · source-quality analysis.
- Domain: recruiting metrics · DE&I funnel analytics.

### Tower 2 — Onboarding & Offboarding

#### 2.1 Onboarding Agent  [UB +Reach]
JD: Pre-boarding, day-1 plans, new-hire paperwork; triggers IT provisioning.
- Systems: **HRIS (Workday, BambooHR, Rippling)** · the IT IAM agent · channels · `intake.py`.
- Technical: onboarding-plan design · paperwork (tax/policy) · provisioning request (→ IAM).
- Maverick: provisioning handed to IT (cross-suite SoD).

#### 2.2 Work-Authorization (I-9 / E-Verify) Agent  [UB]
JD: Work-auth verification, I-9 completeness, immigration/visa tracking.
- Systems: **E-Verify, Tracker I-9** · HRIS.
- Technical: I-9 completeness checking · work-auth/visa tracking.
- Domain: **IRCA / I-9** · visa categories · anti-discrimination (no document abuse).
- Maverick: the verification decision is human; highly sensitive.

#### 2.3 Offboarding & Exit Agent  [UB +Reach]
JD: Offboarding checklist, access-revocation trigger, exit interviews, final-pay handoff.
- Systems: HRIS · IT IAM · finance payroll · channels.
- Technical: offboarding-checklist execution · deprovisioning request · exit-interview synthesis.
- Domain: final-pay law · COBRA · timely access revocation (security).
- Maverick: deprovisioning → IT; final pay → finance.

#### 2.4 Internal Mobility & Transfer Agent  [UB]
JD: Transfers, role changes, internal moves, redeployment.
- Systems: HRIS · the talent-marketplace module.
- Technical: transfer drafting · internal-match analysis.
- Maverick: role/comp change gated (consequential).

### Tower 3 — HR Operations & Shared Services

#### 3.1 HR Helpdesk / Employee-Service Agent  [UB +Reach]
JD: Tier-1 HR Q&A (policy, PTO, benefits), case triage, escalation.
- Systems: **ServiceNow HRSD** · the channels layer · `knowledge_search` · `intake.py`.
- Technical: policy-grounded answering · case triage · escalation.
- Maverick: AI disclosure; **escalate anything sensitive** (ER, comp, medical); never expose another employee's data.

#### 3.2 HRIS & Employee-Records Agent  [UB +Data]
JD: Employee master data, records management, data quality/governance.
- Systems: **Workday, SuccessFactors, BambooHR** · `pii_detector`.
- Technical: HRIS data management · validation · **Workday report/calc-field basics** · data quality.
- Domain: HR data model · special-category privacy.
- Maverick: record changes gated; need-to-know.

#### 3.3 Employment-Verification & Letters Agent  [UB]
JD: Verification of employment, letters (visa/mortgage), references.
- Systems: HRIS · **The Work Number** (verification).
- Technical: verification drafting · letter generation.
- Domain: what may be disclosed; consent for references/comp.
- Maverick: release without authorization gated.

#### 3.4 HR Policy & Document Agent  [UB]
JD: Policy/handbook lifecycle, acknowledgments, e-signatures.
- Systems: policy repo (Drive) · e-sign · the GRC policy agent.
- Technical: policy drafting · acknowledgment tracking · version control.
- Maverick: publish gated.

#### 3.5 HR Compliance & Reporting Agent  [UB]
JD: Mandatory reporting (EEO-1, OSHA 300, ACA, BLS, VETS-4212), retention, audit support.
- Systems: HRIS + reporting portals.
- Technical: compliance-report generation · data extraction.
- Domain: **EEO-1, OSHA 300/300A, ACA 1094/1095, VETS-4212, BLS**.
- Regulatory: EEOC, OSHA, IRS/ACA, DOL.
- Maverick: filing gated.

### Tower 4 — Total Rewards (Comp & Benefits)

#### 4.1 Compensation Analysis & Bands Agent  [UB +Data]
JD: Comp benchmarking, band design, range placement, merit-cycle modeling.
- Systems: **Radford, Mercer, Pave** (survey/comp) · HRIS.
- Technical: comp benchmarking · band design · **merit-cycle modeling** · compa-ratio analysis.
- Domain: comp philosophy · **pay-transparency law** · job architecture.
- Maverick: comp data need-to-know; changes gated (DoA).

#### 4.2 Pay-Equity Agent  [UB +Data]
JD: Pay-equity analysis, disparate-pay detection, remediation modeling.
- Systems: HRIS + comp · the bias-eval engine.
- Technical: **regression-based pay-equity analysis** · disparate-pay detection · remediation modeling.
- Domain: pay equity · **EU Pay Transparency Directive** · state pay laws.
- Maverick: often attorney-client-privileged → restricted compartment; aggregate.

#### 4.3 Benefits Administration Agent  [UB +Reach]
JD: Benefits enrollment, open enrollment, vendor liaison, questions.
- Systems: **benefits platforms (Sequoia, bSwift), carriers** · HRIS.
- Technical: enrollment guidance · open-enrollment support.
- Domain: **ERISA, ACA, COBRA, HIPAA** (health data = Art 9).
- Maverick: health-data privacy; elections gated.

#### 4.4 Leave & Absence Agent  [UB]
JD: FMLA/ADA leave administration, accommodation intake, absence tracking.
- Systems: HRIS + leave platform (AbsenceSoft).
- Technical: leave-eligibility checking · absence tracking · accommodation intake (→ ER 7.4).
- Domain: **FMLA, ADA, PWFA** · state leave laws.
- Maverick: medical-data privacy; eligibility/accommodation decisions human-led.

#### 4.5 Payroll Liaison Agent  [UB]
JD: Feed comp/status changes to finance Payroll, reconcile, resolve queries.
- Systems: HRIS ↔ the finance Payroll agent.
- Technical: payroll-input sync · reconciliation.
- Maverick: **never runs payroll** (finance owns); SoD across HR↔finance.

### Tower 5 — Performance & Talent Management

#### 5.1 Goals & OKR Agent  [UB]
JD: Goal/OKR setting, alignment, progress tracking.
- Systems: **Lattice, 15Five, Workday** (performance).
- Technical: goal/OKR drafting · alignment mapping · progress tracking.

#### 5.2 Performance-Review Agent  [UB +Assess]
JD: Orchestrate the cycle; draft review summaries from documented inputs; calibration support.
- Systems: performance platform · the bias-eval engine.
- Technical: review synthesis from documented inputs · **bias-aware language** · calibration data.
- Domain: performance management · rater-bias awareness (recency/halo).
- Maverick: **L1 ceiling**; never assigns a rating/decision; decision record on the human rating.

#### 5.3 Calibration & Promotion Agent  [UB +Data]
JD: Calibration support, promotion-packet assembly, pay-for-performance modeling.
- Systems: performance + comp.
- Technical: calibration analysis · promo-packet assembly · **adverse-impact check on promotion rates**.
- Maverick: consequential gate; the decision is human.

#### 5.4 Succession & Talent-Review Agent  [UB]
JD: Succession plans, 9-box, high-potential, talent reviews.
- Systems: HRIS + performance.
- Technical: succession-plan drafting · 9-box analysis.
- Domain: talent management; bias-aware (no proxy-based potential).
- Maverick: sensitive/confidential.

#### 5.5 Performance-Improvement & Coaching Agent  [UB]
JD: Draft PIPs and coaching plans; manager guidance.
- Systems: performance platform · ER (7.1).
- Technical: PIP drafting · coaching-plan design.
- Domain: progressive discipline; documentation; dignity.
- Maverick: **delivering it is human-owned**; legal review of PIP/termination paths.

### Tower 6 — Learning & Development

#### 6.1 Learning Content & Curriculum Agent  [UB]
JD: Course/curriculum design, microlearning, content from SMEs.
- Systems: **LMS (Cornerstone, Docebo, Workday Learning)** · authoring (Articulate).
- Technical: **instructional design (ADDIE/Bloom's)** · content authoring · microlearning.

#### 6.2 Skills & Career-Pathing Agent  [UB +Data]
JD: Skills taxonomy, gap analysis, career paths, IDPs.
- Systems: HRIS + skills platform (Gloat, Eightfold).
- Technical: **skills-taxonomy mapping** · gap analysis · IDP drafting.
- Domain: skills-based talent · career architecture.

#### 6.3 Training Delivery & LMS Agent  [UB]
JD: Assign/track training, LMS admin, completion nudges.
- Systems: LMS · channels.
- Technical: training assignment · completion tracking · LMS admin.
- Maverick: low-risk → L3/L4 eligible.

#### 6.4 Compliance-Training Agent  [UB]
JD: Mandatory training (harassment, security, ethics, safety), completion + attestation.
- Systems: LMS · the GRC compliance agent.
- Technical: compliance-training tracking · attestation reporting.
- Domain: mandatory-training requirements (state harassment-training laws).

### Tower 7 — Employee Relations, Compliance & Investigations

#### 7.1 Employee-Relations Agent  [UB]
JD: ER case intake, manager guidance, documentation, trend spotting.
- Systems: ER case mgmt (HR Acuity) · `knowledge_search`.
- Technical: case intake · manager-guidance drafting · trend analysis.
- Domain: ER practice · consistency · documentation.
- Maverick: confidential; escalate; decides no outcomes.

#### 7.2 Investigations Agent  [UB]
JD: Workplace-investigation support — interview plans, evidence organization, neutral report.
- Systems: case mgmt (restricted) · the legal domain.
- Technical: investigation planning · evidence organization · timeline building · neutral report drafting.
- Domain: workplace-investigation protocol · interview techniques.
- Maverick: **independence + strict confidentiality + privilege**; isolated compartment; never concludes.

#### 7.3 Employment-Law Compliance Agent  [UB]
JD: FLSA/FMLA/ADA/Title VII/WARN/state-law compliance; policy/practice review.
- Systems: the legal domain · GRC · `knowledge_search`.
- Technical: compliance checking · risk flagging.
- Domain: **FLSA, FMLA, ADA, Title VII, ADEA, NLRA, WARN** + state law.
- Maverick: drafts for counsel; not legal advice.

#### 7.4 EEO / AAP & Accommodations Agent  [UB]
JD: EEO compliance, affirmative-action plans, ADA/PWFA accommodation interactive process.
- Systems: HRIS · the bias-eval engine · legal.
- Technical: **AAP drafting (OFCCP)** · accommodation-process support · adverse-impact analysis.
- Domain: **EEO, OFCCP/AAP, ADA/PWFA** interactive process.
- Maverick: protected-class data aggregate/compliance-only; interactive process human-led.

#### 7.5 Labor-Relations Agent  [UB]
JD: Union/CBA support, grievances, works councils, NLRA.
- Systems: `knowledge_search` (CBA) · case mgmt.
- Technical: CBA interpretation · grievance tracking.
- Domain: **NLRA · CBA administration · EU works councils / co-determination**.
- Maverick: jurisdiction-aware; sensitive; human-led.

#### 7.6 Ethics & Whistleblower-Triage Agent  [UB]
JD: Hotline intake, triage, routing (SOX §301 for finance matters).
- Systems: the GRC ethics/whistleblower agent · case mgmt.
- Technical: report intake · triage · routing.
- Domain: whistleblower protection · anonymity preservation.
- Maverick: confidential/anonymous-preserving.

### Tower 8 — People Analytics, Workforce Planning & Engagement

#### 8.1 People-Analytics Agent  [UB +Data]
JD: HR metrics, attrition/retention analytics, dashboards, flight-risk.
- Systems: HRIS + BI (**Visier**, Tableau).
- Technical: HR analytics · **attrition/flight-risk modeling** · re-identification protection.
- Domain: people analytics; aggregate-only; flight-risk informs retention, never adverse action.

#### 8.2 Workforce-Planning Agent  [UB +Data]
JD: Headcount/workforce plans, org design, scenario modeling.
- Systems: HRIS · the finance FP&A workforce-cost agent.
- Technical: workforce modeling · org-design analysis · scenario planning.
- Maverick: HR owns the people plan, finance owns the cost (SoD); WARN if layoffs.

#### 8.3 Engagement & Survey Agent  [UB]
JD: Engagement/pulse surveys, consented & aggregated sentiment, action planning.
- Systems: **Culture Amp, Glint, Qualtrics**.
- Technical: survey design · **aggregate sentiment synthesis** (min-response threshold).
- Maverick: **REFUSES individual emotion inference / monitoring (EU AI Act Art 5)** — aggregate-only.

#### 8.4 DEI Analytics & Programs Agent  [UB +Data]
JD: Diversity representation analytics, DEI programs, inclusion metrics.
- Systems: HRIS · BI.
- Technical: representation analytics · inclusion metrics · DEI-program drafting.
- Domain: DEI; **post-SFFA / jurisdiction limits** — aggregate-only, no protected attribute as a selection input.
- Maverick: legal review; no protected-class-based decisions.

#### 8.5 Internal-Communications Agent  [UB +Reach]
JD: Employee communications, announcements, change comms.
- Systems: the channels layer · intranet.
- Technical: comms drafting · audience targeting.
- Maverick: sensitive comms (layoffs, policy) human-approved.

### Council-added agents
*(seats the council flagged as missing; full profiles below.)*

#### C1 Background-Check / FCRA Adverse-Action Agent  [UB]
JD: Runs the background-check process and the FCRA adverse-action sequence — drafts notices, never makes the decision.
- Systems: **Checkr, HireRight** `[C]` · the ATS.
- Technical: adjudication-matrix application · individualized-assessment drafting · dispute tracking · timing-clock management.
- Domain: **FCRA** pre-adverse/adverse-action two-step · **ban-the-box / fair-chance** timing · EEOC arrest-vs-conviction guidance · dispute handling.
- Regulatory: **FCRA, EEOC, state/local fair-chance laws**.
- Maverick: drafts the notices and timeline; **the hire/no-hire decision is human**; uses only job-related criteria, never protected-class proxies.

#### C2 Immigration / Global-Mobility Agent  [UB]
JD: Supports the work-authorization and global-mobility lifecycle (deeper than I-9, which 2.2 owns).
- Systems: immigration case-management · the HRIS · outside immigration counsel.
- Technical: visa-timeline tracking · **LCA / public-access-file** assembly · prevailing-wage checks · expat-assignment + **shadow-payroll** triggers (to finance Payroll).
- Domain: visa lifecycle (**H-1B/L-1/O-1/TN/PERM/green card**) · global-mobility · expat tax interplay.
- Regulatory: **INA/USCIS, DOL (LCA/PERM), IRCA anti-discrimination**, host-country immigration.
- Maverick: prepares filings for counsel/human sign-off; **a filing or status decision is human**; anti-discrimination rules apply.

#### C3 HRIS / HCM Platform-Admin Agent  [UB +Build]
JD: Configures and troubleshoots the HCM platform — the admin depth split out of HRIS records (3.2).
- Systems: **Workday** (business processes, security groups, EIB / Studio / Core Connectors, advanced/matrix reports) · **SuccessFactors** (MDF, RBP, business rules, Integration Center).
- Technical: business-process configuration · security-group/RBP design · **EIB/Studio/Integration-Center** integrations · advanced/matrix reporting · tenant-config troubleshooting.
- Domain: HCM data model · org/position management · effective-dating.
- Regulatory: HR-data privacy (special-category) · SoD in HCM security.
- Maverick: changes ship through the sandbox + review; **production config changes and mass data loads are gated**; employee data stays need-to-know.

#### C4 Workers'-Comp & HR-Safety Agent  [UB]
JD: Owns the HR↔EHS seam — OSHA recordkeeping, WC claims intake, and return-to-work.
- Systems: the OSHA log system · WC carrier/TPA portals · the HRIS · the EHS suite (ops).
- Technical: **OSHA recordability (300/301/300A) + ITA e-submission (1904.41)** · fatality/hospitalization reporting · WC claims intake · return-to-work coordination.
- Domain: workers'-comp administration · OSHA↔FMLA/ADA interplay · modified-duty programs.
- Regulatory: **OSHA 1904, state workers'-comp, FMLA/ADA**.
- Maverick: maintains the log and drafts filings; **regulatory submission is human-gated**; medical data is protected and aggregate where possible.

#### C5 Total-Rewards Equity / LTI Agent  [UB +Data]
JD: Benchmarks and models equity/long-term incentives (ties to finance SBC, 7.3).
- Systems: equity-admin (Carta/Shareworks) · comp-benchmarking (Radford/Mercer/Pave) · the finance SBC seat.
- Technical: RSU/option/ESPP benchmarking · **dilution / burn-rate / overhang** modeling · vesting schedules · mobility & **§83(b)** tax modeling.
- Domain: long-term-incentive design · equity-grant mechanics · total-rewards strategy.
- Regulatory: **ASC 718 (cross-ref finance), §409A, §83(b), §6039** · mobility tax.
- Maverick: models and benchmarks for human decision; **grant/comp changes are gated**; comp data is strictly need-to-know.

---

## Product & Engineering suite

40 agents ([product-engineering-agent-suite.md](product-engineering-agent-suite.md)).
Cross-cutting baseline: **sandbox-mediation (rule 4)**, the **verifier + review ship gate**,
**human-approved merge/release/deploy**, and the **self-modification floor** (never alter the
kernel/`safety`/`capability`/`governance` without human authorization; `self_edit` off).

### Tower 1 — Product Management

#### 1.1 Product Discovery & Research Agent  [UB]
JD: User/market research, problem validation, opportunity assessment, JTBD.
- Systems: `web_search`, `tools/newsapi_tool` · user-feedback sources · `knowledge_search`.
- Technical: research synthesis · opportunity sizing · JTBD interviews.
- Domain: product discovery (Continuous Discovery, JTBD).

#### 1.2 Roadmap & Prioritization Agent  [UB]
JD: Roadmap construction, prioritization, tradeoff analysis.
- Systems: **Jira, Linear, Productboard, Notion**.
- Technical: prioritization frameworks (**RICE, WSJF, Kano**) · roadmap building · tradeoff analysis.
- Maverick: roadmap is human-owned (product decision).

#### 1.3 Requirements & Spec (PRD) Agent  [UB]
JD: PRDs, user stories, acceptance criteria, edge-case enumeration.
- Systems: **Confluence, Notion, Jira, Linear**.
- Technical: PRD authoring · user-story/Gherkin acceptance criteria · edge-case enumeration.
- Domain: product specs · requirements clarity.

#### 1.4 Backlog & Sprint Agent  [UB]
JD: Backlog grooming, sprint planning, ticket hygiene, estimation.
- Systems: **Jira, Linear, ClickUp, Asana**.
- Technical: backlog grooming · sprint planning · estimation support.
- Domain: Agile/Scrum/Kanban.

#### 1.5 Product Analytics & Insights Agent  [UB +Data]
JD: Usage/funnel/retention analytics, experiment analysis, insights.
- Systems: **Amplitude, Mixpanel, PostHog, GA4** · SQL.
- Technical: funnel/retention/cohort analysis · **A/B experiment analysis** (significance, power) · SQL.
- Domain: product analytics · experimentation.

#### 1.6 Customer-Feedback Synthesis Agent  [UB]
JD: Synthesize feedback/reviews/tickets into themes & product signals.
- Systems: support (cross-ref GTM 6.x) · `knowledge_search` · review sites.
- Technical: thematic synthesis · sentiment · signal extraction.

#### 1.7 Launch & Release-Coordination Agent  [UB]
JD: Launch plans, release notes, internal/GTM coordination.
- Systems: GTM suite · Jira/Linear · channels.
- Technical: launch-plan drafting · release-notes authoring.
- Maverick: external comms gated (GTM).

### Tower 2 — Design & UX

#### 2.1 UX Research Agent  [UB]
JD: Usability studies, research synthesis, personas, journey maps.
- Systems: `web_search` · research repos (Dovetail) · `knowledge_search`.
- Technical: usability-study design · research synthesis · persona/journey-map authoring.
- Domain: UX research methods.

#### 2.2 Interaction & UI Design Agent  [UB]
JD: UI design, wireframes, mockups, prototypes; design-to-code handoff.
- Systems: **Figma** (MCP, incl. Code Connect) · `tools/diagram_tool`.
- Technical: UI/wireframe/prototype generation · **design-to-code** handoff.
- Domain: interaction design · design heuristics.

#### 2.3 Design-System Agent  [UB +Build]
JD: Components, design tokens, consistency, design↔code sync.
- Systems: **Figma** (Code Connect) · the codebase (Storybook).
- Technical: component/token management · **design-token sync** · design-system governance.

#### 2.4 Accessibility (a11y) Agent  [UB +Build]
JD: WCAG audits, accessibility fixes, inclusive-design review.
- Systems: `tools/a11y` (shipped) · **axe, Lighthouse** · the codebase.
- Technical: **WCAG 2.2 auditing** · ARIA fixes · screen-reader testing.
- Domain: accessibility (WCAG, Section 508, ADA).

#### 2.5 Content & UX-Writing Agent  [UB]
JD: Microcopy, content design, product voice, localization prep.
- Systems: `knowledge_search` · `tools/translate`.
- Technical: microcopy authoring · content-design systems · i18n prep.

### Tower 3 — Software Engineering (the kernel)

#### 3.1 Implementation / Coding Agent  [UB +Build]
JD: Feature implementation — the core write-test loop against a spec.
- Systems: the kernel (`agent`/`coding_mode`/`edit_format`) · `tools/{apply_patch,ast_edit,code_exec,repo_map}` · the **7 sandbox backends** (+ a `network_policy` egress layer) · Git.
- Technical: **multi-language coding** (Python, TypeScript/JS, Go, Java, Rust, …) · test-first development · debugging · the relevant frameworks.
- Domain: software design · the codebase + its standards.
- Maverick: edit-in-sandbox; opens PRs; **never merges, deploys, or `self_edit`s**.

#### 3.2 Code-Review Agent  [UB +Build]
JD: Review diffs for correctness, simplification, reuse; enforce standards.
- Systems: `reviewer.py` · `/code-review` skill · GitHub Copilot review.
- Technical: diff review · bug/edge-case detection · style/standards enforcement.
- Domain: code-review rubrics · language idioms.

#### 3.3 Refactoring & Tech-Debt Agent  [UB +Build]
JD: Refactor, modernize, reduce duplication, plan/execute debt paydown.
- Systems: `tools/{ast_edit,dep_graph,repo_map}` · the sandbox.
- Technical: **safe refactoring** (AST-level) · dependency upgrades · debt prioritization.

#### 3.4 Debugging & Fix Agent  [UB +Build]
JD: Reproduce, diagnose, fix defects; root-cause analysis.
- Systems: `tools/diagnose`, `code_exec`, the sandbox · `sentry_tool`.
- Technical: reproduction · debugging · **root-cause analysis** · regression-test authoring.

#### 3.5 Test-Authoring Agent  [UB +Build]
JD: Write unit/integration/E2E tests (TDD); raise coverage on risk.
- Systems: `verifier.py` · `code_exec` · `test_impact` · test frameworks (pytest, Jest, Playwright).
- Technical: **TDD** · test-pyramid design · coverage-on-risk.
- Maverick: the anti-test-cheating verifier discipline.

#### 3.6 Code-Documentation Agent  [UB +Build]
JD: Docstrings, API docs, READMEs, comments to house density.
- Systems: `tools/{pandoc_tool,knowledge}` · the codebase.
- Technical: docstring/API-doc authoring (Sphinx, TypeDoc) · README authoring.

### Tower 4 — Quality Engineering

#### 4.1 Test-Strategy Agent  [UB]
JD: Risk-based test plans, coverage strategy, test-pyramid design.
- Systems: `knowledge_search` · `test_impact`.
- Technical: risk-based test planning · coverage strategy.

#### 4.2 Test-Automation Agent  [UB +Build]
JD: Build/maintain automated suites (unit→E2E); reduce flakiness.
- Systems: `code_exec`, the sandbox · **Playwright, Cypress, Selenium**.
- Technical: test-automation engineering · **flakiness reduction** · CI-test integration.

#### 4.3 Eval & Benchmark Agent  [UB +Build]
JD: Run the eval/benchmark harness; track regressions.
- Systems: `benchmarks/` (**SWE-bench, GAIA, τ², terminal-bench**) · `continuous_benchmark.py`.
- Technical: eval-harness operation · regression tracking · pass@k/cost analysis.

#### 4.4 Bug-Triage & Quality-Analytics Agent  [UB +Data]
JD: Triage bugs, defect analytics, flakiness/quality trends.
- Systems: `tools/{jira,linear,sentry_tool}`.
- Technical: bug triage · defect/escape analytics · flakiness trending.

#### 4.5 Release-Readiness & Chaos Agent  [UB +Build]
JD: Release gates/checklists, chaos & resilience testing.
- Systems: `chaos.py` · `benchmarks/` · the sandbox.
- Technical: release-gate execution · **chaos/fault-injection** testing.
- Maverick: the release decision is human.

### Tower 5 — DevOps / Platform / Release

#### 5.1 CI/CD Pipeline Agent  [UB +Build]
JD: Pipeline authoring/maintenance, build/test automation, gate config.
- Systems: **GitHub Actions, GitLab CI** · `deploy/`.
- Technical: pipeline authoring (YAML) · build/test automation · caching/matrix.
- Maverick: never disables a gate (hard floor).

#### 5.2 Infrastructure-as-Code Agent  [UB +Build]
JD: IaC, provisioning, environment config — incl. standing up databases.
- Systems: **Terraform, Pulumi, Helm/Kubernetes** · `tools/{cloudflare_tool,vercel_tool,lambda_tool,s3_tool}` · AWS/Azure/GCP.
- Technical: **IaC authoring** · **provisioning & configuring databases (e.g., stand up Oracle 23ai, Postgres, RDS — install, parameters, backup, HA)** · container orchestration.
- Domain: cloud architecture · the Well-Architected frameworks.
- Maverick: plan-in-sandbox; **apply/provision gated** (human).

#### 5.3 Release & Deployment Agent  [UB +Build]
JD: Cut releases, orchestrate rollouts/canaries, rollback.
- Systems: `deploy/` · **GitHub Actions, Vercel, ArgoCD/Spinnaker** · `checkpoint.py`.
- Technical: release engineering · canary/blue-green rollouts · rollback.
- Maverick: **production deploy = hard floor (human)**.

#### 5.4 Observability & SRE Agent  [UB +Build]
JD: Monitoring, SLOs, alert tuning, reliability *(cross-ref IT-GRC 10.3)*.
- Systems: **Datadog, Grafana, Prometheus, Sentry, PagerDuty** · `observability.py`, `health.py`.
- Technical: **SLO/SLI design** · alert tuning · dashboards · incident on-call.
- Domain: SRE · error budgets.

#### 5.5 Dependency & Supply-Chain Agent  [UB +Build]
JD: Dependency updates, SBOM, vuln remediation *(cross-ref IT-GRC 7.2/7.4)*.
- Systems: `license_scan.py` · `dep_graph` · **Dependabot, Snyk**.
- Technical: dependency updates · SBOM · CVE remediation.
- Maverick: copyleft/critical-CVE deps = hard floor.

### Tower 6 — Data & ML Engineering

#### 6.1 Data-Pipeline / Analytics-Engineering Agent  [UB +Build +Data]
JD: ETL/ELT, transformations, data models, pipeline maintenance.
- Systems: **dbt, Airflow/Dagster** · **Snowflake, BigQuery, Databricks** · `tools/{sql_query,pandas_query,notebook_exec}`.
- Technical: **SQL/dbt modeling** · pipeline orchestration · **querying Oracle/Snowflake/etc. to extract data** · data testing.
- Domain: dimensional modeling · ELT patterns.
- Maverick: prod pipeline changes gated.

#### 6.2 Data-Quality & Governance Agent  [UB +Data]
JD: Data-quality tests, lineage, data contracts *(cross-ref GRC data gov)*.
- Systems: **Great Expectations, Monte Carlo** · warehouses · `pii_detector`.
- Technical: data-quality testing · lineage · data-contract enforcement.

#### 6.3 ML / Model-Development Agent  [UB +Build +Data]
JD: Model development, training, evaluation, experiment tracking.
- Systems: **PyTorch/scikit-learn, MLflow, Weights & Biases** · `tools/{embeddings,huggingface,notebook_exec}` · the sandbox.
- Technical: model development · training/eval · experiment tracking · feature engineering.
- Domain: ML methods · evaluation rigor.
- Maverick: model promotion gated.

#### 6.4 MLOps & Model-Deployment Agent  [UB +Build]
JD: Model serving, monitoring, drift detection, retraining *(model cards/AI risk → IT-GRC T1)*.
- Systems: **SageMaker, Vertex AI, KServe/Seldon** · serving infra.
- Technical: model serving · **drift/performance monitoring** · retraining pipelines.
- Maverick: deploy gated.

#### 6.5 BI & Reporting Agent  [UB +Data]
JD: Dashboards, reports, self-serve analytics.
- Systems: **Looker, Tableau, Power BI** · `tools/{sql_query,spreadsheet}`.
- Technical: dashboard/report building · semantic-layer modeling · SQL.

### Tower 7 — Developer Experience & Productivity

#### 7.1 Technical-Documentation Agent  [UB]
JD: Internal docs, runbooks, ADRs, API references, onboarding guides.
- Systems: `tools/{knowledge,confluence_tool,notion,pandoc_tool}` · the codebase · docs-as-code (MkDocs, Docusaurus).
- Technical: tech-doc authoring · runbook/ADR writing · API-reference generation.

#### 7.2 Internal-Tooling & Scaffolding Agent  [UB +Build]
JD: Codegen scaffolds, internal CLIs/tools, plugin/skill scaffolding.
- Systems: `plugin_scaffold.py`, `skills.py` · the sandbox.
- Technical: scaffolding/codegen · internal-tool building · **authoring SKILL.md** + plugins.

#### 7.3 Engineering-Metrics (DORA) Agent  [UB +Data]
JD: DORA + flow metrics, bottleneck analysis.
- Systems: `git_advanced`, `tools/{jira,linear}` · CI.
- Technical: **DORA metrics** (deploy freq, lead time, MTTR, change-fail rate) · flow metrics · bottleneck analysis.

#### 7.4 Developer-Support / Codebase-Q&A Agent  [UB +Build]
JD: Answer "how does X work / where is Y", onboarding, codebase navigation.
- Systems: `repo_map`, `knowledge_search` · the codebase.
- Technical: codebase navigation/explanation · onboarding support.
- Maverick: read-only.

### Tower 8 — Technical Research & Architecture

#### 8.1 Architecture & Design-Doc Agent  [UB +Build]
JD: System design, ADRs, design reviews, tradeoff analysis.
- Systems: `knowledge_search` · `tools/diagram_tool` · the codebase.
- Technical: **system design** · ADR authoring · design review · diagramming (C4).
- Domain: architecture patterns · scalability/reliability tradeoffs.

#### 8.2 Technical-Investigation / Spike Agent  [UB +Build]
JD: Research spikes, feasibility studies, throwaway PoCs in the sandbox.
- Systems: the sandbox · `web_search` · the reasoning strategies (debate/ToT).
- Technical: feasibility prototyping · spike investigation.
- Maverick: PoCs don't ship without the gate.

#### 8.3 Technology-Evaluation Agent  [UB +Build]
JD: Library/framework/vendor evaluation, build-vs-buy, license screening.
- Systems: `web_search` · `license_scan.py` · `dep_graph`.
- Technical: tech evaluation · build-vs-buy analysis · license/maintenance-health screening.

### Council-added agents
*(shipped tooling, no persona — the "tools there, agent missing" gap. Full profiles below.)*

#### C1 Mobile Engineering Agent  [UB +Build]
JD: Builds native and cross-platform mobile apps (the agent for the already-shipped mobile tools).
- Systems: `tools/android.py`, `tools/ios_sim.py` `[C]` · Xcode/Android Studio · **Fastlane / Xcode Cloud / Gradle**.
- Technical: **Swift/SwiftUI · Kotlin/Jetpack Compose · React Native/Flutter** · mobile CI/release automation · **mobile security (keychain/keystore, cert pinning)** · offline/sync.
- Domain: mobile UX patterns · app lifecycle · push/deep-linking.
- Regulatory: store privacy labels · mobile data-protection (ATT, Play Data Safety).
- Maverick: builds and tests in the sandbox; opens a PR; **App Store / Play release is a hard human floor**; never self-edits.

#### C2 API Design & Contract Agent  [UB +Build]
JD: Designs API contracts and enforces compatibility (the agent for the shipped OpenAPI runner).
- Systems: `tools/openapi_runner.py` `[C]` · schema registries · contract-test harnesses.
- Technical: **OpenAPI 3.1 · GraphQL / Apollo federation · gRPC/protobuf · AsyncAPI** · versioning/deprecation · idempotency/pagination · **contract testing (Pact)**.
- Domain: API design (REST/GraphQL/event) · backward-compatibility · API governance.
- Regulatory: API security (OWASP API Top 10) · data-exposure review.
- Maverick: proposes contracts and tests in the sandbox via PR; **breaking changes require human review**; never self-edits.

#### C3 Database Engineering / DBA Agent  [UB +Build +Data] {expert}
JD: Owns data modeling, performance, and database standups — including the named "Oracle 23ai standup" capability.
- Systems: Oracle / Postgres / SQL Server · `tools/{dynamodb,mongodb,redis,elasticsearch}_tool.py` `[C]` · migration tooling.
- Technical: **data modeling · indexing/partitioning · query optimization (EXPLAIN) · migrations (Flyway/Liquibase/Alembic) · replication/HA/PITR · standing up Oracle 23ai (incl. JSON-relational duality + vector)** · NoSQL data modeling.
- Domain: relational + NoSQL design · transaction isolation · HA/DR topologies.
- Regulatory: data-at-rest encryption · DB access controls (ITGC) · PII handling.
- Maverick: provisions/standups in the sandbox; **schema migrations and production DB changes are human-gated**; never touches a system-of-record without approval; never self-edits.

#### C4 Platform Engineering Agent  [UB +Build]
JD: Builds the internal developer platform — golden paths, environments, and secrets.
- Systems: **Backstage / IDP** · Kubernetes · **Vault / SOPS / sealed-secrets** · cloud-cost (FinOps) tooling.
- Technical: **IDP / golden paths · ephemeral environments · secrets management · FinOps / cloud cost** · self-service scaffolding · paved-road tooling.
- Domain: developer experience · platform-as-a-product · multi-tenancy.
- Regulatory: secrets hygiene · least-privilege platform access.
- Maverick: builds platform components in the sandbox via PR; **provisioning/apply to shared infra is human-gated**; never self-edits the kernel runtime.

#### C5 LLM-Application / Prompt-Engineering Agent  [UB +Build]
JD: Builds LLM-powered product features — Maverick is itself an AI product, so this is distinct from classical ML (6.3/6.4).
- Systems: the LLM/provider layer · vector stores · the eval/benchmark harness · `tools/embeddings`.
- Technical: **RAG pipelines · prompt engineering · eval (RAGAS / LLM-as-judge) · guardrails · latency/cost optimization** · context/window management · tool-use design.
- Domain: applied LLM patterns · retrieval quality · agent/guardrail design.
- Regulatory: AI transparency (Art 50) · eval/robustness evidence (NIST AI RMF).
- Maverick: builds features in the sandbox via PR; **guardrails/safety changes go through review**; respects the self-modification floor — never edits the agent's own runtime/safety/controls.

#### C6 Performance / Load-Engineering Agent  [UB +Build]
JD: Owns non-functional performance — load testing, profiling, and capacity.
- Systems: **k6 · Gatling · JMeter · Locust** · profilers (eBPF/Pyroscope) · APM/observability.
- Technical: **load/stress testing · profiling · Core Web Vitals (INP) · capacity testing** · bottleneck analysis · regression budgets.
- Domain: performance engineering · scalability · capacity planning.
- Regulatory: performance SLAs · resilience-test evidence.
- Maverick: runs tests in the sandbox; reports for human decision; **load against production/shared environments is gated**; never self-edits.

---

## Strategy / Corp Dev / Executive suite

26 agents ([strategy-corpdev-exec-agent-suite.md](strategy-corpdev-exec-agent-suite.md)).
Cross-cutting baseline: **MNPI / ethical-wall discipline** (deal & board work runs in sealed
`quarantine` compartments), **decisions are executive/board-owned**, **Reg FD** (no selective
disclosure), and fluency with the **`/deep-research`** harness.

### Tower 1 — Corporate Strategy & Planning

#### 1.1 Strategy Research & Analysis Agent  [UB] {strong}
JD: Industry/market analysis, strategic frameworks, option generation, strategy memos.
- Systems: `/deep-research` `[C]` · `web_search` `[C]` · `tools/{newsapi_tool,semantic_scholar}` `[C]`.
- Technical: research synthesis `[S]` · strategy-memo authoring `[S]`.
- Domain: **strategy frameworks** (Porter's Five Forces, value chain, 3-horizons, BCG matrix) `[K]`.
- Judgment: signal vs narrative; saying "unverified" when the evidence is thin.

#### 1.2 Scenario-Planning & Wargaming Agent  [UB +Data] {strong}
JD: Scenario construction, competitor/market war-gaming, sensitivity analysis.
- Systems: `web_search` `[C]` · the reasoning strategies (debate/ToT) · finance models `[C]`.
- Technical: scenario construction `[S]` · war-gaming `[S]` · **sensitivity/Monte-Carlo analysis** `[S]`.
- Domain: scenario planning · game-theory basics `[K]`.
- Judgment: avoiding false precision; stating every assumption.

#### 1.3 Business-Model & Portfolio Agent  [UB +Data]
JD: Business-model analysis, portfolio strategy, build/buy/partner framing.
- Systems: the finance suite (unit economics) `[C]` · `knowledge_search` `[C]`.
- Technical: business-model analysis `[S]` · portfolio/BCG analysis `[S]` · build-buy-partner framing `[S]`.
- Domain: business-model patterns · portfolio theory `[K]`.

#### 1.4 Strategy-Ops / OKR Agent  [UB]
JD: Operationalize strategy — OKR cascade, strategic KPIs, alignment.
- Systems: `tools/{notion,jira,linear}` `[C]` · BI `[C]`.
- Technical: OKR cascade `[S]` · strategic-KPI design `[S]` · alignment mapping.
- Domain: OKR methodology (Doerr) · MBO `[K]`.

### Tower 2 — Corporate Development / M&A  *(sealed deal compartments)*

#### 2.1 Target-Sourcing & Screening Agent  [UB] {strong}
JD: Build the acquisition pipeline; screen targets against the thesis.
- Systems: `web_search` `[C]`, `tools/newsapi_tool` `[C]` · market data · **PitchBook/CapIQ** `[C]`.
- Technical: target screening `[S]` · pipeline building `[S]` · thesis-fit analysis `[S]`.
- Domain: M&A sourcing · the acquisition thesis `[K]`.
- Maverick: sealed; no approach/commitment.

#### 2.2 Due-Diligence Agent  [UB +Assess] {expert}
JD: Coordinate DD, analyze the data room, surface red flags.
- Systems: **virtual data rooms (Datasite, Intralinks)** `[C]` · finance + legal + GRC assessors `[C]` · `assessment.py` `[C]`.
- Technical: **data-room analysis** `[S]` · DD-coverage management `[S]` · red-flag detection `[S]` · `start/answer/finalize_assessment`.
- Domain: M&A diligence (financial/legal/tech/commercial) `[K]`.
- Verified: the eval/`assessment` harness (DD-coverage completeness).
- Judgment: deal-breaker vs price-adjuster; "unknown" over a confident guess.
- Maverick: **sealed deal compartment** (`allow_hosts=[]`); MNPI cannot cross.

#### 2.3 Valuation & Deal-Modeling Agent  [UB +Data] {expert}
JD: Valuation, deal models, synergy & accretion/dilution.
- Systems: the finance suite (valuation/forecasting) `[C]` · market data · Excel `[S]`.
- Technical: **DCF · comparable-companies · precedent transactions · LBO modeling** `[S]` · synergy & accretion/dilution `[S]`.
- Domain: valuation theory · deal structures `[K]`.
- Verified: model-integrity checks (balancing, no broken circularity) via the eval harness.
- Maverick: sealed; reuses finance models.

#### 2.4 Deal-Execution & Documentation Agent  [UB]
JD: Term sheets, deal-doc assembly/redline (with legal), process management.
- Systems: the legal domain (CLM) `[C]` · the deal compartment.
- Technical: term-sheet drafting `[S]` · deal-doc redline `[S]` · process management.
- Domain: deal-doc structure · closing mechanics `[K]`.
- Maverick: never signs/commits (human + legal).

#### 2.5 Post-Merger Integration (PMI) Agent  [UB]
JD: Integration planning, synergy tracking, Day-1/Day-100 plans.
- Systems: all suites (the integration workstreams) `[C]` · PM tools `[C]`.
- Technical: integration planning `[S]` · synergy tracking `[S]` · cross-functional coordination.
- Domain: post-merger integration · Day-1/Day-100 playbooks `[K]`.

### Tower 3 — Competitive & Market Intelligence

#### 3.1 Competitive-Intelligence Agent  [UB]
JD: Track competitor moves, strategy, positioning; strategic implications.
- Systems: `web_search` `[C]`, `tools/{newsapi_tool,reddit_tool}` `[C]` · GTM CI (8.3) · **Klue** `[C]`.
- Technical: competitor tracking `[S]` · CI-brief authoring `[S]`.
- Domain: competitive analysis `[K]`.

#### 3.2 Market-Research & Sizing Agent  [UB +Data]
JD: TAM/SAM/SOM, market trends, demand modeling.
- Systems: `/deep-research` `[C]` · `web_search` `[C]` · finance modeling · industry reports `[K]`.
- Technical: **TAM/SAM/SOM sizing** (top-down & bottom-up) `[S]` · trend analysis `[S]`.
- Domain: market-sizing methodology `[K]`.

#### 3.3 Industry & Trend-Monitoring Agent  [UB]
JD: Monitor industry/tech/regulatory disruption; early-warning signals.
- Systems: `tools/{newsapi_tool,arxiv,hackernews}` `[C]` · `CourtListener` (regulatory) `[C]`.
- Technical: signal monitoring `[S]` · trend-brief authoring `[S]`.

### Tower 4 — PMO & Strategic Execution

#### 4.1 Portfolio & Program-Management Agent  [UB]
JD: Strategic portfolio/program oversight, dependencies, RAID.
- Systems: `tools/{jira,linear,asana_tool,notion}` `[C]` · Smartsheet `[C]`.
- Technical: portfolio tracking `[S]` · dependency mapping `[S]` · **RAID** logs `[S]`.
- Domain: program/portfolio management (PMI/PMBOK basics) `[K]`.

#### 4.2 Strategic-Initiative-Tracking Agent  [UB]
JD: Track strategic initiatives, milestones, risks; status synthesis.
- Systems: PM tools `[C]` · BI `[C]`.
- Technical: initiative tracking `[S]` · milestone/risk synthesis `[S]` · status reporting `[S]`.

#### 4.3 Execution-Cadence & OKR Agent  [UB]
JD: Run the operating cadence (QBRs, business reviews), OKR tracking.
- Systems: PM tools `[C]` · `tools/calendar_tool` `[C]` · BI `[C]`.
- Technical: QBR prep `[S]` · OKR tracking `[S]` · cadence management.

### Tower 5 — Investor Relations & Capital Markets  *(Reg FD)*

#### 5.1 Investor-Relations Agent  [UB] {strong}
JD: Investor comms, shareholder analysis, Q&A prep, perception tracking.
- Systems: the finance IR/reporting towers `[C]` · **IR CRM (Q4, Irwin)** `[C]` · `tools/salesforce_tool` `[C]`.
- Technical: investor-material drafting `[S]` · shareholder/ownership analysis `[S]` · Q&A prep `[S]`.
- Domain: IR · **Reg FD** · the equity story `[K]`.
- Maverick: external release gated; no selective disclosure.

#### 5.2 Earnings & Disclosure Agent  [UB] {strong}
JD: Earnings materials, scripts, consistency with the filing; disclosure-control checklist.
- Systems: the finance SEC-reporting tower `[C]`.
- Technical: earnings-material drafting `[S]` · consistency checking `[S]` · **non-GAAP (Reg G)** reconciliation `[S]`.
- Domain: earnings process · Reg FD/Reg G `[K]`.
- Maverick: release human (Reg FD).

#### 5.3 Capital-Strategy & Markets Agent  [UB +Data]
JD: Capital structure, financing options, analyst/coverage tracking.
- Systems: the finance treasury/capital-markets tower `[C]` · market data (**Bloomberg**) `[C]`.
- Technical: capital-structure modeling `[S]` · financing-option analysis `[S]` · analyst tracking.
- Domain: capital markets · cost of capital `[K]`.

### Tower 6 — Executive Office & Chief of Staff

#### 6.1 Board & Governance-Support Agent  [UB] {strong}  *(sealed board compartment)*
JD: Board materials, pre-reads, minutes, governance/calendar, action tracking.
- Systems: **board portal (Diligent, Boardvantage)** `[C]` · `gdrive_tool` `[C]` · `tools/calendar_tool` `[C]`.
- Technical: board-deck/pre-read drafting `[S]` · minutes `[S]` · governance-action tracking.
- Domain: corporate governance · board process `[K]`.
- Maverick: **sealed board compartment**; confidentiality/privilege; no board decisions.

#### 6.2 Decision-Brief & Memo Agent  [UB]
JD: Executive decision memos, pre-reads, options/recommendations, synthesis.
- Systems: all suites (inputs) `[C]` · `knowledge_search` `[C]` · `pandoc_tool` `[C]`.
- Technical: **decision-memo authoring** (e.g., Amazon 6-pager) `[S]` · options analysis `[S]` · synthesis.
- Judgment: surfacing the real tradeoff and a recommendation, not just options.

#### 6.3 Executive-Assistant / Scheduling Agent  [UB +Reach]
JD: Scheduling, inbox triage, travel, meeting prep — exec operational support.
- Systems: `tools/{calendar_tool,calendly_tool,gmail_tool,msgraph_tool,teams_tool}` `[C]` · channels `[C]`.
- Technical: scheduling/coordination `[S]` · inbox triage/prioritization `[S]` · travel · meeting prep.
- Maverick: external sends gated.

#### 6.4 Executive-Communications Agent  [UB +Reach]
JD: Exec/leadership comms — all-hands, leadership messages, internal narrative.
- Systems: the channels layer `[C]` · `knowledge_search` `[C]`.
- Technical: exec-comms drafting `[S]` · narrative crafting `[S]`.
- Maverick: sensitive/external comms human-approved.

### Tower 7 — Corporate Affairs & ESG

#### 7.1 Corporate-Communications & PR Agent  [UB +Reach]
JD: External narrative, press, crisis comms, message consistency *(cross-ref GTM PR)*.
- Systems: the GTM PR agent · media DBs (Cision) `[C]` · channels `[C]`.
- Technical: corp-comms drafting `[S]` · crisis-comms playbooks `[S]`.
- Maverick: external release gated.

#### 7.2 Government-Relations & Public-Affairs Agent  [UB]
JD: Policy/regulatory monitoring, public-affairs positions, engagement prep.
- Systems: `CourtListener` `[C]`, `web_search` `[C]`, `tools/newsapi_tool` `[C]` · the GRC reg-change agent.
- Technical: policy monitoring `[S]` · position-paper drafting `[S]`.
- Domain: public policy · **lobbying-disclosure** awareness `[K]`.
- Maverick: engagement gated.

#### 7.3 ESG & Sustainability Agent  [UB +Data] {strong}
JD: ESG strategy + reporting (CSRD/ESRS, ISSB), carbon/impact tracking *(cross-ref finance ESG)*.
- Systems: the finance ESG vertical `[C]` · ESG-data platforms (Persefoni, Workiva ESG) `[C]`.
- Technical: **ESG reporting** `[S]` · carbon accounting (Scope 1/2/3) `[S]` · materiality assessment `[S]`.
- Domain: **CSRD/ESRS, ISSB (IFRS S1/S2), GRI, TCFD, EU Taxonomy** `[K]`.
- Maverick: disclosure gated.

#### 7.4 Corporate Social Responsibility Agent  [UB]
JD: CSR programs, philanthropy, community impact, volunteering.
- Systems: `knowledge_search` `[C]` · channels `[C]` · grants/giving platforms `[C]`.
- Technical: CSR-program drafting `[S]` · impact tracking `[S]`.

### Council-added agents
*(the deal-defining seats that fell between suites; full profiles below.)*

#### C1 M&A Financial-Modeling Agent  [UB +Data] {expert}
JD: Builds the deal models — closes the Strategy↔Finance modeling gap inside the sealed deal compartment.
- Systems: the model workbook · the finance valuation/forecasting seats · market data (inside the wall).
- Technical: **three-statement model · LBO mechanics (debt schedule / cash sweep / circularity) · DCF / WACC build-up · PPA / opening balance sheet · accretion-dilution · returns (IRR/MOIC) bridges · structuring (cash/stock/earnout/NWC peg)**.
- Domain: deal modeling · synergy quantification · capital structure.
- Regulatory: purchase accounting (**ASC 805**) interplay · MNPI handling.
- Maverick: **sealed deal compartment** — MNPI cannot cross the wall; models for the deal team to decide; never commits, prices, or signs.

#### C2 Antitrust / Merger-Clearance Agent  [UB]
JD: Flags merger-control and foreign-investment risk for counsel (was a "flag for counsel" gap with no skill).
- Systems: `web_search` · `CourtListener` · the deal compartment · outside antitrust counsel.
- Technical: HSR-threshold screening · overlap/concentration analysis · filing-timeline mapping · second-request readiness assessment.
- Domain: **HSR thresholds + the 2024 HSR rule · 2023 Merger Guidelines · second requests · EU/UK & global merger control · CFIUS · gun-jumping**.
- Regulatory: **HSR/Clayton Act, EU/UK merger control, CFIUS (FIRRMA)**.
- Maverick: awareness/flagging only — **the legal determination is qualified counsel's**; gun-jumping discipline enforced inside the wall.

#### C3 Activist-Defense / Shareholder-Engagement Agent  [UB]
JD: Monitors the shareholder base and prepares engagement and defense readiness.
- Systems: ownership/13F data · proxy-advisor feeds · the IR seats · transfer-agent data.
- Technical: **13D/G monitoring (2024 deadlines) · proxy season / ISS-Glass Lewis analysis · say-on-pay modeling · Rule 10b5-1 plan tracking** · vulnerability/perception assessment.
- Domain: activism defense · proxy mechanics · shareholder engagement.
- Regulatory: **§13(d)/(g), Reg 14A proxy rules, say-on-pay, Rule 10b5-1**.
- Maverick: research + brief; **external engagement/disclosure is gated under Reg FD**; MNPI walled.

#### C4 JV / Alliance / BD Agent  [UB]
JD: Supports non-M&A inorganic growth — JVs, alliances, and licensing.
- Systems: `knowledge_search` · the legal CLM (for terms) · finance (for economics).
- Technical: JV structuring · alliance/partnership design · **licensing/partnership economics** modeling · governance-structure options.
- Domain: joint-venture structures · strategic alliances · BD deal shapes.
- Regulatory: antitrust-in-JVs awareness (cross-ref C2) · IP/licensing terms (cross-ref legal).
- Maverick: structures and models for executive decision; **never signs or commits**; antitrust/IP routed to counsel.

#### C5 Transaction-Tax / Structuring Agent  [UB]
JD: Analyzes deal tax structuring with finance tax (sealed).
- Systems: the deal compartment · the finance tax seats · tax research.
- Technical: structuring analysis — **338(h)(10)/336(e) · NOLs & §382 limitation · step-up · tax-free reorg (§368)** · entity/jurisdiction structuring.
- Domain: transaction tax · M&A tax structuring · attribute preservation.
- Regulatory: **IRC §§338/336/368/382**, cross-ref finance tax.
- Maverick: **sealed** deal compartment; models for counsel/tax sign-off; never commits a position; MNPI walled.

---

## Legal suite

31 agents ([legal-agent-suite.md](legal-agent-suite.md)). Cross-cutting baseline (the
`legal.toml` spine): **research & analysis, not legal advice** (an attorney owns every
position); **citation integrity** (every authority verified against CourtListener/Westlaw or
marked unverified — never fabricated); **privilege & conflicts** via sealed `quarantine`
compartments; **never file/serve/sign/send** without an attorney; jurisdiction-scoped.

### Tower 1 — Legal Research & Knowledge

#### 1.1 Legal Research Agent  [UB]
JD: Research case law/statutes/regulations; write memos with precise, quoted authority.
- Systems: **CourtListener** (live) · **Westlaw, LexisNexis** · `web_search` · `knowledge_search`.
- Technical: case-law/statute research · **Bluebook citation** · memo drafting (IRAC/CRAC).
- Domain: legal research method · primary vs secondary authority.
- Maverick: **verify every citation**; jurisdiction-scoped; not legal advice.

#### 1.2 Citation-Verification Agent  [UB]
JD: Verify every citation against a real source; flag/strip unverifiable authority.
- Systems: **CourtListener** (live) · Westlaw/Lexis · Shepard's/KeyCite.
- Technical: **citation verification** · quote/pin-cite checking · **Shepardizing** (good law check).
- Domain: citation accuracy · the fabricated-citation failure mode.
- Maverick: **the citation-integrity enforcement point** — unverifiable → `[UNVERIFIED]`, excluded.

#### 1.3 Legal Knowledge-Management Agent  [UB]
JD: Internal precedent/clause/memo library; surface prior work.
- Systems: `knowledge_search` · `tools/{confluence_tool,notion}` · the matter system.
- Technical: precedent indexing/retrieval · clause libraries.

### Tower 2 — Commercial Contracts (CLM)

#### 2.1 Contract-Drafting Agent  [UB]
JD: Draft contracts from approved templates + the playbook (NDAs, MSAs, SOWs, DPAs).
- Systems: **CLM (Ironclad, Icertis, DocuSign CLM)** · template library.
- Technical: **contract drafting** from templates/playbook · clause assembly.
- Domain: commercial contract law · the contract playbook.
- Maverick: never executes/signs.

#### 2.2 Contract-Review & Redline Agent  [UB]
JD: Review third-party paper against the playbook, redline, flag risk.
- Systems: CLM · the playbook · privacy suite (DPA terms) · **contract-AI (Spellbook, LegalOn)**.
- Technical: **contract review & redlining** (liability, indemnity, IP, data, termination) · playbook-deviation flagging.
- Domain: commercial terms · risk allocation.
- Maverick: cite the playbook; attorney owns non-standard; never signs.

#### 2.3 Contract-Negotiation-Support Agent  [UB]
JD: Fallback positions, negotiation tracking, counterparty-position analysis.
- Systems: CLM · the playbook.
- Technical: fallback-position proposal · negotiation tracking.

#### 2.4 Obligations & Renewals Agent  [UB +Data]
JD: Extract obligations/key terms, track renewals/milestones/auto-renews.
- Systems: CLM · finance (revenue/spend impact).
- Technical: **obligation extraction** · renewal/milestone tracking.

#### 2.5 Contract Repository & Intake Agent  [UB]
JD: Repository, intake/triage, metadata/tagging, search.
- Systems: CLM · `intake.py` · channels.
- Technical: contract intake/triage · metadata tagging · repository search.

### Tower 3 — Corporate, Governance & Securities

#### 3.1 Entity-Management Agent  [UB]
JD: Entity formation/maintenance, subsidiary management, registered agents, annual filings.
- Systems: **entity mgmt (Diligent Entities)** · state SOS portals.
- Technical: entity tracking · corporate-filing drafting.
- Domain: corporate law · entity structures.
- Maverick: filing gated.

#### 3.2 Board & Governance Agent  [UB]  *(cross-ref Strategy 6.1 — sealed)*
JD: Board materials, minutes, resolutions, governance.
- Systems: the Strategy board agent · `gdrive_tool`.
- Technical: resolution/minutes drafting · governance support.
- Maverick: sealed board compartment; privilege; no board decisions.

#### 3.3 Securities & SEC Agent  [UB]  *(cross-ref finance SEC tower)*
JD: Securities-law compliance, disclosure review, filing legal review.
- Systems: the finance SEC tower · CourtListener (rules) · EDGAR.
- Technical: disclosure review · securities-risk flagging.
- Domain: **'33/'34 Acts, Reg S-K/S-X, Section 16, 10b-5**.
- Maverick: filing gated.

#### 3.4 Equity & Cap-Table Legal Agent  [UB]
JD: Equity-issuance legal, option grants, 409A legal, securities exemptions.
- Systems: cap-table (Carta) · the finance equity agent.
- Technical: equity-doc review · exemption analysis.
- Domain: **Reg D/S, Rule 701, 409A, ISO/NSO** law.
- Maverick: no issuance.

### Tower 4 — Litigation, Disputes & E-Discovery  *(sealed matter compartments)*

#### 4.1 Litigation-Management Agent  [UB]
JD: Case management, docketing/deadlines, strategy support, outside-counsel coordination.
- Systems: matter system · `tools/calendar_tool` · CourtListener · **PACER**.
- Technical: **docketing & deadline calculation** (FRCP/local rules) · case-status synthesis.
- Domain: **the finer points of litigation procedure — FRCP, jurisdiction/venue, pleadings, motion practice, discovery sequencing, appeals**.
- Maverick: **deadline integrity** (missed deadline = malpractice); sealed; no filings.

#### 4.2 E-Discovery Agent  [UB]
JD: Document review, responsiveness/relevance coding, privilege review/logging, production prep.
- Systems: **Relativity, Everlaw, Disco** · `tools/{pdf_reader,ocr}`.
- Technical: **TAR/predictive coding** · responsiveness/relevance review · **privilege review & logging** · production prep.
- Domain: **EDRM / FRCP Rule 26-34** · privilege types · proportionality.
- Maverick: **privilege protection** (mis-coding waives privilege); sealed; production human.

#### 4.3 Legal-Hold Agent  [UB]
JD: Issue/track legal holds, custodian management, spoliation prevention.
- Systems: the data stores · `audit/` (hold flags) · HRIS (custodians) · legal-hold tools.
- Technical: hold issuance/tracking · custodian management · hold-reminder workflow.
- Domain: **preservation duty / spoliation (FRCP Rule 37(e))**.
- Maverick: **deletion of held data refused** (hold overrides retention/erasure — hard floor).

#### 4.4 Brief & Motion-Drafting Agent  [UB]
JD: Draft briefs, motions, pleadings; build the table of authorities.
- Systems: CourtListener (live) · Westlaw/Lexis · the matter (sealed).
- Technical: **brief/motion/pleading drafting** · legal argument (IRAC) · table-of-authorities assembly · **Bluebook**.
- Domain: motion practice · standards of review · persuasive writing.
- Maverick: **citation integrity** (the courtroom is where fabricated cites get sanctioned); filing is the attorney's.

#### 4.5 Settlement & Dispute Agent  [UB]
JD: Settlement analysis, demand/response letters, ADR support, exposure modeling.
- Systems: the matter (sealed) · finance (exposure).
- Technical: settlement analysis · demand/response drafting · exposure modeling.
- Domain: ADR (mediation/arbitration) · settlement strategy.
- Maverick: never sends/commits.

### Tower 5 — Intellectual Property

#### 5.1 Patent Agent  [UB]
JD: Patent/prior-art search, application support, portfolio management.
- Systems: **USPTO Patent Center** (filing) + **Patent Public Search** (PatFT/AppFT retired), **PEDS, Global Dossier, Google Patents, Espacenet**.
- Technical: prior-art search · claim analysis · application-support drafting.
- Domain: patent law (35 USC) · patentability · the PCT.
- Maverick: filing gated.

#### 5.2 Trademark Agent  [UB]
JD: Trademark clearance/search, filing prep, watch/monitoring, oppositions.
- Systems: **USPTO Trademark Search** (TESS retired) + **TSDR**, **ID Manual, Madrid/WIPO Global Brand DB, TTABVUE** · trademark watch services.
- Technical: clearance/knockout search · filing prep · likelihood-of-confusion analysis.
- Domain: trademark law (Lanham Act) · classes (Nice).
- Maverick: filing gated.

#### 5.3 Copyright & Trade-Secret Agent  [UB]
JD: Copyright registration, trade-secret programs, DMCA, NDAs.
- Systems: U.S. Copyright Office · the contracts tower (NDAs).
- Technical: copyright registration support · trade-secret-program design · DMCA notices.
- Domain: copyright law · **DTSA/UTSA** trade-secret law.

#### 5.4 IP Licensing & Infringement Agent  [UB]
JD: Licensing-deal support, infringement analysis, enforcement/C&D.
- Systems: the contracts tower · CourtListener.
- Technical: license-agreement drafting · **infringement analysis** · cease-and-desist drafting.
- Maverick: enforcement sends gated.

### Tower 6 — Regulatory, Antitrust & Trade

#### 6.1 Regulatory-Counsel Agent  [UB]  *(cross-ref GRC)*
JD: Regulatory advice, applicability analysis, regulatory-change legal impact.
- Systems: CourtListener · `web_search` · the GRC suite · the **CFR/Federal Register**.
- Technical: applicability analysis · regulatory-memo drafting.
- Domain: administrative law · the relevant sector regulators.

#### 6.2 Antitrust & Competition Agent  [UB]  *(cross-ref Strategy M&A)*
JD: Antitrust analysis, HSR/merger review, competition compliance.
- Systems: the Strategy M&A tower · CourtListener.
- Technical: antitrust analysis · **HSR filing support** · competition-risk assessment.
- Domain: **Sherman/Clayton/HSR Acts** · merger guidelines · EU competition law.
- Maverick: no filings.

#### 6.3 Trade & Sanctions Agent  [UB]  *(cross-ref finance AML + GTM screening)*
JD: Export controls, sanctions/OFAC, trade compliance.
- Systems: sanctions screening · the GRC/finance suites.
- Technical: **export-control classification (ECCN)** · sanctions screening · trade-compliance review.
- Domain: **EAR/ITAR, OFAC, customs**.
- Maverick: decisions gated.

### Tower 7 — Employment & Privacy Law

#### 7.1 Employment-Law Agent  [UB]  *(cross-ref HR T7)*
JD: Employment-law advice, policy legal review, dispute/claim analysis.
- Systems: the HR employment-law agent · CourtListener.
- Technical: employment-policy legal review · claim analysis.
- Domain: **Title VII, ADA, ADEA, FLSA, FMLA, NLRA, WARN** + state.
- Maverick: attorney-owned; not legal advice.

#### 7.2 Privacy & Data-Protection-Law Agent  [UB]  *(cross-ref privacy suite)*
JD: Privacy counsel, DPAs, breach legal analysis, GDPR/CCPA positions.
- Systems: the privacy suite · CourtListener.
- Technical: **DPA review** · breach legal analysis · privacy-position drafting.
- Domain: **GDPR, CCPA/CPRA, sectoral (HIPAA/GLBA/FERPA)** · cross-border.
- Maverick: notification decisions human/attorney.

### Tower 8 — Legal Operations

#### 8.1 Matter-Management Agent  [UB]
JD: Matter intake/triage, lifecycle, status reporting, prioritization.
- Systems: matter system (**Litera, Clio**) · `intake.py`.
- Technical: matter intake/triage · lifecycle/status management.

#### 8.2 Outside-Counsel & Spend Agent  [UB +Data]
JD: Outside-counsel guidelines, e-billing review, spend analytics, panel management.
- Systems: **e-billing (Legal Tracker, Brightflag)** · finance (spend).
- Technical: **e-billing/invoice review** (OCG compliance, LEDES) · legal-spend analytics.
- Maverick: approvals gated; SoD vs finance AP.

#### 8.3 Legal-Intake & Triage Agent  [UB +Reach]
JD: Legal-request intake, routing, self-service answers, SLA tracking.
- Systems: `intake.py` · the channels layer · `knowledge_search`.
- Technical: request intake · routing · self-service answering.
- Maverick: AI disclosure; **escalate substantive questions** (not legal advice).

#### 8.4 Legal-Tech & KM-Ops Agent  [UB +Build]
JD: Legal tech stack, workflow automation, legal metrics/reporting.
- Systems: legal-ops tools · BI.
- Technical: workflow automation · legal-metrics reporting.

#### 8.5 Conflicts-Check Agent  [UB]
JD: Run conflicts checks before matter intake; set up ethical walls.
- Systems: the matter/entity system · `quarantine.py`/`capability.py`.
- Technical: **conflicts checking** · ethical-wall setup.
- Domain: conflicts of interest · ethical-wall practice.
- Maverick: clearing a conflict is human; the ethical-wall setup point.

### Council-added agents
*(seats the council flagged as missing; full profiles below.)*

#### C1 AI & Emerging-Tech Counsel Agent  [UB]
JD: The legal owner of AI/emerging-tech matters, complementing the GRC AI-governance seats.
- Systems: `knowledge_search` (the AI-law library) · `CourtListener` · the CLM · the GRC AI-gov seats.
- Technical: AI-contract drafting/review · training-data & IP risk analysis · model-terms review · regulatory-mapping for AI features.
- Domain: **EU AI Act · Colorado AI Act (SB 24-205) · the US state-privacy wave · AI/IP & training-data law · AI contracting**.
- Regulatory: **EU AI Act, US state AI/privacy laws, copyright/IP**.
- Maverick: drafts and analyzes — **not legal advice**; a licensed attorney reviews; every authority is citation-verified (no fabricated cases).

#### C2 Litigation Discovery-Response / Subpoena Agent  [UB]
JD: Runs the inbound-demand workflow — responding to subpoenas, CIDs, and investigations (distinct from e-discovery review).
- Systems: the matter system · the litigation-hold seat (4.3) · the e-discovery platform · `knowledge_search`.
- Technical: subpoena/CID response drafting · scope/objection analysis · litigation-hold coordination · **30(b)(6)** witness-prep support · production-tracking.
- Domain: responding to **subpoenas / CIDs / government investigations** · meet-and-confer · privilege-log basics.
- Regulatory: **FRCP (26/30/34/45), state discovery rules**.
- Maverick: drafts responses for attorney sign-off; **not legal advice**; preserves privilege; citations verified.

#### C3 Internal-Investigations (GC-led) Agent  [UB]
JD: Supports privileged, counsel-led investigations (distinct from HR's workplace investigations; sealed, privileged).
- Systems: a sealed/privileged compartment (`quarantine.py`/`capability.py`) · the document set · interview materials.
- Technical: investigation-plan drafting · evidence organization · neutral timeline construction · **Upjohn-warning** scripting · board/audit-committee report drafting.
- Domain: **privileged, counsel-led** investigations (**FCPA, fraud, whistleblower-legal**) · privilege preservation.
- Regulatory: **FCPA, attorney-client privilege / work-product, whistleblower law**.
- Maverick: **sealed, privileged** compartment — findings stay inside the wall; reaches no legal conclusion; the attorney/board decides; not legal advice.

#### C4 Insurance-Coverage Agent  [UB]
JD: Analyzes coverage and manages claim tender across the insurance program.
- Systems: the policy library · `knowledge_search` · broker/carrier correspondence · the matter system.
- Technical: **D&O / cyber / E&O coverage analysis** · claim-tender drafting · **reservation-of-rights** review · exclusion/retention analysis.
- Domain: insurance coverage · claims handling · tower/limits structure.
- Regulatory: insurance-law basics · notice-and-tender timing.
- Maverick: analyzes and drafts tenders for attorney/risk sign-off; **a coverage position is human**; not legal advice; citations verified.

#### C5 Bankruptcy / Restructuring & Creditors'-Rights Agent  [UB]
JD: Owns the finance/AR credit seam — secured transactions, claims, and avoidance-risk awareness.
- Systems: the contract/CLM · the finance AR/credit seats · `knowledge_search`.
- Technical: **UCC Article 9** security-interest analysis · **proof-of-claim** drafting · **preference / fraudulent-transfer** awareness · lien/perfection checks.
- Domain: bankruptcy & restructuring · creditors' rights · workout structures.
- Regulatory: **Bankruptcy Code (§§547/548/362), UCC Article 9**.
- Maverick: drafts and flags for counsel; **not legal advice**; a filing/position is attorney-owned; citations verified.

---

## Operations / Supply Chain suite

33 agents ([operations-supply-chain-agent-suite.md](operations-supply-chain-agent-suite.md)).
Cross-cutting baseline: the **physical-action gate** ("never move atoms" — POs/production/
dispatch/actuation are human-authorized), **safety is a refusal, not a gate** (never control
safety-critical equipment or override an interlock; worker safety overrides efficiency), and
**lean / Six-Sigma** problem-solving.

### Tower 1 — Supply Chain Planning (S&OP)

#### 1.1 Demand-Planning Agent  [UB +Data]
JD: Demand forecasting, consensus demand, seasonality/promo effects.
- Systems: **Kinaxis, o9, Blue Yonder** (planning) · ERP · GTM/finance forecast.
- Technical: **statistical demand forecasting** · consensus planning · forecast-error (MAPE/bias) analysis.
- Domain: demand planning · seasonality · promo lift.

#### 1.2 Supply-Planning & MRP Agent  [UB +Data]
JD: Supply/materials planning, MRP runs, capacity-feasible plans.
- Systems: **SAP, Oracle, Kinaxis** (MRP).
- Technical: **MRP/MPS** · materials planning · capacity-feasibility checks.
- Domain: supply planning · lead-time/lot-sizing.

#### 1.3 S&OP / IBP Agent  [UB +Data]
JD: Sales & operations planning, IBP, scenario balancing.
- Systems: planning · finance (reconciliation) · GTM (demand).
- Technical: S&OP scenario balancing · consensus-plan synthesis.
- Domain: S&OP/IBP process.

#### 1.4 Inventory-Optimization Agent  [UB +Data]
JD: Safety stock, reorder points, ABC/XYZ, multi-echelon optimization.
- Systems: ERP/WMS · `pandas_query`.
- Technical: **safety-stock / reorder-point math** · ABC/XYZ · multi-echelon optimization.
- Maverick: reorder execution tiered.

#### 1.5 Network & Capacity-Planning Agent  [UB +Data]
JD: Network design, capacity planning, footprint/sourcing strategy.
- Systems: planning · finance (cost) · Strategy (footprint).
- Technical: network modeling · capacity analysis.

### Tower 2 — Procurement & Sourcing  *(money side → finance)*

#### 2.1 Strategic-Sourcing Agent  [UB]
JD: Sourcing strategy, RFx, bid analysis, supplier selection.
- Systems: **SAP Ariba, Coupa** (sourcing) · finance.
- Technical: RFx management · bid/should-cost analysis · supplier selection.
- Maverick: award gated.

#### 2.2 Purchasing / PO Agent  [UB]
JD: Create POs, run the 3-way match, manage confirmations.
- Systems: ERP · finance AP (1.2) · `governance` (risk-floor gate today; **DoA/amount-aware policy to build**).
- Technical: PO creation · **3-way match** · variance flagging.
- Maverick: **PO commit beyond the DoA tier denied**; never releases payment; bank-detail-change → human.

#### 2.3 Supplier-Management & Performance Agent  [UB +Data]
JD: Supplier scorecards, performance/SLA tracking, relationship management.
- Systems: **SRM** · ERP.
- Technical: scorecard analysis · SLA tracking.

#### 2.4 Supplier-Risk & Resilience Agent  [UB +Assess]
JD: Supplier risk, single-source/concentration, forced-labor/conflict-minerals, disruption.
- Systems: the GRC vendor-risk tower + `_VENDOR_RISK` · risk feeds (Resilinc/Everstream).
- Technical: supplier-risk assessment · concentration analysis · disruption monitoring.
- Domain: supply-chain resilience · **forced-labor (UFLPA) / conflict-minerals** due diligence.

### Tower 3 — Manufacturing & Production  *(safety-critical actuation refused)*

#### 3.1 Production-Planning & Scheduling Agent  [UB +Data]
JD: Production schedules, sequencing, line balancing, capacity feasibility.
- Systems: **MES / ERP (SAP PP)** · the planning tower.
- Technical: **finite scheduling** · sequencing · line balancing.
- Maverick: releasing to the floor is human/tier.

#### 3.2 Shop-Floor / MES Agent  [UB +Data]
JD: Work-order management, shop-floor status, OEE analysis (read; actuation refused).
- Systems: **MES** · industrial IoT (read-only telemetry).
- Technical: work-order management · **OEE analysis** · throughput/bottleneck analysis.
- Domain: lean manufacturing · TPS.
- Maverick: **refuses equipment actuation / safety control** (§ safety refusal); escalate unsafe conditions.

#### 3.3 BOM & Routing Agent  [UB]  *(cross-ref P&E for design)*
JD: BOM management, routings, engineering-change orders.
- Systems: ERP/**PLM (Teamcenter, Windchill)** · the P&E suite.
- Technical: BOM management · routing definition · **ECO** processing.
- Maverick: changes gated.

#### 3.4 Production-Quality & Yield Agent  [UB +Data]
JD: Yield, scrap, statistical process control, first-pass yield.
- Systems: MES · `pandas_query`.
- Technical: **SPC (control charts, Cpk)** · yield/scrap analysis.
- Domain: Six-Sigma · process capability.

### Tower 4 — Quality Management

#### 4.1 Quality-Control & Inspection Agent  [UB +Data]
JD: Inspection plans, sampling, test-result capture/analysis.
- Systems: **QMS (MasterControl, ETQ)** · MES.
- Technical: inspection planning · **AQL sampling** · test-result analysis.
- Maverick: quality-hold decisions gated.

#### 4.2 Nonconformance & CAPA Agent  [UB]
JD: NCR management, root-cause, CAPA tracking to closure.
- Systems: QMS.
- Technical: NCR management · **root-cause (5-why, fishbone, 8D)** · CAPA tracking.
- Maverick: closure gated.

#### 4.3 Supplier-Quality Agent  [UB]  *(cross-ref Procurement)*
JD: Incoming quality, supplier audits, SCARs.
- Systems: QMS + SRM.
- Technical: incoming-quality assessment · **supplier audits (PPAP, APQP)** · SCAR management.

#### 4.4 Compliance & Recall Agent  [UB]
JD: ISO 9001 / regulatory quality compliance, lot/serial traceability, recall scope.
- Systems: QMS/ERP · legal (regulatory) · the audit chain.
- Technical: **lot/serial traceability** · recall-scope assembly.
- Domain: **ISO 9001** · industry quality (FDA QSR/21 CFR 820, IATF 16949).
- Maverick: **recall execution is human-led** (safety/regulatory).

### Tower 5 — Logistics, Warehousing & Distribution

#### 5.1 Transportation / TMS Agent  [UB +Data]
JD: Carrier selection, route/load optimization, freight audit, tracking.
- Systems: **TMS (project44, FourKites, MercuryGate)**.
- Technical: **route/load optimization** · carrier selection · freight audit · ETA tracking.
- Maverick: **dispatch gated**; routing optimization is L3-eligible.

#### 5.2 Warehouse / WMS Agent  [UB +Data]
JD: Warehouse ops — pick/pack waves, slotting, labor/dock planning.
- Systems: **WMS (Manhattan, Körber, Blue Yonder)**.
- Technical: wave planning · **slotting optimization** · labor/dock planning.
- Maverick: physical task release gated.

#### 5.3 Inventory-Control Agent  [UB +Data]  *(cross-ref finance 1.9)*
JD: Inventory accuracy, cycle counts, adjustments.
- Systems: WMS/ERP · finance.
- Technical: cycle-count planning · variance analysis · accuracy (IRA) tracking.
- Maverick: **adjustments gated**.

#### 5.4 Fulfillment & Order-Ops Agent  [UB +Reach]
JD: Order fulfillment, allocation, OTC operations, exceptions.
- Systems: **Shopify** (shipped) · ERP/OMS.
- Technical: fulfillment management · allocation · exception resolution.
- Maverick: customer comms gated.

#### 5.5 Customs, Trade & Returns Agent  [UB]  *(cross-ref legal trade 6.3)*
JD: Customs/import-export docs, HS classification, duties; reverse logistics.
- Systems: customs/trade (Descartes) · the legal suite.
- Technical: **HS classification** · customs-doc drafting · duty calculation · returns management.
- Domain: customs · Incoterms · trade compliance.
- Maverick: filings gated.

### Tower 6 — Asset & Maintenance Management

#### 6.1 Asset-Management Agent  [UB +Data]  *(physical assets; IT assets → IT-GRC)*
JD: Physical-asset registry, lifecycle, utilization.
- Systems: **EAM/CMMS (Maximo, Fiix, UpKeep)** · finance FA.
- Technical: asset registry · lifecycle/utilization analysis.

#### 6.2 Preventive/Predictive-Maintenance Agent  [UB +Data]
JD: PM schedules, condition monitoring, predictive maintenance.
- Systems: **CMMS** · industrial IoT (read telemetry).
- Technical: PM scheduling · **condition monitoring / predictive maintenance** (vibration, thermal).
- Maverick: **equipment actuation refused**; work-order execution gated.

#### 6.3 Reliability & Downtime Agent  [UB +Data]
JD: Reliability engineering, downtime/RCA, spare-parts optimization.
- Systems: CMMS · `pandas_query`.
- Technical: **reliability analysis (MTBF/MTTR, Weibull)** · downtime RCA · spare-parts optimization.
- Domain: RCM · TPM.

### Tower 7 — Facilities & Real Estate

#### 7.1 Facilities-Management Agent  [UB +Reach]
JD: Facilities ops, maintenance work orders, service-vendor coordination.
- Systems: **CMMS/IWMS** · the channels layer.
- Technical: facility-WO management · vendor coordination.
- Maverick: vendor spend gated.

#### 7.2 Real-Estate & Lease Agent  [UB]  *(cross-ref finance Lease 1.10 + legal)*
JD: Real-estate portfolio, lease administration, site-selection support.
- Systems: **lease/IWMS** · finance + legal.
- Technical: lease administration · portfolio analysis · site-selection support.
- Maverick: commitments gated.

#### 7.3 Workplace & Space Agent  [UB]
JD: Space planning, workplace services, moves/adds/changes, occupancy.
- Systems: **IWMS** · `tools/calendar_tool`.
- Technical: space planning · move management · occupancy analytics.

#### 7.4 Energy & Utilities Agent  [UB +Data]  *(cross-ref ESG)*
JD: Utilities/energy management, consumption analytics, efficiency.
- Systems: **BMS / energy-management** · finance ESG.
- Technical: energy-consumption analytics · efficiency recommendations.
- Maverick: **building-control actuation refused/gated**.

### Tower 8 — EHS & Sustainability Operations  *(safety paramount)*

#### 8.1 Workplace-Safety (OSHA) Agent  [UB +Reach]
JD: Safety programs, hazard/JSA management, incident/injury tracking, OSHA recordkeeping.
- Systems: **EHS (Cority, Intelex, VelocityEHS)** · the channels layer.
- Technical: hazard/JSA management · incident tracking · **OSHA 300/301/300A recordkeeping**.
- Domain: **OSHA standards (29 CFR 1910/1926)** · safety management (ISO 45001).
- Maverick: **safety paramount**; incidents escalate; never recommends an unsafe shortcut.

#### 8.2 Environmental-Compliance Agent  [UB]  *(cross-ref GRC/legal)*
JD: Environmental permits, emissions/waste/water tracking, EPA reporting.
- Systems: EHS · GRC + legal.
- Technical: permit tracking · emissions/waste reporting · exceedance flagging.
- Domain: **EPA (Clean Air/Water Acts, RCRA), hazmat (DOT/IATA)**.
- Maverick: **permit-limit exceedance is a hard floor**; filing gated.

#### 8.3 Incident & Emergency-Management Agent  [UB +Reach]  *(cross-ref IT-GRC IR/DR)*
JD: Operational incident management, emergency response, physical BCP.
- Systems: EHS · the IT-GRC incident agents · channels.
- Technical: incident management · emergency-response coordination · BCP drafting.
- Domain: emergency management · ISO 22301.
- Maverick: actions gated.

#### 8.4 Sustainability-Operations Agent  [UB +Data]  *(cross-ref finance ESG)*
JD: Operational sustainability — carbon (Scope 1&2), waste/circularity, efficiency.
- Systems: ESG platforms · the finance ESG vertical.
- Technical: **carbon accounting (Scope 1/2/3)** · waste/circularity tracking · efficiency analysis.
- Domain: sustainability · GHG Protocol.

---

### Council-added agents
*(seats the council flagged as missing; full profiles below.)*

#### C1 OT / ICS-Security Agent  [UB +Build]
JD: Owns security over the SCADA/historian/DCS the rest of the suite only reads — the IT-OT seam.
- Systems: historian/SCADA/DCS (**OSIsoft PI/AVEVA, Rockwell, Siemens, Honeywell, Emerson**) `[C]` · OT-IDS (Claroty/Nozomi/Dragos) · the IT secops seats.
- Technical: OT asset inventory · IT-OT segmentation review · OT-protocol monitoring · OT vulnerability triage · safe patch-window planning.
- Domain: **IEC 62443 · the Purdue model / IT-OT segmentation · NIST 800-82** · OT incident response.
- Regulatory: **IEC 62443, NIST 800-82**, sector OT mandates (e.g. TSA pipeline, NERC CIP where applicable).
- Maverick: read + recommend; **never writes to a control system or changes a setpoint** (refuses safety-critical actuation); remediation is human-gated.

#### C2 Continuous-Improvement / OpEx (Lean) Agent  [UB +Data]
JD: Owns the lean operating system the suite treated as cross-cutting but no one held.
- Systems: the MES/ERP (for process data) · BI · the quality/planning seats.
- Technical: **VSM · kaizen · 5S · SMED · kanban/pull · A3 · standard work · DMAIC** · process-data analysis · bottleneck/constraint analysis.
- Domain: Lean / TPS · Six Sigma · theory of constraints · OpEx program design.
- Regulatory: change-control discipline where processes touch quality systems.
- Maverick: analyzes and proposes improvements; **process changes are human-approved**; never alters a running line or control parameter.

#### C3 Process-Safety (PSM/RMP) Agent  [UB]
JD: Process-safety management for chemical/process plants (distinct from general EHS).
- Systems: the PHA/HAZOP toolset · the EHS suite · permit systems · `knowledge_search`.
- Technical: **PHA/HAZOP/LOPA** facilitation support · **LOTO / confined-space / hot-work** permit review · MOC review · incident-investigation support.
- Domain: **OSHA PSM (1910.119) · EPA RMP** · the 14 PSM elements · mechanical integrity.
- Regulatory: **OSHA 1910.119, EPA RMP (40 CFR 68)**.
- Maverick: **safety is a refusal, not a gate** — never authorizes a permit or overrides an interlock; drafts analyses for the human process-safety owner.

#### C4 Trade-Compliance / Export-Control Agent  [UB]
JD: Owns export-control and trade compliance in-band (cross-ref legal 6.3).
- Systems: the ERP (item/BOM master) · denied-party-screening tools · classification databases · `knowledge_search`.
- Technical: **ECCN/EAR** classification · **deemed-export** screening · denied-party / **Entity List** screening · **rules-of-origin / FTA (USMCA)** analysis · **FTZ / duty drawback** modeling.
- Domain: **EAR (de minimis, Entity List, the 2022–23 semiconductor controls) · ITAR/USML + DDTC · OFAC · UFLPA forced-labor · CTPAT**.
- Regulatory: **EAR, ITAR, OFAC, UFLPA, USMCA, CBP**.
- Maverick: classifies and screens, drafts filings; **an export decision / license position is human (and counsel where required)**; blocks on a screening hit.

#### C5 Industrial / Production-Engineering Agent  [UB +Data]
JD: Designs the line and the work — capacity, flow, and automation integration.
- Systems: the MES/ERP · simulation/CAD tools · the planning/manufacturing seats.
- Technical: time/motion studies · line & **takt** design · capacity modeling · ergonomics analysis · **automation/robotics integration (AS/RS, AMRs)** specification.
- Domain: industrial engineering · line balancing · work-design · throughput analysis.
- Regulatory: machine-safety/ergonomics standards awareness (cross-ref EHS).
- Maverick: designs and models for human approval; **never commissions equipment or changes a running line**; safety-critical specs route to EHS/process-safety.

#### C6 Cold-Chain / Serialization Agent  [UB +Data]
JD: Regulated-vertical traceability depth beyond generic lot tracking (pharma/food).
- Systems: serialization/track-and-trace platforms · the WMS/ERP · temperature-monitoring (IoT) feeds.
- Technical: lot/serial/aggregation management · **temperature-excursion** handling · chain-of-custody traceability · recall-trace support.
- Domain: **pharma DSCSA** · **food FSMA 204 traceability** · cold-chain validation.
- Regulatory: **DSCSA, FSMA 204, FDA 21 CFR Part 11** (records).
- Maverick: maintains traceability and flags excursions; **a hold/release or recall decision is human**; never alters a physical shipment or environmental control.

---

## Coverage

Every agent has a per-agent skill profile. Base roster (38 · 47 · 45 · 41 · 40 · 26 · 31 ·
33) = **301**, plus **45 council-added agents** (Finance +5 · IT-GRC +8 · GTM +5 · HR +5 ·
Product & Engineering +6 · Strategy +5 · Legal +5 · Operations +6) = **~346 agents**.

**Full profiles for the council-added seats (40/45).** The seven non-finance suites' council-added
agents have been promoted from one-line bullets to **full profiles** (JD + Systems/Technical/
Domain/Regulatory/Maverick), numbered `C1…Cn` under each "Council-added agents" block — so every
one of those seats has the same depth as the base roster and can actually execute its JD. The
**Finance** suite's 5 council-added seats are still summary bullets, left to land with the
finance suite's own build (to avoid colliding with that in-flight work).

**Council pass: complete.** A five-member adversarial council reviewed every suite; their
CRITICAL/IMPORTANT findings are applied (accuracy fixes, the staleness sweep, the 45 added
agents, and the new skill dimensions) — see "Adversarial council review (applied)" at the top.
Remaining work is the **incremental rollout**: applying the new dimension tags (`[S]/[C]/[K]`,
proficiency, Prereq/Verified/Judgment/Cert) and the MINOR depth items to *every* base entry
(they're applied to the council-added/updated ones now), promoting the **Finance** council seats
to full profiles alongside the finance build, and authoring the flagged new templates
(`sox_control`, `itgc`, `outreach_compliance`, …) and connectors.
