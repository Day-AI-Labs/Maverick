# GTM — ICP, Wedge Buyer, and Sales Motion for Maverick's Governance Pivot

> Teardown #6 of 10 for the commercial pivot. Date: 2026-06-06.
> Premise: Maverick stops being an MIT consumer/dev agent and becomes a
> commercial **AI-&-agent-governance + regulated-compliance** platform vs OneTrust.
> Scope: who we sell to, what we land, how we sell, who the first design partners
> are, and why the current repo positioning actively harms this business.
> Grounded in the two prior strategy docs (`regulated-deployment-and-compliance-platform.md`,
> `agentic-os-and-enterprise-analysis.md`) + a fresh GTM market pass.

## Bottom line

Sell to the **CISO**, not the DPO, not the AI-governance lead, not MRM. In 2026 the
CISO is the role that (a) absorbed AI risk into its mandate, (b) controls a budget
that is *growing*, and (c) feels the pain *now* via shadow agents — privacy counsel
and MRM are slower, more paperwork-driven, and don't hold a discretionary security
budget. The **land** is dead-simple and non-controversial: **"Where are my agents,
what can they do, and what did they do — proven, not asserted."** An agent registry +
tamper-evident action audit, deployable on-prem so nothing leaves the boundary. The
motion is **design-partner-led product-led *sales* (PLS)**, not PLG self-serve:
compliance/security buyers do not swipe a credit card for a governance platform. The
OSS heritage is a **lead-gen and credibility funnel for practitioners**, not a
distribution channel for the buyer — and the consumer-agent brand is baggage we must
shed deliberately. Land 3-5 design partners off the EU AI Act Aug-2-2026 forcing
function; expand from registry → evidence → agentic compliance labor.

## ICP and the wedge buyer

**ICP (first 18 months):** mid-to-large enterprises, **1,000-15,000 employees**, in
**EU-exposed regulated verticals** — financial services, insurance, health/pharma,
and regulated SaaS — that are (1) **already deploying internal AI agents** (coding
agents, SaaS-embedded copilots, MCP-connected workflow bots), and (2) **inside EU AI
Act high-risk scope** with the Aug-2-2026 deadline live. Not Fortune-100 (18-month
procurement, OneTrust already entrenched); not SMB (no governance budget, no agents
at scale yet). Sweet spot: big enough to have a named CISO and an AI committee, small
enough that one champion can drive a deal.

**The buyer — CISO (economic buyer + budget owner).** Defending the pick against the
alternatives:

