# Packaging, Pricing & Editions — the Open-Core Line

> Teardown #2 of 10 for the commercial pivot. Date: 2026-06-06.
> Scope: product editions, the free/paid cut, pricing model, and a concrete v1
> table for an **agent-governance + regulated-deployment** product positioned
> against OneTrust. Companion to `regulated-deployment-and-compliance-platform.md`
> and `agentic-os-and-enterprise-analysis.md`. External figures flagged **[verify]**.

## Bottom line

1. **Sell the control plane, give away the runtime.** The open-core line runs
   *under* the governance UI, not through it. The agent kernel (swarm, sandboxes,
   budgets, the *enforcement* primitives — signed audit, capabilities, RBAC,
   consent, erasure) stays MIT and self-hostable — that is the wedge, the demo,
   and the trust story. What you charge for is the **hosted, multi-tenant
   governance system-of-record**: the agent registry, framework-mapped evidence
   export, identity federation (SSO/OIDC + SCIM), the trust portal, regulatory
   content, and compliance-as-agentic-labor. *Enforcement is open; oversight,
   attestation, and federation are paid.*
2. **Price the platform, not the agents.** Per-agent pricing is the trap this
   category sets for itself — it taxes exactly the behavior a *recursive swarm*
   exists to produce (spawning sub-agents) and the behavior you want customers to
   adopt. Lead with a **platform fee tiered by governed-estate scope** (a soft
   agent/seat band, not a hard per-agent meter), plus modest consumption on a
   *cheap, defensible* unit. Never meter the audit log per event.
3. **Land cheap on a single framework; expand on scope, modules, and labor.** The
   cheap LAND SKU is a per-framework wedge in Vanta's price band; the EXPAND
   motion is OneTrust's six-figure module stack, taken via agent governance +
   automated labor where OneTrust is weakest.

## The market sets the price corridor

Verified competitor anchors (all quote-based; list prices are third-party
estimates — re-confirm before any external use):

