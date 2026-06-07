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

## Finance suite

40 agents ([finance-agent-suite.md](finance-agent-suite.md)). Cross-cutting finance skills
every agent here also carries: double-entry accounting fluency, the company **chart of
accounts**, **materiality** judgment, and the **stage-not-post / require_human-for-money**
discipline.

### Tower 1 — Controllership

#### 1.1 General Ledger & Close Agent  [UB +Data]
JD: Owns the period-end close — drafts journal entries, runs reconciliations and flux analysis, assembles the close binder.
- Systems: NetSuite · SAP S/4HANA · Oracle Fusion/EBS · QuickBooks/Xero (GL) · **BlackLine, FloQast** (close & recon) · OneStream/Hyperion HFM (consolidation).
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
- Technical: **depreciation schedules** (straight-line, DDB) · CWIP roll-forward · Excel modeling.
- Domain: capitalization policy & useful lives · **ASC 360 impairment** · disposals/transfers.
- Maverick: capitalize-vs-expense threshold · disposal `require_human`.

#### 1.6 Revenue Recognition Agent  [UB +Data]
JD: ASC 606 — reads contracts, runs the 5-step model, builds deferred-revenue schedules.
- Systems: Salesforce/CPQ · **Zuora / Stripe Billing / Zuora Revenue (RevPro)** · ERP rev JE · contract repository.
- Technical: contract analysis · **deferred-revenue & rev-waterfall schedules** · SSP allocation · variable-consideration estimates.
- Domain: **ASC 606 / IFRS 15 (5-step model)** · contract modifications · principal-vs-agent.
- Maverick: cite the contract clause · flag judgmental calls (SSP, variable consideration).

#### 1.7 Intercompany & Consolidations Agent  [UB +Data]
JD: Multi-entity consolidation — eliminations, FX translation, minority interest, consolidated statements.
- Systems: **Oracle FCCS, OneStream, Hyperion HFM** · multi-book ERP.
- Technical: **intercompany eliminations** · **FX translation (CTA)** · allocations · entity-tree roll-up.
- Domain: **ASC 810** (consolidation) · **ASC 830 / IAS 21** (FX) · minority/NCI.
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
- Domain: cost accounting · **FIFO/LIFO/weighted-average** · lower-of-cost-or-NRV · **E&O reserves** · landed cost · cycle-count reconciliation.
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
- Systems: **Kyriba** (TMS) · **Modern Treasury, Plaid** (bank aggregation) · bank portals · SWIFT messaging awareness.
- Technical: **cash positioning** across accounts · covenant calculation · short-term liquidity forecasting.
- Domain: liquidity & working capital · **debt covenants** · bank-account administration · sweep/pooling structures.
- Regulatory: bank KYC.
- Maverick: **propose-not-send** (denies wire/ACH/release) · dual approval over DoA threshold · covenant breach → alert.

#### 3.2 Investments / Portfolio Agent  [UB +Data]
JD: Manages the corporate investment portfolio per the IPS — researches, prices, proposes allocations.
- Systems: **Interactive Brokers (IBKR — already wired)** · **Bloomberg Terminal** · custodian APIs.
- Technical: **portfolio analytics** (yield, duration, credit quality, concentration) · security pricing · fixed-income math.
- Domain: money-market & **fixed-income** instruments · the **Investment Policy Statement** · FINRA/SEC basics for corporate investing.
- Maverick: **trade-propose-not-execute** (denies order tools, verbatim from `finance.toml`) · IPS limit enforcement · egress pinned to IBKR hosts.

#### 3.3 FX & Hedging Agent  [UB +Data]
JD: Quantifies currency exposure, proposes hedges, supports hedge-accounting docs.
- Systems: IBKR/bank FX · ERP exposure data · FX-rate feeds.
- Technical: **exposure quantification** (transaction & translation) · **hedge-effectiveness testing**.
- Domain: **ASC 815 / IFRS 9 hedge accounting** · FX risk · hedge designation/documentation.
- Maverick: hedge execution `require_human` · effectiveness method cited.

