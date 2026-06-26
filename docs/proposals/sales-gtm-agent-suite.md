# Sales / GTM agent suite — the revenue engine

**Status:** design / roadmap. Companion to
[`finance-agent-suite.md`](finance-agent-suite.md),
[`it-grc-agent-suite.md`](it-grc-agent-suite.md), and
[`../enterprise/architecture.md`](../enterprise/architecture.md). Indexed in
[`agent-suites-overview.md`](agent-suites-overview.md).

"GTM" here is the **whole go-to-market motion** — Marketing → Sales Development →
Sales/AE → Customer Success → Support, with RevOps and Enablement as the connective
tissue. ~50 agents (45 base + 5 council-added) across eight towers.

> **What makes GTM different from finance and GRC.** Those domains are *inward-
> facing* — the blast radius is the books or the control set. GTM agents are
> **outward-facing at scale**: they contact prospects, publish content, spend ad
> budget, and quote prices. A wrong send is a **reputational, deliverability, and
> regulatory** event (CAN-SPAM, GDPR/PECR, TCPA, FTC), not a mis-statement. So the
> product is again the **governance wrapper** — and Lightwork already owns the exact
> chokepoint: the multi-channel engagement layer, AI/bot disclosure, the consent
> gate, high-risk classification of every "send" tool, and rate/spend caps. GTM is
> **rich substrate, greenfield workflow.**

