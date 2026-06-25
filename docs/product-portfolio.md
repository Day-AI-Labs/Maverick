# Lightwork — Product Portfolio & Pricing (Working Draft)

> **Purpose:** an internal working doc to (1) show the full scope of what's been
> built, (2) pick product/tier/pack **names**, and (3) seed the website.
>
> **Pricing is a directional starting point, not validated.** The numbers are
> hypotheses anchored to the competitor bands in
> [`research/commercialization/02-packaging-pricing-editions.md`](./research/commercialization/02-packaging-pricing-editions.md).
> Re-confirm against design partners before any external use.

## The shape — 4 products

1. **Lightwork Platform** — the core. Sold good-better-best: **Basic / Gold / Platinum**.
2. **Specialized Agent Packs** — turnkey departments of agents (Finance, Tax, …), priced as add-ons by group.
3. **Fleet Governance & Memory** — govern + learn from agents you didn't build. Stands alone.
4. **Custom Work** — bespoke agents, regime packs, regulated deployment, outcome-priced labor.

Everything else (channels, dashboard, IDE extensions, installers, deploy targets, SDKs)
is plumbing *inside* Product 1, not a separate thing to sell.

> **Data & learning principle (non-negotiable).** Each customer's usage improves
> *their own* isolated workforce — on their own data, inside their own boundary.
> Lightwork never pools, aggregates, or learns across customers: no hivemind, no
> telemetry, and one tenant's learning never feeds another's runs. The compounding
> benefit is the *customer's* (a bespoke, portable, sticky instance they own); our
> defensibility is the specialist packs, the governance/compliance control plane,
> and the switching cost that earned value creates — never a data network effect.
> Any cross-instance sharing (federated insight exchange) is opt-in, operator-run,
> signed, and consolidated lessons only — never raw data, never automatic.

---

## Canonical naming, editions & SKU map

> **This document is the single source of truth for product names, editions,
> tiers, and SKUs.** Three *independent* axes describe what a customer gets — do
> not conflate them:

| Axis | Values | What it means | Defined in |
|---|---|---|---|
| **Edition** (distribution) | **Community** *(planned — not yet shipped)* · **Enterprise** *(available now)* | Open-core split: a future stripped-down community on-ramp vs. the licensed commercial build. | [`enterprise/editions.md`](./enterprise/editions.md) |
| **Platform tier** (commercial pricing, within Enterprise) | **Basic · Gold · Platinum** | The good/better/best pricing tiers in this doc. | This doc (canonical) |
| **Billing-plan key** (multi-tenant entitlement) | `free` · `pro` · `enterprise` | Technical plan IDs an operator assigns *per tenant* for feature gating + quotas (`maverick.billing.DEFAULT_PLANS`) — **not** the sales-tier names. | Code (`billing.py`) |

