# Competitive analysis: aiworkers.so (Workers Delos)

> Captured 2026-06-23. The site is a client-rendered SPA that blocks naive
> fetchers (403); the analysis below is extracted from the shipped JS bundle
> and structured-data tags. Verify against their live site before relying on
> any specific number — early-stage vendors change copy weekly.

## Who they are

- **Vendor:** Delos SAS — a Paris-based company (RCS Paris, 128 rue de Rivoli).
  Product brand "Workers" / "Workers Delos". `aiworkers.so` canonicalizes to
  `workers-delos.dls.so`. Site is bilingual FR/EN.
- **Category:** A **hosted SaaS marketplace of "AI coworkers"** — autonomous
  agents pre-built for specific business roles, sold like virtual employees.
- **Core pitch:** *"Not a chatbot you prompt. Real coworkers with their own
  email, phone number, and initiative. Working 24/7 without being asked."*
  Explicit positioning: *"most AI tools augment humans — we built an AI that
  replaces entire business functions, end to end."*

### What they actually offer

- **~50+ ready-to-deploy worker profiles** (the SPA headline says 15 flagship,
  the marketplace claims 50+) across marketing, dev, design, HR, finance, ops,
  legal, procurement, data governance, security/SOC, CSR, exec assistant,
  receptionist, SDR, IT support, etc. Each ships with a name, photo, phone
  number, email, and a written "personality."
- **A persistent professional identity per worker.** Own email + phone number,
  joins the company directory "like any new hire," and contacts external
  parties (calls, follow-ups) *from its own identity* — explicitly so
  "candidates can't tell the difference."
- **Goal-driven autonomy.** "Not script-followers — you give a goal, they
  figure out the how." Multi-worker teams collaborate ("assemble a custom AI
  workforce: marketing + dev + design + support").
- **Channels:** Slack, Microsoft Teams, Gmail, email, phone. "Talk to your
  Workers on Slack/Teams/email/phone; they contact your customers directly."
- **Integrations:** "3000+ tools," 5-minute no-code install (this is almost
  certainly a Zapier/Make-style connector layer, not 3000 native integrations).
- **Stated tech:** "latest-gen LLMs, RAG architecture, autonomous agents with
  persistent memory."
- **A human-freelancer side.** Notably hybrid: they recruit human freelancers
  via "a technical interview with an expert" and claim *"our freelancers earn
  on average 23% more."* So part of the model is a vetted human-talent
  marketplace wrapped in the same brand — the "AI worker" line is partly
  human-in-the-loop today.

### Security / compliance posture (their claims)

- GDPR compliant, **ISO 27001 certified**, DPA available.
- TLS 1.3 in transit, AES-256 at rest; **EU-only data hosting**, no third-country
  transfer without consent.
- **Zero data-training** pledge ("your data never trains our models").
- RBAC + full audit log of worker actions. MFA for all; **SSO/SAML 2.0 on
  enterprise**. Daily backups, 4-hour RTO, 24/7 SOC monitoring.

### Pricing (from the bundle)

- **Starter — Free:** up to 2 workers, all profiles, Slack+email, dashboard.
- **New Hire — $500/mo:** 200k credits, ≤1 active worker.
- **Worker Pack — $2,500/mo:** 1M credits, ≤3 active workers, unlimited
  prototypes. (Marked the highlighted/recommended tier.)
- **Enterprise Pack — custom:** setup > €4k, 1-year commitment, dedicated
  onboarding, custom integrations + SLA.
- Credits-based, USD, monthly; 20% annual discount; free trial, no card.

## Verdict: are we better?

**Yes — on substance and defensibility. They beat us on packaging and
go-to-market polish.** Maverick is a deeper, self-hostable, governance-first
*platform*; Workers Delos is a slicker, hosted, role-marketplace *product* with
a sharper consumer-grade story and a lower-friction funnel. We win the
enterprise/regulated buyer who must own and audit the runtime; they win the SMB
buyer who wants a virtual hire by Friday with zero ops.

Per the kernel rule, this is the right competitive frame: compete on
**governance + provable learning + self-host**, not on the agent runtime or on
"cheaper than a human" copy.

## Head-to-head

| Dimension | Maverick | Workers Delos (aiworkers.so) |
|---|---|---|
| Form factor | Self-hostable platform + CLI + dashboard + MCP | Hosted SaaS only |
| Prebuilt specialists | **1,118 packs across 26 suites** (lint-audited) | ~50 worker profiles |
| Governed learning | **Yes** — dreaming/hindsight/proof, snapshot + **rollback**, **signed** learning audit | "Persistent memory" claim; no governed/auditable learning story |
| Audit | **WORM, signed, sealed, federated, retention/erase** (`audit/`) | "Full audit log" (unspecified) |
| Governance plane | **Yes** — `governance.py`, `access_policy.py`, RBAC, SCIM, DPIA, AI-Act pack, compliance regimes | RBAC + audit log only |
| Compliance certs | SOC2 readiness tooling, DPIA, AI-Act; **ISO 27001 not yet claimed** | **GDPR + ISO 27001 certified**, DPA, EU hosting |
| Multi-tenant | **Yes** — tenancy, KMS, egress, billing | Vendor-hosted single posture |
| Channels | **14+** incl. voice, streaming voice, SMS, email, Slack, Teams, WhatsApp, Signal, Telegram, RCS, iMessage | Slack, Teams, email, phone |
| Per-worker identity (email/phone/persona) | Capability exists (email/voice channels) but **not packaged** as a named identity in a directory | **Yes — signature feature**, first-class |
| Outbound phone/voice to customers | Voice + streaming-voice channels present | **Yes**, marketed front-and-center |
| Model choice | **User-owned, 12 providers**, never hard-coded | Vendor-chosen ("latest-gen LLMs") |
| Safety chokepoint | **Shield** on input/tool/output, ensemble, rate-limit | Not a stated concept |
| Budget governance | **Hard caps** (tokens/$/wall/tools) enforced at record time | Credits metering (billing, not safety) |
| Setup friction | Higher (self-host / install) | **5-min no-code, free 2-worker tier** |
| Pricing legibility | Enterprise/seat oriented | **Clear, public, self-serve $0→$2.5k** |
| GTM polish | Engineering-led | **Strong** — role-marketplace, personas, free funnel |