The cardinal rule for every agent below (the GTM analogue of finance's "never move
money"):

> *Research, draft, score, and recommend freely — but NEVER send an external
> message, publish content, spend ad budget, commit a price or discount, or change a
> customer record of account without the required human gate. And NEVER contact
> anyone who has opted out or whom you lack a lawful basis to contact.*

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How a GTM agent maps onto Lightwork](#2-how-a-gtm-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — eight towers](#5-the-roster--eight-towers)
   - [Tower 1 — Marketing & Demand Generation](#tower-1--marketing--demand-generation)
   - [Tower 2 — Sales Development (pipeline generation)](#tower-2--sales-development-pipeline-generation)
   - [Tower 3 — Sales / AE & Deal Desk](#tower-3--sales--ae--deal-desk)
   - [Tower 4 — Revenue Operations](#tower-4--revenue-operations)
   - [Tower 5 — Customer Success & Account Management](#tower-5--customer-success--account-management)
   - [Tower 6 — Customer Support & Service](#tower-6--customer-support--service)
   - [Tower 7 — Partnerships & Channel](#tower-7--partnerships--channel)
   - [Tower 8 — GTM Enablement, Strategy & Intelligence](#tower-8--gtm-enablement-strategy--intelligence)
6. [The Revenue Supervisor (Layer A)](#6-the-revenue-supervisor-layer-a)
7. [Compliance-regime packs (Layer B)](#7-compliance-regime-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

Status vocabulary as before: **Shipped** / **Partial** / **Gap** / **Process-only**.
GTM has a surprisingly strong base because the *engagement* primitives already exist.

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **Multi-channel engagement** (email, SMS, voice, WhatsApp, Slack, Telegram, Signal, Discord, Mastodon, Bluesky, Matrix, iMessage) | `packages/maverick-channels/` (13 adapters) | **Shipped** | SDR (2.2), Nurture (1.6), Social (1.3), Support (6.1) |
| **AI / bot disclosure** (EU AI Act Art 50, CA SB 1001) | `compliance.py` (`first_turn_disclosure`) | **Shipped** | every customer-facing agent |
| **"Send" tools classified high-risk** (the gate basis) | `safety/tool_risk.py` (`email`/`gmail`/`ses`/`sns`/`twilio`/`slack_bot`/…) | **Shipped** | the outbound gate (§3.1) |
| **Human-in-the-loop send gate** | `safety/consent.py` (`ask`/`dashboard`) | **Shipped** | every outbound action |
| **Cadence / sequence scheduling** | `scheduler.py`, `worker.py` | **Shipped** | Sequencing (2.4), Nurture (1.6) |
| **Conversational lead intake** | `intake.py` | **Shipped** | Inbound qual (2.1), Support (6.1) |
| **Conversation / contact memory** | `world_model.py` | **Shipped** (CRM connector is the system of record → build) | all |
| **Volume / spend / deliverability caps** | `safety/rate_limiter.py`, `quotas.py`, `net_concurrency.py`, `budget.py` | **Shipped** | §3.8 |
| **Data privacy** (PII redaction, egress/residency, encryption) | `safety/pii_detector.py`, `enterprise.py`, `crypto_at_rest.py` | **Shipped** | §3.7 |
| **Prospect/customer data rights** (DSAR, erasure, ROPA) | `dsar.py`, `audit/erase.py`, `ropa.py` | **Shipped** (reuse the privacy suite) | §3.7 |
| **Discount/approval gate** | `governance.py` (+ amount-aware policy) | **Partial** (amount-aware is the shared finance build) | Deal Desk (3.4) |
| **Knowledge** (battlecards, pricing, product) | `knowledge_search` | **Shipped** | most |
| **Web research** | `web_search` | **Shipped** (deep enrichment via connectors → build) | SDR research (2.3) |
| **Creative / web / collateral / meetings / email** | Figma, Wix, Google Drive, Google Calendar, Gmail (live MCP) | **✅ connectors exist** | Brand (1.5), Content (1.2), Events (1.8), Booking (2.5) |
| **Tamper-evident record** | the signed Merkle audit chain | **Shipped** | every send + CRM mutation + approval |

**The headline gaps** (no code): the systems-of-record + business workflow — CRM,
marketing automation (MAP), CPQ, CLM/e-sign, sales-engagement, conversation
intelligence, enrichment/intent, ads, CS & support platforms; plus lead scoring,
attribution, deal-desk workflow, forecast roll-up, commissions, territory/quota,
churn/health models, partner/PRM, and win-loss. These are §9 connectors + new packs.

---

## 2. How a GTM agent maps onto Lightwork

Same as the other suites: each agent is one
[`DomainProfile`](../../packages/maverick-core/maverick/domain.py) pack (compartment
+ persona + attenuating capability + tools + knowledge), governed by Layer A
(`governance.py`), the consent gate, and the signed audit chain. Two GTM specifics:

- **The customer-facing agents are personas over the shipped channels layer** — an
  AI SDR is a channel-bound agent with the `first_turn_disclosure` prepended and its
  `send` tool behind the consent gate. The pattern already runs in production for the
  support/assistant channels.
- **Outbound is the risk axis.** Where finance gates *money* and GRC gates *control
  changes*, GTM gates *what leaves the building to a human on the other side* —
  enforced by classifying every send/publish/spend tool high-risk and routing it
  through consent/governance.

---

## 3. The control model (cross-cutting)

### 3.1 The outbound gate (cardinal control)
Every external send, publish, post, or ad-spend is a high-risk action routed through
`governance.evaluate()` → `require_human` (or an automation tier, §4.1). Email/SMS/
social/voice tools are *already* `high` in `tool_risk.py`, so the gate is wiring, not
new classification. Agents draft; the send is gated.

### 3.2 Consent, permission & suppression (the hard floor)
The non-negotiable GTM control: **never contact a party who has opted out, is on a
do-not-contact/DNC list, or for whom there is no lawful basis.** A **suppression +
consent check** precedes *every* outreach action; unsubscribe/opt-out is honored
immediately and recorded. Covers CAN-SPAM, GDPR/ePrivacy (PECR), CASL, and TCPA/DNC
for calls/SMS. Lead-source **provenance** is checked too (bought/scraped lists are a
lawful-basis risk). Reuses the privacy suite's consent + PII primitives; this floor
cannot be lowered by any client profile (§4.2).

### 3.3 AI / bot disclosure
Customer-facing agents disclose they are AI where required (EU AI Act Art 50, CA SB
1001). **Shipped** — `compliance.py` `first_turn_disclosure` prepends it on the first
turn of every channel conversation; the GTM agents inherit it for free.

### 3.4 Pricing & discount authority (deal desk)
The maker-checker pattern from finance, applied to **margin**: a discount beyond a
floor, a non-standard term, or a price override routes to the deal desk / a human per
an **amount-aware approval matrix** (the same `require_human_above` policy the finance
suite needs — shared build). List-price quotes can auto-issue; everything below the
margin floor is gated.

### 3.5 Brand, claims & messaging governance
Published content, ad copy, and outbound messaging are reviewed before they go out:
**brand-voice** adherence, **FTC truth-in-advertising / substantiation** (no
unsupported claims), no unauthorized **competitive** claims, and regulated-industry
rules (HIPAA marketing, FINRA/SEC advertising) where the vertical applies. Content is
*drafted* by the agent and *approved* by a human (or an enablement-approved template)
before publish — the analogue of finance's "draft, don't post."

### 3.6 CRM & forecast integrity
Pipeline and forecast changes are **audited** (who/what/when on every stage move);
agents never fabricate activity; the **forecast submitted to finance is human-
committed** (it feeds the finance Forecasting agent). Light separation of duties: the
agent that advances a deal is not the one that "calls" the forecast, and **not** the
one that computes the rep's **commission** (which overlaps finance payroll).

### 3.7 Data privacy, provenance & residency
CRM holds customer/prospect PII → reuse `pii_detector`, egress/residency lock,
encryption at rest, and the **DSAR/erasure** path (a prospect is a data subject with
access/deletion rights, incl. CCPA sale/share opt-out). Lead data provenance is
recorded (§3.2).

### 3.8 Volume, deliverability & spend caps
Outreach respects per-channel **rate limits** (domain/sender reputation), per-run
**budget**, and **ad-spend caps** — reusing `rate_limiter`, `quotas`,
`net_concurrency`, `budget`. No agent can blast a list or overspend a campaign.

### 3.9 Contracts & signature
Agents assemble order forms and redline against the standard template, but **never
sign or counter-sign**; non-standard terms route to **legal/human** (overlaps the
legal domain + CLM).

### 3.10 The record
Every outbound message, CRM mutation, discount approval, and published asset is
written to the signed Merkle audit chain — the evidence trail for marketing-consent
audits, deal reviews, and dispute resolution.

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder (per action class)
The L0–L4 ladder, with GTM examples:

| Level | GTM behaviour |
|---|---|
| **L0 Observe** | research accounts, score leads, recommend plays — no outreach |
| **L1 Draft** *(default for outbound)* | draft the email/post/quote; a human sends/publishes |
| **L2 Approve** | send/publish/quote after per-item human sign-off |
| **L3 Auto-under-threshold** | auto-send to *consented* contacts below a volume/risk floor; auto-quote at list price; auto-reply to inbound — exception-routed above the floor *(amount/volume-aware build)* |
| **L4 Straight-through** | always-on inbound chat (with AI disclosure) and opted-in nurture, autonomous within policy/budget; humans review samples |

Example: an SDR can be **L3** for follow-ups to opted-in inbound leads, **L2** for
cold outbound, and **L0** for anything to a net-new enterprise logo.

### 4.2 Hard floors — never auto, no matter the tier
The profile compiler refuses to lower these below a human gate:
- contacting a **suppressed / opted-out / no-lawful-basis** party (a hard **deny**);
- a **discount/term beyond the margin floor**;
- **signing a contract** or committing non-standard terms;
- **publishing a regulated or competitive claim** without review;
- **ad spend above the campaign cap**;
- **exporting or selling** customer data;
- **omitting AI disclosure** where it is legally required.

### 4.3 GTM motion
PLG / sales-led / channel-led / hybrid — sets which towers are primary. A PLG SaaS
leans on Marketing + Support + CS + product-qualified routing and a light AE tower;
an enterprise motion leans on SDR + AE + Deal Desk + Partnerships.

### 4.4 Discount-authority matrix
Per product/segment/currency: discount bands → required approver (rep / manager /
deal desk / VP / CFO) — the GTM DoA matrix, compiled to the amount-aware policy
(shared with finance §3.3 there).

### 4.5 Brand & messaging guardrails
Brand voice, prohibited claims, approved value props/competitive framing, tone, and
the approved-template library — a per-client knowledge source every content/outbound
agent must conform to (§3.5).

### 4.6 Consent & suppression rules per jurisdiction
Which regimes apply (CAN-SPAM / PECR / CASL / TCPA / CCPA), default opt-in vs opt-out,
cookie-consent posture, and the suppression sources — strictest-wins union (§7).

### 4.7 Channels, ICP & connectors
Which channels are enabled (and their rate caps), the ICP/segmentation definition,
and which CRM/MAP/CPQ/ads/CS systems back each agent.

### 4.8 The GTM Operating Profile
One signed, versioned bundle (intake produces, the wizard edits, rule 6) compiling to
capability + governance policy + consent config + enabled regimes + brand guardrails
+ the discount matrix — the GTM analogue of the Finance/GRC Operating Profiles.

---

## 5. The roster — eight towers

~45 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**,
**Status**. Connectors marked `‹build›` are §9. Representative packs are full TOML.

---

### Tower 1 — Marketing & Demand Generation

#### 1.1 Demand-Gen & Campaign Agent
- **Job:** Plan and orchestrate multi-channel campaigns — audience, offer, channel
  mix, budget, calendar; draft assets; measure pipeline contribution.
- **Connects to:** MAP (Marketo/HubSpot) + ads (Google/Meta/LinkedIn) `‹build›`,
  the channels layer, `scheduler.py`.
- **Capability:** read performance + `draft_campaign`. **Denies** publish + ad-spend.
- **Controls:** spend cap (§3.8); launch is `require_human`.
- **Status:** **Partial** (channels + scheduler shipped; MAP/ads to build).

#### 1.2 Content & SEO Agent
- **Job:** Content briefs, drafts (blog/landing/whitepaper), SEO optimization, the
  content calendar.
- **Connects to:** CMS / **Wix** (live), web analytics (GA4) `‹build›`, `knowledge_search`.
- **Capability:** `draft_content`, `seo_audit`. **Denies** publish.
- **Controls:** brand/claims review before publish (§3.5); accessibility (WCAG).
- **Status:** **Partial** (Wix connector exists; CMS/GA4 to build).

#### 1.3 Social & Community Agent
- **Job:** Draft/schedule social posts, monitor mentions, engage and moderate community.
- **Connects to:** social channels (Bluesky/Mastodon/Discord shipped; LinkedIn/X `‹build›`).
- **Capability:** `draft_post`, `monitor_social`. **Denies** post (gated).
- **Controls:** brand voice; AI disclosure; no unapproved claims.
- **Status:** **Partial**.

#### 1.4 Product Marketing Agent
- **Job:** Positioning, messaging, launch plans, **battlecards**, competitive framing.
- **Connects to:** `knowledge_search`, the competitive-intel agent (8.3).
- **Capability:** `draft_messaging`, `draft_battlecard`. No publish.
- **Status:** **Gap**.

#### 1.5 Brand & Creative Agent
- **Job:** Brand-voice guardrails, creative briefs, design production.
- **Connects to:** **Figma** (live), Google Drive.
- **Capability:** `draft_creative_brief`, `gen_design`. No publish.
- **Status:** **Partial** (Figma connector exists).

#### 1.6 Lifecycle & Nurture Agent
- **Job:** Lifecycle/nurture email sequences; deliverability and list hygiene.
- **Connects to:** the **email channel** (shipped), MAP `‹build›`.
- **Capability:** `draft_sequence`, `send_to_segment` **gated**.
- **Controls:** **consent/suppression hard floor** (§3.2); rate/deliverability caps.
- **Status:** **Partial** (email + scheduler shipped).

#### 1.7 Marketing Ops & Analytics Agent
- **Job:** Attribution, funnel analytics, **lead scoring**, MAP data hygiene.
- **Connects to:** MAP, CRM, BI `‹build›`.
- **Capability:** read + `build_attribution`, `score_leads`. No sends.
- **Status:** **Gap**.

#### 1.8 Events & Webinar Agent
- **Job:** Event/webinar planning, invitations, registration, follow-up.
- **Connects to:** **Google Calendar** (live), event platforms `‹build›`, channels.
- **Capability:** `plan_event`, `draft_invites`. Sends gated; suppression honored.
- **Status:** **Partial** (calendar exists).

#### 1.9 PR & Comms Agent
- **Job:** Press materials, announcements, media monitoring, message consistency.
- **Connects to:** `web_search`, media DBs `‹build›`.
- **Capability:** `draft_press`, `monitor_media`. No external send.
- **Status:** **Gap**.

---

### Tower 2 — Sales Development (pipeline generation)

#### 2.1 Inbound Qualification Agent
- **Job:** Qualify inbound leads (MQL→SQL), respond fast, route, book meetings.
- **Connects to:** CRM `‹build›`, **Google Calendar**, the channels layer, `intake.py`.
- **Capability:** read + `qualify_lead`, `route_lead`, `book_meeting`. Replies gated/tiered.
- **Controls:** AI disclosure; consent on outbound follow-up.
- **Status:** **Partial** (channels + intake + calendar shipped; CRM to build).

#### 2.2 Outbound Prospecting (SDR) Agent
- **Job:** Research target accounts/contacts, draft **personalized** outreach, run
  multi-touch sequences, hand qualified meetings to AEs.
- **Connects to:** enrichment/intent (ZoomInfo/Apollo/6sense) `‹build›`, sales
  engagement (Outreach/Salesloft) `‹build›`, the channels layer, `web_search`.
- **Capability:** research + `draft_outreach`, `enroll_sequence`. **Denies** raw send
  outside the gated sequence.
- **Controls:** the **consent/suppression hard floor** (§3.2) and **AI disclosure**
  are the whole game here; volume/deliverability caps; lead-source provenance.
- **Status:** **Partial** (engagement substrate shipped; enrichment/sales-engagement to build).

```toml
# packages/maverick-core/maverick/domains/gtm_sdr.toml
name = "gtm_sdr"
compartment = "gtm_sales"
description = "Outbound sales development: account research and compliant outreach."

persona = """You are a Sales Development specialist. Research the account and person,
personalize every touch, and lead with value -- never a generic blast. You DRAFT
outreach and enroll contacts into approved, gated sequences; a human (or the tier
policy) releases the send. You NEVER contact anyone who has opted out, is on a
do-not-contact list, or whom we have no lawful basis to email/call, and you ALWAYS
honor an unsubscribe immediately. Disclose you are an AI assistant where required.
State the source of every contact; if a list's provenance is unclear, flag it and
stop rather than send."""

allow_tools = [
    "read_file", "web_search", "knowledge_search",
    "enrich_contact", "draft_outreach", "enroll_sequence", "check_suppression",
]
deny_tools = ["email", "sms", "twilio", "buy_list"]   # raw sends bypass the gate
max_risk = "medium"
mcp_servers = ["CRM_Salesforce", "SalesEngagement_Outreach"]   # ‹build›
knowledge_sources = ["gtm_playbooks", "gtm_icp", "gtm_brand"]
authoring = "manual"
```

#### 2.3 Lead Enrichment & Account-Research Agent
- **Job:** Firmographic/technographic enrichment, intent signals, account/stakeholder
  research feeding 2.2 and the AEs.
- **Connects to:** enrichment/intent `‹build›`, `web_search`.
- **Capability:** read + `enrich_contact`, `research_account`. No sends.
- **Controls:** data provenance + privacy (§3.7).
- **Status:** **Partial** (`web_search` shipped; enrichment connectors to build).

#### 2.4 Sequencing & Cadence Agent
- **Job:** Orchestrate multi-touch cadences across channels, A/B test, protect
  deliverability.
- **Connects to:** `scheduler.py`/`worker.py`, sales engagement `‹build›`, channels.
- **Capability:** `manage_cadence`. Sends inside the gated sequence only.
- **Status:** **Partial** (scheduler shipped).

#### 2.5 Meeting-Booking Agent
- **Job:** Book demos and hand off to the AE with context.
- **Connects to:** **Google Calendar** (live), CRM `‹build›`.
- **Capability:** `book_meeting`, `prep_handoff`.
- **Status:** **Partial/Shipped** (calendar exists).

---

### Tower 3 — Sales / AE & Deal Desk

#### 3.1 Account-Plan & Research Agent
- **Job:** Account intelligence, stakeholder maps, account/territory plans.
- **Connects to:** CRM `‹build›`, `web_search`, enrichment.
- **Capability:** read + `build_account_plan`. No sends.
- **Status:** **Partial**.

#### 3.2 Discovery & Solution Agent
- **Job:** Discovery prep, qualification (MEDDIC/BANT), solution mapping, demo scripts.
- **Connects to:** CRM `‹build›`, `knowledge_search` (product).
- **Capability:** `prep_discovery`, `map_solution`. No external send.
- **Status:** **Gap**.

#### 3.3 Proposal & Quoting (CPQ) Agent
- **Job:** Generate quotes/proposals, configure products, apply price book.
- **Connects to:** CPQ (Salesforce CPQ/DealHub) `‹build›`, `knowledge_search` (pricing).
- **Capability:** `draft_quote`. **Denies** committing a non-list price (→ Deal Desk).
- **Controls:** list-price quotes can auto-issue (tiered); discounts gated (§3.4).
- **Status:** **Gap** (CPQ connector to build).

#### 3.4 Deal Desk & Approvals Agent
- **Job:** Enforce the **discount/term approval matrix**, check margin, route non-
  standard terms, assemble the approval package.
- **Connects to:** CPQ `‹build›`, `governance.py` (amount-aware), the legal domain.
- **Capability:** read + `check_margin`, `route_approval`. **Denies** approving a
  deal itself (that's the human/DoA tier).
- **Controls:** the amount-aware DoA matrix (§4.4); discounts beyond floor = `require_human`.
- **Status:** **Partial** (governance gate shipped; amount-aware policy is the shared build).

```toml
# packages/maverick-core/maverick/domains/gtm_dealdesk.toml
name = "gtm_dealdesk"
compartment = "gtm_revops"
description = "Deal desk: discount/term approval, margin protection, quote integrity."

persona = """You are the Deal Desk specialist. Check every quote against the price
book and the approval matrix, compute the margin impact, and cite the policy band a
discount falls into. You ASSEMBLE the approval package and ROUTE it to the right
approver -- you never approve a discount, commit a non-standard term, or sign an order
form yourself. List-price, standard-term quotes may proceed per the tier policy;
anything below the margin floor stops for a human. State the margin and the policy
band for every deal."""

allow_tools = [
    "read_file", "knowledge_search",
    "check_margin", "lookup_price_book", "route_approval", "draft_order_form",
]
deny_tools = ["approve_discount", "commit_terms", "sign_contract"]
max_risk = "medium"
mcp_servers = ["CPQ_Salesforce", "CLM_Ironclad"]   # ‹build›
knowledge_sources = ["gtm_pricing", "gtm_discount_policy"]
authoring = "manual"
```

#### 3.5 Sales Engineering / POC Agent
- **Job:** Technical Q&A, POC plans, **security questionnaires** (overlaps GRC vendor-risk).
- **Connects to:** `knowledge_search`, the GRC compliance agent, CRM `‹build›`.
- **Capability:** `answer_technical`, `draft_poc_plan`. No commitments.
- **Status:** **Partial** (reuses the GRC assessment surface for security Qs).

#### 3.6 Negotiation & Closing-Support Agent
- **Job:** Negotiation prep, objection handling, mutual close plans.
- **Connects to:** CRM `‹build›`, `knowledge_search`.
- **Capability:** `prep_negotiation`, `draft_close_plan`. No commitments.
- **Status:** **Gap**.

#### 3.7 Contract / Order-Form Agent
- **Job:** Assemble the order form, redline vs. the standard template, hand off to CLM.
- **Connects to:** CLM/e-sign (DocuSign/Ironclad) `‹build›`, the legal domain.
- **Capability:** `draft_order_form`, `redline_vs_standard`. **Denies** sign/counter-sign.
- **Controls:** non-standard terms → legal/human (§3.9).
- **Status:** **Partial** (overlaps legal; CLM connector to build).

---

### Tower 4 — Revenue Operations

#### 4.1 Pipeline Analytics & Forecasting Agent
- **Job:** Pipeline health, deal inspection, **forecast roll-up** by rep/segment.
- **Connects to:** CRM + BI `‹build›`; **feeds the finance Forecasting agent**.
- **Capability:** read + `build_forecast`, `inspect_pipeline`. **Forecast commit is human.**
- **Controls:** forecast integrity (§3.6); no fabricated pipeline.
- **Status:** **Partial** (overlaps finance FP&A Forecasting).

#### 4.2 Territory, Quota & Capacity Agent
- **Job:** Territory design, quota setting, capacity/coverage modeling.
- **Connects to:** CRM `‹build›`, the headcount-plan agent (finance FP&A).
- **Capability:** read + `model_territory`, `propose_quota`. No commits.
- **Status:** **Gap**.

#### 4.3 Commissions & Incentive-Comp Agent
- **Job:** Calculate commissions/attainment against the comp plan; handle disputes.
- **Connects to:** CRM + comp tool `‹build›`; **finance payroll** for payout.
- **Capability:** read + `calc_commission`. **Payout is human-gated** (finance).
- **Controls:** **SoD** — not the agent that closes deals (§3.6); ties to payroll.
- **Status:** **Partial** (overlaps finance payroll).

#### 4.4 CRM Data Hygiene & Governance Agent
- **Job:** Dedup, enrich, validate, and govern CRM fields and data quality.
- **Connects to:** CRM `‹build›`, enrichment, `pii_detector`.
- **Capability:** read + `dedup_records`, `flag_data_quality`. Bulk writes gated.
- **Controls:** privacy (§3.7); change audit.
- **Status:** **Partial** (data primitives shipped).

#### 4.5 Lead Routing & Assignment Agent
- **Job:** Route leads/accounts by rules (round-robin, territory, ICP), enforce SLAs.
- **Connects to:** CRM `‹build›`.
- **Capability:** `route_lead`, `track_sla`.
- **Status:** **Gap**.

#### 4.6 GTM Systems & Process Agent
- **Job:** Manage the GTM tech stack, workflow automation, and process documentation.
- **Connects to:** the GTM tool APIs `‹build›`.
- **Capability:** read + `document_process`, `draft_automation`. Config changes gated.
- **Status:** **Gap**.

---

### Tower 5 — Customer Success & Account Management

#### 5.1 Onboarding & Implementation Agent
- **Job:** Onboarding plans, kickoff, time-to-value tracking.
- **Connects to:** CS platform (Gainsight/Catalyst) `‹build›`, PM tools, channels.
- **Capability:** `build_onboarding_plan`, `track_ttv`. Customer sends gated.
- **Status:** **Partial**.

#### 5.2 Adoption & Health-Scoring Agent
- **Job:** Usage/adoption analytics, **health scores**, risk signals.
- **Connects to:** product analytics (Amplitude) + CS platform `‹build›`.
- **Capability:** read + `score_health`, `flag_risk`. No sends.
- **Status:** **Gap**.

#### 5.3 Renewals Agent
- **Job:** Renewal forecasting, notices, paperwork prep.
- **Connects to:** CRM/CS `‹build›`, finance.
- **Capability:** `forecast_renewal`, `draft_renewal`. **Never auto-renew or commit price.**
- **Controls:** price/term gated via Deal Desk (§3.4).
- **Status:** **Partial**.

#### 5.4 Expansion / Upsell Agent
- **Job:** Whitespace analysis, expansion plays, upsell timing.
- **Connects to:** CS + product analytics `‹build›`.
- **Capability:** `find_whitespace`, `draft_expansion_play`. Outreach gated.
- **Status:** **Gap**.

#### 5.5 Churn-Risk & Save Agent
- **Job:** Churn prediction, save plays, escalation to CSM/exec.
- **Connects to:** CS + product analytics `‹build›`.
- **Capability:** read + `predict_churn`, `draft_save_play`.
- **Status:** **Gap** (also a finance assessment template, `churn_risk`, §8).

#### 5.6 QBR & Business-Review Agent
- **Job:** QBR decks, success plans, executive business reviews.
- **Connects to:** BI, **Google Drive**/Figma (decks), CS platform `‹build›`.
- **Capability:** `build_qbr`. No external send.
- **Status:** **Partial** (deck/collateral connectors exist).

#### 5.7 Advocacy & References Agent
- **Job:** Identify advocates, manage references, case studies, review generation.
- **Connects to:** CS platform `‹build›`, channels.
- **Capability:** `identify_advocates`, `draft_case_study`. Outreach gated + consented.
- **Status:** **Gap**.

---

### Tower 6 — Customer Support & Service

#### 6.1 Support Triage & Deflection Agent
- **Job:** Tier-1 support: triage tickets, answer from the KB, deflect, escalate —
  the highest-volume customer-facing agent.
- **Connects to:** support platform (Zendesk/Intercom) `‹build›`, the **channels
  layer** (shipped), `knowledge_search`, `intake.py`.
- **Capability:** `triage_ticket`, `answer_from_kb`, `escalate`. Replies tiered (L3/L4
  for known answers; L2 for novel).
- **Controls:** **AI disclosure** (shipped); escalate rather than guess; no commitments.
- **Status:** **Partial** (channels + disclosure + intake shipped; support platform to build).

```toml
# packages/maverick-core/maverick/domains/gtm_support.toml
name = "gtm_support"
compartment = "gtm_service"
description = "Tier-1 customer support: triage, KB answers, deflection, escalation."

persona = """You are a Customer Support specialist. Answer ONLY from the knowledge
base and the customer's verified context; cite the article. Disclose that you are an
AI assistant at the start of the conversation. When you are not confident, or the ask
involves a refund, credit, commitment, or account change, ESCALATE to a human rather
than guess -- you make no commitments on the company's behalf. Be concise, empathetic,
and never expose another customer's data."""

allow_tools = [
    "read_file", "knowledge_search",
    "triage_ticket", "answer_from_kb", "escalate", "reply_in_channel",
]
deny_tools = ["issue_refund", "change_account", "commit_terms"]
max_risk = "medium"
mcp_servers = ["Support_Zendesk"]   # ‹build›
knowledge_sources = ["support_kb", "product_docs"]
authoring = "manual"
```

#### 6.2 Knowledge-Base & Self-Service Agent
- **Job:** Author and maintain the KB and help content from resolved tickets + product
  changes; spot gaps.
- **Connects to:** support platform + CMS `‹build›`, `knowledge_search`.
- **Capability:** `draft_kb_article`, `flag_kb_gap`. Publish gated.
- **Status:** **Partial**.

#### 6.3 Escalation & Customer-Incident Agent
- **Job:** Manage escalations and customer-facing **status communications** during
  incidents; coordinate with eng/IR.
- **Connects to:** support + status page `‹build›`, the GRC incident agent (6.3 there).
- **Capability:** `manage_escalation`, `draft_status_update`. External posts gated.
- **Status:** **Partial** (ties to the GRC IR workflow).

#### 6.4 Voice-of-Customer & CSAT Agent
- **Job:** Run CSAT/NPS, synthesize sentiment and feedback, route to product.
- **Connects to:** survey tools `‹build›`, product.
- **Capability:** read + `synthesize_feedback`. Surveys gated + consented.
- **Status:** **Gap**.

---

### Tower 7 — Partnerships & Channel

#### 7.1 Partner Recruitment & Onboarding Agent
- **Job:** Recruit, **vet** (reuse GRC vendor-risk), and onboard partners.
- **Connects to:** PRM `‹build›`, the GRC vendor-risk assessment.
- **Capability:** `research_partner`, `run_assessment` (vendor_risk), `draft_onboarding`.
- **Status:** **Gap** (reuses the shipped vendor-risk template for vetting).

#### 7.2 Partner Enablement & Co-Sell Agent
- **Job:** Enable partners, support co-sell, manage **deal registration**.
- **Connects to:** PRM `‹build›`, CRM.
- **Capability:** `enable_partner`, `register_deal`. Approvals gated.
- **Status:** **Gap**.

#### 7.3 Marketplace & Alliance Agent
- **Job:** Manage marketplace listings (AWS/Azure/GCP/app stores) and strategic alliances.
- **Connects to:** marketplace APIs `‹build›`.
- **Capability:** `manage_listing`, `draft_alliance_plan`. Listing changes gated.
- **Status:** **Gap**.

---

### Tower 8 — GTM Enablement, Strategy & Intelligence

#### 8.1 Sales Enablement & Content Agent
- **Job:** Playbooks, battlecards, enablement content, rep onboarding/certification.
- **Connects to:** LMS/enablement `‹build›`, `knowledge_search`.
- **Capability:** `draft_playbook`, `build_enablement`. Publish gated.
- **Status:** **Partial**.

#### 8.2 Conversation Intelligence & Coaching Agent
- **Job:** Analyze recorded calls (Gong/Chorus-style), coach reps, track talk-track
  adherence and risk language.
- **Connects to:** conversation intelligence `‹build›`, the **voice channel**, CRM.
- **Capability:** read transcripts + `analyze_call`, `draft_coaching`.
- **Controls:** **call-recording consent** (two-party-consent states) — a hard floor.
- **Status:** **Partial** (voice channel shipped; CI connector to build).

#### 8.3 Competitive & Market-Intelligence Agent
- **Job:** Track competitors, run **win/loss** analysis, market/TAM and ICP research.
- **Connects to:** `web_search`, CRM (win/loss), `knowledge_search`.
- **Capability:** read + `track_competitor`, `analyze_win_loss`. No sends.
- **Status:** **Partial** (`web_search` shipped).

#### 8.4 GTM Strategy & Planning Agent
- **Job:** GTM planning, segmentation, ICP definition, pricing/packaging analytics.
- **Connects to:** BI, CRM `‹build›`, finance.
- **Capability:** read + `build_gtm_plan`, `analyze_pricing`. No commits.
- **Status:** **Gap**.

---

### Council-added agents (from the adversarial review)

Five seats the council flagged — the three the brief named (Salesforce-dev, deliverability,
RevOps-data) were under-built. Full skills in [`agent-skills-catalog.md`](agent-skills-catalog.md).

- **Salesforce Admin / Developer Agent** *(Tower 4)* — Flow, Apex (triggers + async), SOQL/SOSL, governor limits, LWC, deployment (SFDX/unlocked packages/Gearset), security model, CPQ→Revenue Cloud. Splits the overloaded 4.4. **Status: Gap** (the seat that can actually "fix Salesforce errors").
- **Marketing-Ops / MarTech Engineer Agent** *(Tower 1)* — Marketo/HubSpot/MCAE build, lead scoring/lifecycle, GA4 + Consent Mode v2, server-side GTM, Meta CAPI/enhanced conversions, attribution. **Status: Gap** (1.7 is an analyst, not an ops engineer).
- **Deliverability / Email-Infrastructure Agent** *(Tower 1/2)* — SPF/DKIM/DMARC enforcement, BIMI/VMC, Google/Yahoo 2024 bulk-sender rules, Postmaster/SNDS, IP warmup. **Status: Gap** (smeared across 1.6/2.4 with no owner).
- **Revenue / GTM Data-Engineering Agent** *(Tower 4)* — warehouse-native GTM (Snowflake/BigQuery), reverse-ETL (Census/Hightouch), CDP (Segment), dbt funnel models, identity resolution. **Status: Gap** (the "RevOps engineering" the brief named).
- **Marketing-Privacy / Consent Agent** *(Tower 1)* — CMP (OneTrust), Global Privacy Control, CCPA Do-Not-Sell/Share, cookie consent, suppression sync. **Status: Gap.**

---

## 6. The Revenue Supervisor (Layer A)

Above the towers sits the **Revenue Supervisor** — the GTM instance of the oversight
control plane. It:

- **routes** a GTM task to the right tower agent across the funnel (a new inbound lead
  fans out to qualification → enrichment → SDR → AE), respecting compartment seals;
- **owns the outbound + approval queue** — every gated send, discount, publish, and
  contract lands here for human sign-off, with the consent/suppression check and the
  draft attached;
- **enforces the funnel SoD** — close ≠ forecast-call ≠ commission, by attenuated
  capability;
- **holds the brand/consent/discount policy** (§4) and the deliverability/spend caps.

Built on the shipped `governance.py` + `safety/consent.py` + the channels layer +
`fleet.py`; the operator console is the shared Layer-A gap (same as the other suites).

---

## 7. Compliance-regime packs (Layer B)

Strictest-wins union, same pluggable model. Several map to controls Lightwork already
enforces.

| Regime pack | Covers | Status |
|---|---|---|
| **EU AI Act Art 50 / CA SB 1001** | bot/AI disclosure | **Shipped** (`compliance.py`) |
| **CAN-SPAM** | US commercial email (opt-out, sender ID) | **Partial** (suppression check to build on the consent base) |
| **GDPR / ePrivacy (PECR)** | EU marketing consent + cookies + DSAR | **Partial** (DSAR/erase/egress shipped; marketing-consent ledger to build) |
| **CASL** | Canada anti-spam (express consent) | **Gap** |
| **TCPA / DNC** | US calls & SMS (consent, do-not-call) | **Gap** |
| **CCPA / CPRA** | sale/share opt-out, deletion | **Partial** (DSAR/erase shipped) |
| **FTC Act (truth-in-advertising, endorsement guides)** | substantiated claims, disclosed endorsements | **Gap** (claims-review workflow, §3.5) |
| **Call-recording consent** | one/two-party-consent states | **Gap** (gates 8.2) |
| **ADA / WCAG** | web/landing accessibility | **Gap** |
| **HIPAA marketing / FINRA-SEC advertising** | regulated-vertical messaging | **Gap** (vertical packs) |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code — same as the other suites):

| New `type` | Owner | Framework |
|---|---|---|
| `outreach_compliance` | SDR (2.2), Nurture (1.6) | consent / CAN-SPAM / GDPR-PECR / CASL / TCPA pre-campaign check |
| `marketing_claim_review` | Content (1.2), PMM (1.4) | FTC truth-in-advertising / substantiation |
| `deal_desk_review` | Deal Desk (3.4) | discount / term / margin approval checklist |
| `lead_data_provenance` | Enrichment (2.3) | lawful source of a contact list |
| `churn_risk` | Churn (5.5) | account-health risk scoring |
| `win_loss` | CI (8.3) | deal-retro structured review |

Each becomes a `run_assessment` capability + a conversational assessor via the
existing `build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Engagement channels** | email/SMS/voice/Slack/WhatsApp/Telegram/Signal/Discord/Mastodon/Bluesky/Matrix/iMessage | **✅ shipped** (`maverick-channels`) | SDR, Nurture, Social, Support |
| **Email / meetings / collateral** | Gmail, Google Calendar, Google Drive | **✅ exists** | 2.1, 2.5, 5.6, 1.8 |
| **Creative / web** | Figma, Wix | **✅ exists** | Brand (1.5), Content (1.2) |
| **CRM (system of record)** | Salesforce, HubSpot | ◻ build (P1) | most of Towers 2–5 |
| **Marketing automation (MAP)** | Marketo, HubSpot, Pardot | ◻ build (P1) | Marketing (T1) |
| **Sales engagement** | Outreach, Salesloft | ◻ build (P1) | SDR (2.2), Cadence (2.4) |
| **Enrichment / intent** | ZoomInfo, Apollo, Clearbit, 6sense | ◻ build (P2) | Enrichment (2.3) |
| **CPQ** | Salesforce CPQ, DealHub | ◻ build (P2) | Quoting (3.3), Deal Desk (3.4) |
| **CLM / e-sign** | DocuSign, Ironclad | ◻ build (P2) | Contract (3.7) |
| **Ads** | Google, Meta, LinkedIn Ads | ◻ build (P2) | Demand gen (1.1) |
| **Conversation intelligence** | Gong, Chorus | ◻ build (P3) | Coaching (8.2) |
| **CS platform** | Gainsight, Catalyst, ChurnZero | ◻ build (P2) | CS (T5) |
| **Support platform** | Zendesk, Intercom | ◻ build (P1) | Support (6.1) |
| **Product analytics / BI** | Amplitude, GA4, Looker | ◻ build (P3) | Health (5.2), MOps (1.7) |
| **PRM / marketplace** | partner portals, cloud marketplaces | ◻ build (P3) | Partnerships (T7) |

**Knowledge sources:** the ICP/segmentation definition, brand & messaging guardrails,
the price book + discount policy, battlecards, product docs, the support KB, and the
suppression/consent rules.

---

## 10. Build sequence

Wrap the shipped engagement substrate first; gate everything outbound from day one.

1. **The outbound gate + consent/suppression hard floor (do this first).** Wire the
   suppression/consent check ahead of every send, the AI-disclosure prepend (shipped),
   per-channel rate caps, and the `require_human`/tier routing. Plus the
   `outreach_compliance` assessment template (§8). *No agent sends before this lands.*
2. **CRM connector (the system of record) + Support (6.1) + SDR (2.2) + Nurture
   (1.6)** on the channels layer — the highest-volume, substrate-ready agents.
3. **Deal Desk (3.4) + Quoting (3.3)** on the amount-aware policy (shared finance
   build) — margin protection; **brand/claims review** (§3.5) for Marketing.
4. **RevOps depth:** forecasting (4.1, feeds finance), CRM hygiene (4.4), routing
   (4.5), commissions (4.3, ties to payroll).
5. **CS & expansion** (Tower 5) on the CS-platform connector; **Marketing depth**
   (MAP/ads); **conversation intelligence + coaching** (8.2, with recording consent).
6. **Partnerships** (Tower 7, reusing vendor-risk) and the vertical regime packs.
7. **Wizard + dashboard** (rule 6): channel/connector setup, the GTM Operating
   Profile / discount matrix / brand-guardrail editor, and the outbound-approval console.

---

## 11. Honest caveats

- **Outward-facing means the blast radius is reputation and the law, not the books.**
  One bad send to the wrong list is a CAN-SPAM/GDPR event and a brand event. The
  consent/suppression floor (§3.2) and the outbound gate (§3.1) are not optional and
  cannot be tuned off.
- **Agents draft; humans send, publish, sign, and commit price.** No agent signs a
  contract, commits a non-standard term, approves its own discount, or publishes a
  regulated claim — those are gated human acts the suite drafts and audit-trails.
- **Disclose the AI; never impersonate a human** where the law requires disclosure
  (Art 50, CA SB 1001, two-party call-recording consent). It's shipped — keep it on.
- **The CRM is the system of record, not the world model.** `world_model.py` is
  working memory; the CRM connector is the source of truth, and forecast/commission
  numbers must reconcile to it (and the forecast is human-committed before it reaches
  finance).
- **Personalization ≠ surveillance.** Enrichment must respect lawful basis and data
  provenance; bought/scraped lists are a liability, not a shortcut (§3.2).
- **Don't game the funnel.** Attribution, forecast, and pipeline integrity (§3.6)
  matter precisely because these numbers drive comp and the finance forecast — the
  signed audit of every stage change is the backstop.