Working tier labels (Basic/Gold/Platinum) are placeholders pending the
[Naming worksheet](#naming-worksheet). The earlier exploration in
[`research/commercialization/02-packaging-pricing-editions.md`](./research/commercialization/02-packaging-pricing-editions.md)
used **Community / Team / Enterprise** and a **$120K** entry-enterprise floor;
that teardown is **superseded by this document** for current naming and numbers
(the Platinum floor here is **$200K**). All pricing remains a directional
hypothesis — see the note at the top.

---

## Product 1 — Lightwork Platform

The governed agent platform itself. Each tier is a **superset** of the one below.
Basic makes agents *work and stay safe*; Gold makes them *pass a security/compliance
review*; Platinum makes them *improve over time and run in regulated/air-gapped
environments*.

### What's in each tier

| Capability | What it does (plain English) | **Basic** | **Gold** | **Platinum** |
|---|---|:---:|:---:|:---:|
| Recursive multi-agent swarm | Splits a big goal into pieces, spawns specialist agents to work them in parallel, and double-checks the result before answering. | ✓ | ✓ | ✓ |
| Multi-provider model routing | Run on any model (Claude, GPT, Gemini, local) and assign the best model to each job — no vendor lock-in. | ✓ | ✓ | ✓ |
| Hard budget caps | Set a dollar / time / token ceiling per run; the system stops itself before it overspends. | ✓ | ✓ | ✓ |
| Sandboxed execution (local + Docker) | Agents run code in an isolated container instead of on your machine, so nothing escapes. | ✓ | ✓ | ✓ |
| Skills + Knowledge (RAG) | Agents reuse learned "recipes" and answer grounded in *your* documents, with citations. | ✓ | ✓ | ✓ |
| 17 channels + Dashboard + CLI + MCP | Reach it from Slack/Teams/email/etc., a web dashboard, the terminal, or inside Cursor/Claude Code. | ✓ | ✓ | ✓ |
| Agent Shield | Screens every input, tool call, and output for prompt-injection, jailbreaks, and data theft. | Built-in rules | Full | Full |
| SSO/OIDC + RBAC + capability tokens | Log in with corporate identity; every agent gets least-privilege permissions it physically cannot exceed. | — | ✓ | ✓ |
| Tamper-evident signed audit + SIEM export | Every action lands in a cryptographically sealed trail you can verify offline and ship to your security tooling. | — | ✓ | ✓ |
| DSAR + erasure + retention | Fulfill "show me / delete my data" requests and auto-expire old data — GDPR/CCPA ready. | — | ✓ | ✓ |
| Enterprise mode (egress lock) | Locks data inside your boundary — even a successful attack can't move it out. | — | ✓ | ✓ |
| Governed Actions | Preview the effect of a risky action before it commits, and trace any outcome back to its cause. | — | ✓ | ✓ |
| Multi-tenancy + quotas + metering/billing | Run many teams or clients on one deployment — each isolated, each with its own spend cap and invoice. | — | ✓ | ✓ |
| Compliance & Assurance | Auto-generates the evidence auditors ask for (SOC 2, EU AI Act, privacy impact assessments). | — | ✓ | ✓ |
| Provable Learning | The workforce gets better from its own experience — and proves it never regressed (dreaming, hindsight, ROI proof). | — | — | ✓ |
| Cognitive Data Engine | Finds the failures that actually hurt outcomes, turns them into guardrails, and tests fixes in simulation first. | — | — | ✓ |
| Framework packs + regulatory content | Pre-built control mappings for HIPAA, ISO 42001, model-risk (SR 11-7), and a FedRAMP path. | — | — | ✓ |
| KMS / BYOK encryption-at-rest | Your data encrypted with your own keys; one tenant's key can never open another's. | — | — | ✓ |
| Air-gap / confidential-compute | Runs fully disconnected for classified/regulated environments, with a one-command readiness check. | — | — | ✓ |
| Federation / A2A | Link multiple Lightwork deployments (or other vendors' agents) into one coordinated, governed fleet. | — | — | ✓ |
| High-isolation sandboxes | Stronger isolation (microVMs, gVisor, Kubernetes) for untrusted or sensitive workloads. | — | — | ✓ |
| Support | — | Community | Standard SLA | Dedicated CSM + premium SLA |

> A free self-hosted **Community** on-ramp (runtime + safety primitives, single-tenant,
> local auth) can sit *below* Basic as the top-of-funnel, per the open-core line in the
> commercialization doc.

### Pricing — starting point (annual, placeholder)

| Tier | Anchor price | Why this band | Who buys it |
|---|---|---|---|
| **Basic** | **$18K / yr** | Above the ~$10K "this is a real system" credibility floor; near Vanta/Drata entry. | A team that wants a safe, working agent workforce, single-tenant. |
| **Gold** | **$90K / yr** | Between Vanta enterprise and OneTrust entry; this is the governance/control-plane tier. | An enterprise that has to pass security + compliance review. |
| **Platinum** | **$200K floor → $500K+** | OneTrust enterprise band; regulated, self-improving, federated. | Regulated/large enterprise: finance, health, gov, critical infra. |

---

## Product 2 — Specialized Agent Packs

**What a "pack" is:** a turnkey department of specialist agents. Each agent has a
fixed job, a least-privilege tool set, a risk ceiling, and a built-in maker-checker
discipline — it **drafts and recommends; a credentialed human reviews and commits**.
You don't prompt-engineer them; you switch them on. **1,902 agents across 53 suites.**

Packs attach to any platform tier and get *more* valuable on Gold/Platinum (the
governance and learning layers wrap around them).

### Flagship packs (deep enough to sell on their own)

**Office of the CFO — Finance** · *60 agents*
The finance org as agents: controllership, FP&A, treasury, assurance, and reporting,
with a hard "never move money without a human" guardrail, amount-aware approval
tiers, a segregation-of-duties linter, and OFAC/SDN sanctions screening.
*Examples:* 13-Week Cash Forecaster · Covenant Compliance · AP 3-Way-Match ·
Month-End Close Driver · Audit PBC Coordinator · Transaction Anomaly Monitor.
*Buyer:* CFO / Controller.

**Tax — for CPA firms** · *19 agents + pipeline*
A documents-to-draft workflow: classify and extract W-2 / the 1099 family / K-1 /
1098 → a standardized workpaper → a first-pass 1040 **plus the resident-state
return**, where *every line cites its source document* and anything out of scope is
an explicit open item. Ships a signed tax-law update channel (new law = a content
release, not a code release) and CCH Axcess / Thomson Reuters GoSystem connectors.
**Never files.**
*Examples:* Intake Checklist · Document Classifier · 1099/K-1 Extractors ·
Deduction & Credit Analysts · Notice-Response · E-file Status.
*Buyer:* CPA / accounting firm.

**Legal & Privacy** · *66 agents*
Contracts, litigation support, privacy regimes (GDPR/CCPA/PIPL/APPI + US state
laws), AI/emerging-tech counsel, antitrust, and board governance — with citation
verification that strips any authority it can't confirm.
*Examples:* Contract Drafting · CCPA/CPRA Rights · AI-Contract-Rider ·
Conflict Checker · Briefs & Pleadings Drafter · Citation Verifier.
*Buyer:* GC / legal ops.

### Corporate Function packs

**Human Resources** · *78 agents* — full talent lifecycle + compliance: hiring,
onboarding, comp benchmarking, benefits, payroll, leave, performance/PIP, ADA/PWFA
accommodations, FCRA background checks, DEI analytics, mandatory reporting.

**Sales & Go-to-Market (RevOps)** · *71 agents* — pipeline hygiene, account planning,
quoting/pricing, contract assembly, commissions, renewals, churn-save, competitive &
win-loss intel, AI-SDR oversight, consent-ledger reconciliation.

**IT GRC** · *76 agents* — IT governance/risk/compliance: AI-system inventory &
risk-tiering, fleet oversight, access reviews, cloud-posture, patch & backup
verification, agent-identity auth, DORA/SOC 2 evidence.

**Product Engineering** · *57 agents* — the software org as agents: code review, bug
triage, backlog, architecture docs, API design & docs, CI/CD, on-call incidents +
post-mortems, SLO/error-budget, accessibility, mobile.

**Operations & Supply Chain** · *53 agents* — end-to-end ops: control-tower
visibility, demand planning/sensing, contract-manufacturer liaison, customs,
cold-chain integrity, bill-of-materials, CAPA, OSHA/safety, carbon/CBAM passports.

**Customer Experience** · *41 agents* — support & service ops: live-chat copilot,
bill explanation, billing-dispute investigation, backlog grooming, regulatory
complaints, warranty claims, field-service scheduling, accessibility desk.

**Strategy & Corporate Development** · *41 agents* — corporate strategy & M&A: board
metrics, competitor-financials analysis, deal execution, portfolio/business-model,
OKR cadence, capital strategy, activist defense, merger-clearance awareness.

**Marketing** · *40 agents* — content ops, campaign briefs, ABM dossiers, brand/claims
compliance, case studies, competitor watch, attribution, asset library, analyst
relations, budget reforecast.

**Data & Analytics** · *31 agents* — reviewed ad-hoc SQL, dashboard auditing,
business-anomaly detection, forecasting with intervals, A/B experiment analysis,
data-catalog/lineage stewardship, access governance, warehouse-cost analysis, ML-ops.

**Security Operations** · *28 agents* — SOC workflows: incident scribe/timeline,
access-review runner, AppSec triage, cloud-posture, DLP event review, attack-surface
inventory, bug-bounty triage, cert/key expiry, insider-risk case prep, forensic readiness.

**Procurement** · *26 agents* — source-to-pay: requisition intake & policy check,
buy-channel routing, supplier-contract stewardship, terms comparison, price
benchmarking, 3-way-match exception clerk, P-card audit, dispute files.

**Executive Office** · *20 agents* — chief-of-staff layer: daily briefing, board-pack
assembler, meeting prep, executive scorecard, calendar strategist, delegation log,
investor-relations prep, crisis comms, government-affairs tracking, data-room admin.

**Facilities & EHS** · *20 agents* — environmental health & safety + facilities:
incident recording within regulatory timelines, permit/emissions reporting, EHS
training, emergency preparedness, chemical/SDS inventory, ESG data, lease admin.

### Industry Vertical packs

Each is the same idea, pre-tuned for an industry buyer and bundled with that
industry's regime/jurisdiction packs.

| Pack | Agents | What it covers |
|---|:---:|---|
| **Healthcare** | 38 | Claims status/denials/appeals, eligibility, chart prep, coding QA, credentialing, patient grievance, EHR hygiene. |
| **Banking** | 41 | ACH ops, CDD onboarding, loan boarding, CECL allowance, AML alert prep, covenant tracking, IRRBB/ALM, exam prep. |
| **Insurance** | 41 | Claim files, statutory acknowledgments, loss & LAE reserving, premium-audit disputes, catastrophe response, filings. |
| **Retail** | 35 | Assortment productivity, competitive pricing, e-commerce funnel, PDP audit, inventory rebalancing, order-fraud. |
| **Manufacturing** | 35 | APQP gates, CAPA closure, layered audits, capacity/SMED, downtime Pareto, gauge calibration, ECN routing. |
| **Construction** | 35 | Daily logs, change-order & delay-notice drafting, bid leveling, buyout tracking, COIs, closeout packages. |
| **Logistics** | 35 | Carrier selection/scorecards, freight claims, cold-chain, detention & demurrage, 3PL invoice audit, customs. |
| **Professional Services** | 30 | Engagement setup, client intake/AML, conflict checks, court-docket tracking, receivables, deliverable QA, CLE/CPE. |
| **Government Contracting** | 30 | FAR/DFARS clause checking, compliance matrices, CPARS, DCAA audit prep, CDRL, ITAR/EAR, DD-254/clearance. |
| **Education & Nonprofit** | 30 | Donor ops/research, enrollment funnel, course scheduling, accreditation evidence, endowment compliance, volunteers. |
| **Capital Markets** | 5 | Performance attribution & risk, trade surveillance / MNPI watch, client reporting, Form ADV/PF, research drafting. |
| **Utilities** | 5 | NERC CIP evidence, meter-to-cash billing, outage coordination, FERC/PUC rate-case prep, REC/RPS tracking. |
| **Real Estate** | 5 | Rent-roll reconciliation, lease abstraction, work-order triage, valuation support, capital-project draws. |
| **Pharma & Life Sciences** | 5 | eCTD submission prep, clinical document drafting, GxP deviations/CAPA, e-lab-notebook, pharmacovigilance intake. |
| **Telecom, Media & Tech** | 5 | Content metadata, network NOC triage, rights clearance, royalty calculation, subscriber billing. |
| **Hospitality** | 5 | Revenue management, guest-relations service recovery, group/events BEOs, reservations, property compliance. |

### Pack pricing — starting point (annual, placeholder, attaches to a platform tier)

| Pack type | Anchor price | Notes |
|---|---|---|
| Flagship (CFO / Tax / Legal) | **$60K / yr each** | Deepest workflows, highest willingness-to-pay. Tax can also be priced per-return or per-seat for firms. |
| Corporate Function pack | **$25K / yr each** | Bundle all 13 functions for ~$150K (vs. $300K+ à la carte). |
| Industry Vertical pack | **$75K / yr each** | Includes the industry's regime/jurisdiction packs. |
| Outcome-priced labor (optional) | **per completed unit** | e.g., per completed DSAR, per filed-ready return, per resolved ticket — aligns price to value without taxing usage. |

---

## Product 3 — Fleet Governance & Memory

A governed memory + oversight plane for agents you *didn't* build — Agentforce,
Copilot, custom in-house agents, open-source runtimes. They deposit their experience
into one roster-gated, Shield-scanned, tenant-isolated memory and recall lessons
from it; every read is audited, and value is broken out **per vendor**. It sells even
to organizations that never run Lightwork's own runtime, which is what makes it a
standalone product and not just a platform feature.

**Pricing — starting point:** **$75K / yr** standalone, or **included at Platinum**.

---

## Product 4 — Custom Work (Professional Services)

Bespoke labor powered by the **Agent Factory** (a business describes itself → Lightwork
synthesizes a validated, fail-closed custom department pack):

- Custom agent / department authoring for a specific business.
- Custom jurisdiction / regime / compliance packs.
- System-of-record connectors (CRM/ERP/ticketing/etc.).
- Regulated / air-gapped deployment engagements.
- White-glove onboarding and design-partner programs.

**Pricing — starting point:** custom department authoring from **$25K**; regulated/
air-gap deployment from **$50K**; outcome-priced labor modules per completed unit;
everything else time-and-materials.

---

## Consolidated pricing table (starting point)

| Product | SKU | Anchor (annual) |
|---|---|---|
| Platform | Basic | $18K |
| Platform | Gold | $90K |
| Platform | Platinum | $200K → $500K+ |
| Agent Pack | Flagship (each) | $60K |
| Agent Pack | Corporate Function (each) | $25K |
| Agent Pack | Industry Vertical (each) | $75K |
| Fleet Governance & Memory | Standalone | $75K |
| Custom Work | Engagement | from $25K |

**Example deal shapes**
- *Mid-market land:* Gold + Finance pack → **~$150K/yr**.
- *Regulated expand:* Platinum + Banking pack + Fleet Governance → **~$350K/yr**.
- *CPA firm:* Basic + Tax pack (or per-return) → **~$80K/yr**.

---

## Naming worksheet

The whole point of this doc — fill in the names. (Current labels are descriptive
placeholders.)

| Thing | Current placeholder | Proposed name |
|---|---|---|
| The company | Daybreak Labs | |
| The platform | Lightwork Platform | |
| Tier 1 | Basic | |
| Tier 2 | Gold | |
| Tier 3 | Platinum | |
| The agent-pack line | Specialized Agent Packs | |
| Flagship: finance | Office of the CFO | |
| Flagship: tax | Tax | |
| Flagship: legal | Legal & Privacy | |
| Product 3 | Fleet Governance & Memory | |
| Product 4 | Custom Work | |
| The learning capability | Provable Learning | |
| The causal engine | Cognitive Data Engine | |

---

## Notes & caveats

- **All pricing is a directional hypothesis**, anchored to competitor bands
  (OneTrust, Vanta, Drata, IBM watsonx.governance) documented in
  [`research/commercialization/02-packaging-pricing-editions.md`](./research/commercialization/02-packaging-pricing-editions.md).
  Validate with design partners before publishing.
- **Don't meter the audit log or charge per-agent** — it punishes the exact behavior
  a recursive swarm exists to produce. Agent count is a soft tier *band*, never a
  multiplier (see the commercialization doc, "What would kill us").
- The 32 packs all pass the quality gate (`maverick domains-lint`): every agent has a
  bounded persona, a least-privilege allow-list, an explicit deny-list, and a risk
  ceiling — 0 errors, 0 warnings across all 1,902.
