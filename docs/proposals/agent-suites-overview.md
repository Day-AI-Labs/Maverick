# Enterprise agent suites — quick reference

At-a-glance index of the business-function agent suites designed for the platform.
Full detail lives in the two companion docs; this is the summary to skim later.

- **Finance** → [`finance-agent-suite.md`](finance-agent-suite.md) — ~40 core agents, 7 towers (+ vertical packs)
- **IT / GRC / Privacy / Security / AI-Governance** → [`it-grc-agent-suite.md`](it-grc-agent-suite.md) — 47 agents, 10 towers
- **Sales / GTM (the revenue engine)** → [`sales-gtm-agent-suite.md`](sales-gtm-agent-suite.md) — ~45 agents, 8 towers
- **HR / People** → [`hr-people-agent-suite.md`](hr-people-agent-suite.md) — ~41 agents, 8 towers

Both build on [`../enterprise/architecture.md`](../enterprise/architecture.md)
(the three-layer control plane) and [`agent-factory.md`](agent-factory.md)
(domain packs). Status: draft design, on branch `claude/amazing-davinci-4Gw6P` (PR #915).

---

## The shared design model (both suites)

- **Each agent is one `DomainProfile` pack** — `compartment` seal + `persona` +
  attenuating `allow_tools`/`deny_tools` + `max_risk` + `allow_hosts` +
  `mcp_servers` + `knowledge_sources`.
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

**The one load-bearing gap to build:** amount-aware authorization (dollar/DoA
thresholds) — `governance.evaluate()` is action/risk-based, not amount-based.
Everything in L3 / the DoA matrix depends on it.

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
ITSM. Two **primitive** gaps: runtime **capability expiry/revocation** (`expires_at`
is modeled, not polled) and the **SoD/access-conflict linter**.

Many IT-ops items are **Process-only** — the agent orchestrates and *evidences* a
human/org workflow (provisioning, access reviews, change control), it doesn't
replace the people or the systems of record.

### The throughline

**Maverick's own primitives are the GRC controls, so the fleet governs itself** —
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

## Suggested first builds (highest leverage)

1. **Persona-wrapper packs** for the shipped engines — finance assessors and IT-GRC
   Towers 1–3/5 (fast wins, little new code).
2. **The amount/severity-aware policy** + the **Operating Profile compiler** with
   hard-floor validation — unlocks L3 automation and the DoA/discount matrix across all three suites.
3. **The SoD/access-conflict linter** + **capability expiry/revocation enforcement** —
   the two cross-cutting primitive gaps.
4. **The Supervisor operator console** (Layer A) — the keystone for live oversight (GRC + Revenue).
5. **The outbound gate + consent/suppression hard floor** (GTM) — must precede any
   sending agent; rides the shipped channels + consent + AI-disclosure layer.
6. **The employment-decision pack + bias-eval engine** (HR + AI-Gov) — consequential-
   decision records + mandatory human review + bias-audit export; gates every consequential
   HR agent and satisfies NYC LL144 / EEOC / EU AI Act Annex III.