## Where Maverick wins (defensible moats)

1. **Provable, governed self-improvement.** dreaming → hindsight → proof, with
   snapshot + full rollback and a *signed* learning audit
   (`dreaming.py`, `hindsight.py`, `proof_pack.py`, `workspace_snapshot.py`,
   `test_learning_rollback_full_revert.py`). Their "persistent memory" is a
   black box; ours is reversible and attestable. **This is the #1 wedge.**
2. **Audit you can hand to a regulator.** WORM + signing + sealing + federation
   + retention/erase. "Full audit log" doesn't survive a real compliance review;
   our `audit/` stack is built for one.
3. **Self-host + bring-your-own-model.** Regulated buyers (finance, health,
   gov, defense) cannot send data to a Paris SaaS. We run in their VPC, on
   their model keys, across 12 providers. Workers Delos has no self-host path.
4. **Breadth on a governed core.** 1,118 specialists vs ~50; 289 tool modules;
   14+ channels; shield on every I/O boundary; per-principal budget caps.
5. **Multi-tenant control plane.** Tenancy, KMS, egress policy, billing — we can
   *be* the platform a Workers-Delos-like product is built on.

## Where they win — and what we need to close it

These are the actionable gaps. None require abandoning the kernel strategy; most
are **packaging and GTM**, plus two real product items and one compliance item.

### P0 — Packaging / GTM (highest leverage, lowest engineering cost)

1. **Ship a "Hire a worker" persona layer over the 1,118 packs.** Their entire
   advantage is that a buyer sees *"Victoria, SDR, her own email & phone"*
   instead of *"specialist pack envelope."* We have more and better specialists
   — we present them as infrastructure. Add: name, avatar, one-line persona,
   role bio, and a one-click "deploy" on top of existing packs in the dashboard.
2. **First-class per-worker identity.** Bind a named worker to its own email
   address + phone number + Slack/Teams presence and register it in a worker
   directory. The channels already exist (`email_v2.py`, `voice.py`,
   `streaming_voice.py`, `sms.py`, `slack.py`); what's missing is the *identity
   object* that owns them and shows up as "an employee." Make it governed
   (every outbound action still passes the shield + audit).
3. **Free, self-serve, no-card entry tier.** A "2 workers free, 5-minute setup"
   on-ramp — ideally a hosted lite/trial edition — to compete with their funnel.
   Today our friction (self-host install) loses the SMB evaluator before they
   see the depth.
4. **Public, legible pricing.** A clear $0 → team → enterprise ladder. Enterprise
   "contact us" is fine at the top, but the bottom of the funnel needs a number.

### P1 — Product

5. **No-code connector breadth.** Match the "3000+ tools" perception with a
   Zapier/Make/native-connector story surfaced in the UI. We have 289 tool
   modules + `enterprise_connectors.py` + `oauth_helper.py` — but the *count and
   discoverability* are the marketing gap. Consider a connector marketplace page.
6. **Outbound voice/phone, productized.** They lead with "workers that call your
   customers." We have voice + streaming voice as channels; package an outbound
   calling capability (with shield gating + recording/consent + audit) as a
   headline feature, not a buried channel.
7. **"Assemble a team" UX.** Their multi-worker bundling ("marketing + dev +
   design + support") is exactly our fleet/orchestrator strength
   (`fleet.py`, `fleet_memory.py`). Surface it as a guided team-builder.

### P2 — Compliance / trust signals

8. **Get ISO 27001 certified (and say so).** They claim it; we have SOC2-readiness
   tooling and DPIA but no headline cert. For EU/enterprise deals this is a
   checkbox we currently lose. Pursue ISO 27001 + SOC2 Type II and publish a
   trust center.
9. **EU data-residency option.** Their "EU-only hosting, no third-country
   transfer" resonates with European buyers. Our multi-tenant + KMS substrate
   can offer region pinning — document and market it.
10. **A "zero data-training" pledge, stated plainly.** We likely already don't
    train on customer data (user-owned models), but they say it on the homepage
    and we don't. Make the promise explicit and contractual (DPA).

## Recommendation

Hold the line on the kernel strategy — **governance + provable learning +
self-host is the moat, and it is real and shipped.** But we are losing the first
impression. Fund a **persona/identity packaging sprint (P0 #1–4)** to translate
our depth into the "hire a coworker" language buyers now expect, add the **two
product items (outbound voice, connector marketplace)**, and start the **ISO
27001 / trust-center track**. Do that and we are clearly better on every axis a
serious buyer cares about, while no longer ceding the demo and the funnel.

> Caveat worth flagging to GTM: part of Workers Delos is a **human-freelancer
> marketplace** ("our freelancers earn 23% more"). Their "AI worker" claims are
> partly human-in-the-loop today — a credible point of differentiation for our
> fully-autonomous, governed, auditable runtime.