- **CISO — PICK.** ~70% of CISOs now have AI explicitly added to scope, and ~54%
  expect budget *increases* in 2026; AI security spend is being embedded directly
  into enterprise AI investment. The CISO owns a real, discretionary security budget
  and is the one being asked "are our agents safe?" by the board. ([IANS](https://www.iansresearch.com/resources/all-blogs/post/security-blog/2026/02/06/the-cisos-expanding-ai-mandate--leading-governance-in-2026),
  [Sprinto](https://sprinto.com/blog/ai-governance-trends-ciso-reality-check/))
- **DPO / privacy counsel — secondary champion, not first buyer.** Owns GDPR/DPIA
  obligation but typically *influences* spend rather than holding the security
  budget; OneTrust already sits on this desk. Sell *with* them on the compliance
  expansion, don't lead with them.
- **AI-governance lead / CAIO — too new, budget too soft.** The role is real but the
  budget line is immature and frequently routed *through* the CISO/CRO in the
  cross-functional committee. ([EW Solutions](https://www.ewsolutions.com/the-enterprise-ai-governance-framework/))
- **Model-risk (MRM, banks) — high value, wrong *first* wedge.** SR 11-7 model risk
  is a deep, slow, validation-heavy buyer; it wants model cards, drift, and
  independent validation, not an agent registry. Land the CISO, *then* sell MRM the
  SR 11-7 evidence projection as expansion.
- **Platform/AI-eng leadership — the user, sometimes the technical sponsor.** They run
  the agents and will champion deployment, but they are a cost center, not a budget
  owner for governance. They are the OSS funnel's entry point, not the signer.

**Why CISO wins the economic argument:** the pain is *acute and current* (shadow
agents are being built by employees with "20 minutes and a credit card"), the buyer
*has* money, and the purchase is *defensive* — the easiest enterprise sale is "you
have an unmanaged risk; here is visibility and proof." ([Aona](https://aona.ai/blog/shadow-agents-enterprise-agentic-ai-2026/),
[Bessemer](https://www.bvp.com/atlas/securing-ai-agents-the-defining-cybersecurity-challenge-of-2026))

## The killer land use case

**"Agent visibility + provable action audit."** Most enterprises have *no accurate
inventory* of the agents in their environment — which exist, what permissions they
hold, who authorized them, what they did. Securing AI agents is being called *the*
defining security challenge of 2026, and 48% of practitioners name agentic/autonomous
systems the single most dangerous attack vector. ([Aona](https://aona.ai/blog/agentic-ai-security-risks-ciso-guide-2026/),
[Bessemer](https://www.bvp.com/atlas/securing-ai-agents-the-defining-cybersecurity-challenge-of-2026))

Maverick already has the substrate the prior docs verified: per-agent attenuating
capabilities, an Ed25519 Merkle-chained tamper-evident audit, a kill-switch, and a
default on-prem/air-gapped runtime. The land product is a **projection of data we
already emit**: a registry surface ("here are your agents, their owners, capabilities,
data access, EU AI Act risk tier") + **framework-mapped evidence export** that turns
the signed audit into auto-populated control evidence for AI Act logging/oversight,
SOC 2 audit-trail, and (later) SR 11-7 override records. It demos in one meeting, it
maps 1:1 onto the Aug-2-2026 deadline (deployer logging + Art. 14 human oversight),
and it does **not** require ripping out OneTrust. ([EU AI Act Art. 26](https://artificialintelligenceact.eu/article/26/),
[Art. 14](https://artificialintelligenceact.eu/article/14/))

## Sales motion — be brutally honest

**Design-partner-led enterprise PLS, not PLG.** The data is unambiguous: in security,
individual contributors can *recommend* but cannot *adopt* without senior signoff
because the purchase is trust-gated (SOC 2 review, "will you exist in 12 months,"
leadership meetings); and "it doesn't help to have a free signup for a GRC tool if
GRC people don't try products on their own." Pure PLG can *kill* a security startup.
([Venture in Security](https://ventureinsecurity.net/p/caveat-emptor-product-led-growth),
[PLG is not a boolean](https://ventureinsecurity.net/p/plg-is-not-a-boolean-practical-advice))

So:
- **Primary motion:** founder-led enterprise sales to 3-5 named design partners,
  converting a subset to first paying customers in months 7-12 of an ~18-month GTM —
  the standard design-partner arc. ([Unusual VC](https://www.field-guide.unusual.vc/field-guide-enterprise/the-modern-gtm-design-partner-installs-and-sales-process))
- **OSS as a funnel, *bounded*:** the open-source governed runtime is **lead-gen +
  proof-of-substance** — platform/AI-eng teams adopt it, generating warm intros to
  their CISO and instant technical credibility ("the audit chain is real code, here's
  the repo"). This is product-*led sales*, not self-serve. The OSS pattern of
  open-source wedge → enterprise upsell is well-trodden (e.g. c15t/consent SDK).
  ([YC compliance cohort](https://www.ycombinator.com/companies/industry/compliance))
- **Distraction guardrail:** do **not** invest in consumer/community growth (Discord
  contests, HN launches, channel breadth) as a *commercial* lever. It serves the old
  thesis and dilutes focus. Keep OSS alive as credibility; stop treating downloads as
  the KPI. Pipeline = design-partner meetings booked, not GitHub stars.

## Design-partner plan (first 3-5)

Profile: **EU-exposed regulated mid-enterprise, already running internal agents, with
a named CISO feeling Aug-2026 pressure.** Concretely target:

1. **An EU/UK bank or insurer** with an existing MRM function and a coding-agent
   rollout — AI Act high-risk + SR 11-7 expansion path. Land via the CISO; second
   stakeholder is MRM.
2. **A health/pharma org** handling PHI that wants agents but can't egress data —
   leads with self-host as the moat (the on-prem story neutralizes the SaaS-GRC
   data-residency objection).
3. **A regulated SaaS / fintech scale-up** (our OSS sweet spot) where platform-eng
   *already adopted the OSS runtime* — warmest path, fastest deploy, best logo-velocity.
4. **An EU public-sector / GovTech body** facing AI Act deployer obligations head-on.
5. **(Stretch) a model-risk team at a tier-2 bank** as the expansion-thesis proof.

**How to actually land them:** (a) ride the **Aug-2-2026 deadline** as the cold-open
("you have a logging + human-oversight obligation in weeks and no agent inventory");
(b) **warm intros from OSS adopters** — instrument which orgs run the governed
runtime, route platform-eng champions to their CISO; (c) **design-partner terms**:
free/steeply-discounted, deep access, co-build the registry + evidence export against
*their* AI Act controls, with a contractual path to a paid contract on GA. Offer a
**signable artifact** (audit-as-evidence pack) as the tangible deliverable, since
qualification-led enterprise deals need a concrete proof of value.

## Positioning baggage to fix

The current `README.md`/`ROADMAP.md` positioning is **actively harmful** to this
business and must change before any CISO meeting:

- **"General consumer — no AI expertise required."** A CISO buying agent governance
  cannot be sold by a homepage aimed at consumers running agents on their laptop. It
  signals "toy," not "system of record."
- **"No paid tier, no telemetry, MIT, building a brand for the founder"** (ROADMAP
  positioning line). "No paid tier" tells an enterprise buyer **there is no company to
  stand behind the product** — the exact fear ("won't disappear in three months") that
  trust-gated security buyers screen for. ([Venture in Security](https://ventureinsecurity.net/p/caveat-emptor-product-led-growth))
  And **"no telemetry" is incoherent for a governance product** whose entire value is
  observability and audit — though privacy-preserving, customer-controlled telemetry
  must be reframed as a *feature*, not abandoned.
- **The trust paradox: "the AI-agent company wants to sell me AI governance."** This is
  the single biggest objection. **Neutralize it by inversion:** *we built a compliance
  engine to police our own recursive swarm; the engine, pointed at your estate, is the
  product.* "We govern the hardest case — autonomous multi-agent swarms — and we eat
  our own dog food" turns the heritage from liability into proof. Lead with the
  **runtime/registry**, brand the consumer agent down to an internal reference impl.
- **Naming/brand:** keep the OSS project's name for the practitioner funnel, but the
  **commercial entity needs a security-credible identity, a trust portal (SOC 2, DPA,
  status, security.txt), and pricing** — none of which exist today.

## What would kill us

- **Trust gap stays unclosed:** no commercial entity, no SOC 2 Type II, no trust
  portal → trust-gated CISOs never sign, regardless of how good the tech is. **This is
  process/legal, and the clock starts now.**
- **PLG seduction:** chasing free-signup/community metrics, mistaking OSS downloads for
  pipeline, and never building the enterprise sales muscle the category *requires*.
- **Buyer drift:** trying to sell DPO + CISO + MRM simultaneously, landing none.
  Concentrate on the CISO land first.
- **Incumbent fast-follow:** OneTrust ships an "AI/agent governance" pillar, or
  CrowdStrike/Microsoft/Okta extend agent visibility from the security side and own the
  CISO relationship we need. Our defensibility is **runtime-enforced, on-prem,
  tamper-evident agent state** — must stay ahead on *enforcement*, not dashboards.
  ([CrowdStrike](https://www.crowdstrike.com/en-us/blog/new-crowdstrike-innovations-secure-ai-agents-govern-shadow-ai/),
  [Microsoft](https://www.microsoft.com/en-us/security/blog/2026/03/20/secure-agentic-ai-end-to-end/))
- **Deadline whiff:** the Aug-2-2026 forcing function is a window, not a permanent
  tailwind. Miss this design-partner cycle and the wedge urgency softens.

## Sources

- CISO budget/mandate: <https://www.iansresearch.com/resources/all-blogs/post/security-blog/2026/02/06/the-cisos-expanding-ai-mandate--leading-governance-in-2026>,
  <https://sprinto.com/blog/ai-governance-trends-ciso-reality-check/>,
  <https://www.ewsolutions.com/the-enterprise-ai-governance-framework/>
- Shadow agents / visibility / agent security as #1 2026 problem: <https://www.bvp.com/atlas/securing-ai-agents-the-defining-cybersecurity-challenge-of-2026>,
  <https://aona.ai/blog/shadow-agents-enterprise-agentic-ai-2026/>,
  <https://aona.ai/blog/agentic-ai-security-risks-ciso-guide-2026/>,
  <https://www.armorcode.com/blog/shadow-ai-in-the-agentic-era-who-owns-the-risk-governance>,
  <https://zenity.io/blog/security/ai-agent-governance>
- Incumbent fast-follow (CISO-side agent governance): <https://www.crowdstrike.com/en-us/blog/new-crowdstrike-innovations-secure-ai-agents-govern-shadow-ai/>,
  <https://www.microsoft.com/en-us/security/blog/2026/03/20/secure-agentic-ai-end-to-end/>
- EU AI Act Aug-2-2026 high-risk obligations (logging, oversight, penalties): <https://artificialintelligenceact.eu/article/26/>,
  <https://artificialintelligenceact.eu/article/14/>,
  <https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai>,
  <https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-high-risk-compliance-deadline-20/>
- PLG vs PLS in security/GRC (why self-serve fails, trust-gating): <https://ventureinsecurity.net/p/caveat-emptor-product-led-growth>,
  <https://ventureinsecurity.net/p/plg-is-not-a-boolean-practical-advice>
- Design-partner motion + OSS wedge → enterprise: <https://www.field-guide.unusual.vc/field-guide-enterprise/the-modern-gtm-design-partner-installs-and-sales-process>,
  <https://www.ycombinator.com/companies/industry/compliance>
- OneTrust landscape (context): <https://www.onetrust.com/solutions/ai-governance/>,
  <https://www.modulos.ai/best-ai-governance-platforms/>