#### 3.4 Capital Markets & Debt Agent  [UB +Data]
JD: Debt/lease schedules, interest/amortization, covenant compliance, refinancing models.
- Systems: debt register · market-rate feeds · agent/bank statements.
- Technical: **amortization & interest schedules** · refinancing/issuance models · covenant compliance tests · maturity-ladder analysis.
- Domain: debt instruments · capital structure · credit ratings.
- Maverick: covenant breaches escalate · any draw/issuance `require_human`.

### Tower 4 — Tax

#### 4.1 Tax Provision Agent  [UB +Data]
JD: ASC 740 — current/deferred provision, ETR reconciliation, deferred-tax balances, tax footnote.
- Systems: **ONESOURCE Tax Provision, Corptax** · ERP trial balance · prior returns.
- Technical: **current & deferred tax computation** · **effective-tax-rate reconciliation** · DTA/DTL roll-forward · valuation-allowance analysis.
- Domain: **ASC 740 / IAS 12** · book-tax differences · **uncertain tax positions (FIN 48)**.
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
- Maverick: **independence (read-only)** · `run_assessment` (the `sox_control` / `itgc` templates) · deficiency = finding for a human owner.

#### 5.2 Internal Audit Agent  [UB +Assess]
JD: Risk-based audit planning, fieldwork, workpapers, findings, follow-up.
- Systems: **AuditBoard, TeamMate+** · all finance systems (read).
- Technical: risk-based audit planning · workpaper drafting · sampling & testing.
- Domain: **IIA Standards** · audit methodology · the three-lines model · root-cause analysis.
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
- Domain: **occupational fraud (ACFE)** · fraud schemes & red flags · SAS 99 fraud risk.
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
- Domain: **BSA/AML** · OFAC sanctions · **SAR/STR & CTR** thresholds · laundering typologies.
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
- Technical: dedup · **bank-detail validation** · **sanctions/PEP screening** · `run_assessment` (vendor_risk).
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
- **Fund & grant accounting:** fund-accounting GAAP (FASB 116/117) · grant-compliance · restricted-fund tracking.
- **Regulatory capital (banks/insurers):** **Call Reports / FR Y-9C / FINREP-COREP** · **Basel / Solvency II** capital math · regulatory-reporting tools.
- **Cost allocation (ABC):** activity-based costing · driver modeling.
- **Escheatment:** multistate unclaimed-property rules · UPExchange-style filing.

---

## Remaining suites (to append)

Same format, suite by suite — each agent's deep, named skills (the user's examples land in
these):

- **IT / GRC / Privacy / Security / AI-Gov** — e.g. **standing up & querying Oracle 23ai**,
  SIEM (Splunk/Sentinel) detection engineering, Okta/Entra IAM admin, Terraform/cloud
  security, ISO 27001 / SOC 2 control testing, EU AI Act conformity, DPIA/ROPA.
- **Sales / GTM** — e.g. **fixing data & automation errors in Salesforce** (validation rules,
  flows, dedup), HubSpot/Marketo ops, Outreach/Salesloft sequencing, CPQ, deliverability.
- **HR / People** — Workday/Greenhouse admin, bias-aware screening, comp benchmarking, FMLA/
  ADA/FLSA, OSHA recordkeeping.
- **Product & Engineering** — the coding kernel + the language/framework stack, the **8
  sandbox backends**, CI/CD, SQL/dbt/warehouses, MLOps, Figma/a11y.
- **Strategy / Corp Dev / Exec** — DCF/LBO modeling, data-room diligence, board-pack craft,
  the deep-research harness, MNPI/ethical-wall discipline.
- **Legal** — **the finer points of litigation procedure** (FRCP, discovery, motions),
  contract drafting/redlining against a playbook, **citation verification (CourtListener)**,
  privilege/e-discovery (Relativity), IP (USPTO).
- **Operations / Supply Chain** — ERP/MRP, WMS/TMS, MES, CMMS, demand planning, **OSHA &
  safety-critical refusal discipline**, customs/HS classification.