| Vendor | Entry / LAND | Mid-market | Enterprise | Model |
|---|---|---|---|---|
| **OneTrust** | ~$10K min ACV (Q2 2026 floor) [verify] | Privacy Essentials ~$44K/yr [verify] | **$120K–$500K+**, up to $1M+ | Module-based, opaque; +$10–50K impl. |
| **Vanta** | ~$10K (SOC 2 only) | $30–50K (multi-framework + VRM) | $80–120K+ | Per-framework + headcount |
| **Drata** | $7.5–15K (1 framework) | $15–25K (2–3) | $25–100K+ | Per-framework tiers; +$5K/framework |
| **Secureframe** | ~$7.5K | ~$20K median ACV | $80K+ | Headcount × frameworks |
| **Credo AI** | — | $30–150K+ | $100K+ start | Subscription, custom (models, not agents) |
| **IBM watsonx.governance** | Lite (free) | Standard ~$38K/yr (5 use cases) | $10–25K/**mo** | $0.60/resource-unit + tiers |

**Reads.** (a) The floor for *anything enterprise-credible* is ~$7.5–10K — below
that you signal "tool," not "system of record." (b) **Willingness-to-pay is
highest where the work is labor and the risk is regulatory** — OneTrust's
six-figure deals are privacy-ops + GRC + TPRM, not infosec checklists, precisely
the human-populated workflows our swarm can run. (c) Per-framework (Vanta/Drata)
is a clean, legible LAND meter buyers already understand. (d) watsonx's
**resource-unit** model is the cautionary tale: "200 agent-message evaluations =
1 RU" *meters governance per agent action* — adopt more agents, pay more to watch
them. That is the anti-pattern (§What would kill us).

## Editions and the open-core line

Three editions. The line is drawn so the free tier is genuinely useful (drives
the self-host community and the "be compliant" Q1 story) while the paid tiers are
*essential at scale* — the standard open-core test.

- **Community (MIT, self-host, free).** The full **Governed Runtime**: swarm,
  sandboxes, `Budget`, and every *enforcement* primitive already in-tree — signed
  audit, attenuating capabilities, tool RBAC, consent/HITL, retention, GDPR
  erasure, PII/secret redaction, EU AI Act Art. 50, kill-switch. Single-tenant.
  Local auth only. This is the moat and the trust artifact; crippling it loses
  the wedge to AgentField and forks.
- **Team (paid, ~$15–40K/yr).** The hosted **control plane** for one org: the
  **agent registry** ("where are my agents, what can they do, what did they do"),
  **framework-mapped evidence export** (audit chain → SOC 2 / EU AI Act / NIST AI
  RMF controls), **SSO/OIDC + SCIM**, multi-tenancy, per-tenant **quotas**, SIEM
  export, the two-person rule, and a hosted dashboard/trust portal. One framework
  pack included; this is the LAND.
- **Enterprise (paid, $80K–$500K+/yr).** Everything in Team plus: additional
  **framework packs** (HIPAA/42001/SR 11-7/FedRAMP), **regulatory content
  library**, **compliance-as-agentic-labor** modules (DSAR fulfillment, ROPA-from-
  discovery, evidence collection, vendor-questionnaire completion — billed per
  module, OneTrust-style), KMS/BYOK encryption-at-rest, HIPAA BAA / DPA / SCCs,
  data-residency, FedRAMP path, dedicated CSM, premium support/SLA.

**The bright line:** anything that *enforces* policy on one tenant's own agents is
free. Anything that *federates identity*, *aggregates across tenants*, *attests to
a regulator/auditor*, *supplies regulatory content*, or *performs the compliance
labor* is paid. SSO-as-paid is the canonical open-core upsell and buyers accept
it.

## Pricing model — what actually fits governing agents

- **Per-seat:** wrong primary axis. Governance value scales with the *agent
  estate and regulatory surface*, not human headcount; agents do the work seats
  used to.
- **Per-agent:** **reject as the meter.** It perversely punishes adoption and is
  actively hostile to a recursive swarm that spawns sub-agents (caps at 64) — every
  governed agent becomes a line item, so teams under-register agents to save money,
  defeating the registry's entire purpose. Use agent count only as a *soft tier
  band*, never a hard multiplier.
- **Usage/consumption:** fine on a **cheap, decoupled** unit (governed-agent-hours,
  connector runs, or labor-module *outcomes* — e.g. a completed DSAR). **Never
  per-audit-event or per-evaluation** (the watsonx trap): metering the audit log
  suppresses the exact telemetry compliance depends on.
- **Platform fee + hybrid (recommended).** A platform fee tiered by estate scope
  (agents/seats/frameworks as legible bands) + outcome-based consumption on the
  labor modules. Hybrid correlates with materially higher NRR and growth than pure
  subscription [verify], and outcome-pricing (charge on a *completed* DSAR, not an
  attempt — cf. Intercom's $0.99/resolution) aligns price with value without
  taxing usage.

## What would kill us

- **Giving away the control plane.** If the registry + evidence export + SSO ship
  MIT, there is no enterprise product — only a runtime competitors monetize. The
  Q1 *enforcement* code is open; the Q2 *attestation/federation* control plane is
  the business. Hold that line.
- **Per-agent or per-audit-event metering.** Either one tells customers "govern
  fewer agents, log less." That is suicidal for a governance product and uniquely
  self-defeating for a swarm. The watsonx RU model proves the failure mode exists.
- **Pricing like a consumer tool.** A $20–99/mo SKU anchors us as a toy beneath the
  ~$7.5K credibility floor, attracts unservable SMBs, and forfeits the six-figure
  privacy-ops/GRC budgets where WTP actually lives. No prosumer tier.
- **Forecasting shock.** ~78% of IT leaders report surprise bills from usage
  pricing; ~90% of CIOs name cost-forecasting their top AI worry [verify].
  Uncapped consumption loses enterprise deals — every consumption line needs caps,
  alerts, and an annual-commit option.
- **Over-promising OneTrust breadth on day one.** The cookie CMP, hotline, and
  55-framework content corpus are not swarm-shaped; pricing Enterprise as if we
  ship them invites a feature-parity bake-off we lose. Price the wedge we own.

## Recommendations

Adopt the three-edition cut. Make **Team the LAND** (one framework, in Vanta's
band, fast self-serve-assisted close) and **Enterprise the EXPAND** (modules +
content + agentic labor, sales-led, OneTrust-displacing). Concrete v1:

| Edition | Price (annual) | Primary meter | Included | Paid add-ons |
|---|---|---|---|---|
| **Community** | $0 (MIT, self-host) | — | Full Governed Runtime; all enforcement primitives; single-tenant; local auth | — |
| **Team** | **$24K** (from ~$15K, 1 tenant) | Platform fee; soft band by agents+seats | Hosted control plane; agent registry; evidence export; **SSO/OIDC+SCIM**; multi-tenancy; quotas; SIEM export; two-person rule; 1 framework pack | +$8K / extra framework pack; governed-agent-hours over band |
| **Enterprise** | **$120K floor → $500K+** | Platform fee + outcome-based labor | All Team; KMS/BYOK; content library; BAA/DPA/SCCs; residency; FedRAMP path; CSM + SLA | Agentic-labor modules (DSAR, ROPA, evidence, questionnaires) **billed per completed outcome**; per-module GRC/TPRM |

Anchors chosen deliberately: Team's $15–24K sits between Drata Advanced and Vanta
mid-market — credible, not cheap. Enterprise's $120K floor matches OneTrust's
entry enterprise band [verify], with module + outcome expansion toward $500K+.
Every consumption line ships **capped, with alerts and annual-commit**. Frameworks
and labor modules are the land-and-expand levers; agent count is a *band*, never a
multiplier.

## Sources

- OneTrust pricing: <https://www.vendr.com/marketplace/onetrust>,
  <https://risclens.com/pricing/onetrust>,
  <https://www.enzuzo.com/blog/onetrust-pricing-for-compliance>
- Vanta / Drata / Secureframe: <https://costbench.com/software/compliance-management/vanta/>,
  <https://costbench.com/software/compliance-management/drata/>,
  <https://www.secureleap.tech/blog/secureframe-review-pricing-top-alternatives-for-compliance-automation>
- Credo AI: <https://co-aims.com/blog/credo-ai-review-2026-compliance-officers>,
  <https://www.openlayer.com/blog/post/credo-ai-reviews-pricing-alternatives>
- IBM watsonx.governance: <https://www.ibm.com/products/watsonx-governance/pricing>,
  <https://www.g2.com/products/ibm-watsonx-governance/pricing>
- Open-core / pricing models: <https://www.getmonetizely.com/articles/monetizing-open-source-software-pricing-strategies-for-open-core-saas>,
  <https://goteleport.com/blog/open-core-vs-saas-business-model/>,
  <https://www.chargebee.com/blog/pricing-ai-agents-playbook/>,
  <https://flexprice.io/blog/why-ai-companies-have-adopted-usage-based-pricing>
