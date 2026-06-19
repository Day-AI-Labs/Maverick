# Commercialization Teardown — Synthesis

> Capstone over the ten adversarial teardowns in this directory (01–10), each
> produced by an independent agent told to red-team the pivot, not cheerlead.
> Date: 2026-06-06. This synthesis **corrects** the earlier
> [`regulated-deployment-and-compliance-platform.md`](../regulated-deployment-and-compliance-platform.md)
> where the teardown found it too optimistic. External, post-cutoff facts
> (Microsoft/Okta 2026 launches, market sizes) are flagged **[verify]**.

## Bottom line (the convergent verdict)

Ten agents working different angles landed on the **same** four-part conclusion:

1. **The generic wedge got commoditized while we were writing the strategy doc.**
   "Register + scope + audit my agents" is now shipped *for free or near-free* by
   the identity incumbents — **Microsoft Entra Agent ID** (GA), **Agent 365** (GA,
   ~$15/user/mo), an **open-sourced Agent Governance Toolkit** (MIT, covers all 10
   OWASP agentic risks), and **Okta for AI Agents** (GA ~30 Apr 2026) **[verify]**.
   The "agent governance is an unowned category" claim in the strategy doc is
   **already wrong at the identity layer** (teardowns 03, 06, 10).

2. **We are far less "compliant-ready" than the doc claimed.** The "~70% built"
   figure conflates *cryptographic primitives* with *enforced controls*. Held to a
   CISO's procurement checklist, real regulated readiness is **~15–20%** — and
   multi-tenancy is **~5%, and broken at the call site even when enabled**
   (`server.py:81-88` writes the world model *outside* the `tenant_scope` it wraps
   `run_goal` in). That is a latent **cross-tenant data-leak** the moment anyone
   hosts two customers (teardown 04, 09).

3. **A narrower wedge survives — and only one.** The **self-hostable, provable,
   regulated agent runtime**: running agents on PHI/PCI/EU/classified data with
   tamper-evident, framework-mapped, *human-attested*, exportable evidence,
   air-gapped, no hyperscaler cloud required. It is the one square Microsoft
   (cloud-bound), Okta (identity-only), OneTrust (manual filing cabinet), and Vanta
   (infosec-only) each *structurally* cannot occupy (teardowns 03, 05, 06, 08).

4. **The right next move is a cheap falsification test, not a build or a
   relicense.** Before any cert spend, content deal, re-architecture, or LICENSE
   change: get **≥5 paid design-partner LOIs (~$30–40K each) from regulated buyers
   in 8 weeks**. Under 5 ⇒ the budget isn't here in 2026 ⇒ **do not pivot the
   company**; ship the runtime hardening as OSS and wait (teardown 10).

**Net:** the pivot is *plausible but small and contested* — a realistic **$10–15M
ARR self-host niche by year 4–5**, ~15–20% odds of reaching $10M, <5% venture-scale
(teardown 10). That can be a good founder outcome. It is not the OneTrust-killer the
framing implied, and betting the company on it before the LOI test would be a $3M
guess against Microsoft.

## Two honest corrections to my own strategy doc

The teardown is most useful where it contradicts the document it was grounded in:

- **"~70% built on be-compliant" → ~15–20% *enforced*.** Real and differentiated:
  the Ed25519 hash-chained audit + anti-deletion anchors (`audit/signing.py`), GDPR
  erase-with-re-anchor (`audit/erase.py`), attenuating capabilities (`capability.py`).
  Absent or default-off no-ops: SSO/OIDC/SAML/SCIM (zero code outside CI publishing),
  encryption-at-rest/KMS (`world.db` + audit are plaintext, Unix `0600` only),
  resource-level RBAC, SIEM export, residency, FIPS, secrets *vault* (`secrets.py` is a
  log-*scrubber*, not a vault), and a single shared dashboard bearer token with no users
  (teardown 04). **Floor to enter a regulated POC: ~30–40 person-weeks** of net-new
  engineering — none of it actually scheduled on the 36-month roadmap.

- **"Agent governance is unowned" → owned at the identity layer, open at the
  *regulated-runtime + attested-evidence* layer.** Concede identity (consume
  Entra/Okta as upstream principals; don't build an IdP against them). Concede the
  free runtime-governance toolkit. Win on the part the platform vendors can't ship:
  provable, self-hosted, air-gapped, framework-mapped evidence with a **human in the
  signed loop** (teardowns 03, 08).

I'd rather flag these now than have a buyer's security review find them. I've added a
correction banner to the original doc pointing here.

## The ten teardowns in one picture

| # | Front | The killer finding | The move it forces |
|---|---|---|---|
| [01](./01-licensing-and-relicensing.md) | Licensing | MIT is irrevocable for shipped code; fully-closed kills the self-host moat | **Open-core + source-available (FSL; BSL fallback; reject SSPL).** File the trademark *before* announcing — it's the real lever and is currently unguarded |
| [02](./02-packaging-pricing-editions.md) | Pricing | Per-agent / per-audit-event metering is the category's self-inflicted trap | Give away enforcement runtime; **charge for the control plane + federation + content + labor.** Community / Team $15–24K / Enterprise $120–500K+ |
| [03](./03-competitive-teardown.md) | Competition | Microsoft + Okta commoditized the generic wedge in 2026; window closing | Don't fight on identity or free runtime gov; lead with **provable + self-hostable + regulated** |
| [04](./04-regulated-deployment-eng-gaps.md) | Eng readiness | "70%" is really ~15–20%; tenancy ~5% and **broken at the call site** | ~30–40 pw "Governed Runtime" track *before* a regulated POC; never host multi-tenant until `tenant_id` is enforced |
| [05](./05-agent-governance-product-mvp.md) | Product MVP | ~60% is a projection of data we already emit; TAM hinges on governing *third-party* agents | 90-day MVP: registry + evidence projector + read-only third-party ingest (OTel + MCP introspection); defer third-party *enforcement* |
| [06](./06-gtm-icp-and-sales-motion.md) | GTM | Buyer is the **CISO**; PLG can *kill* a GRC startup; current "consumer / no paid tier" positioning is harmful | Design-partner-led sales; OSS as lead-gen funnel only; neutralize the trust paradox by inversion ("we govern our own swarm") |
| [07](./07-trust-certifications-roadmap.md) | Trust/certs | To sell compliance you must *be* compliant; Type II clock can't be bought fast | Start SOC 2 Type II **now**; trust portal + pen test + DPA + BAA = ~$70–130K yr-1; self-host shrinks the burden; FedRAMP is a seed-stage trap |
| [08](./08-regulatory-content-moat.md) | Content moat | "Agents author the control library" is a liability bomb; SCF's license *bans* AI-derived content | License the spine (**OSCAL free + UCF OEM**); ship AI *drafts + immutable human sign-off* — our consent/HITL ledger is the unique asset |
| [09](./09-saas-architecture-readiness.md) | Architecture | No tenant boundary in the data plane; every governance default is **fail-open** | 6–9 mo re-platform: Postgres+RLS, control/data-plane split, per-tenant KMS; **flip 10 defaults to fail-closed** |
| [10](./10-financial-model-and-fundraising.md) | Financials | Live TAM ~$4.6B (not $50B GRC); budget may be 12–30 mo out | Raise a **$2.5–3.5M seed to buy one falsification cycle**; run the LOI test before cert/content spend |

## The sequence the agents collectively imply

**Gate 0 — Falsify the thesis cheaply (≈8 weeks, ≈$0 capital). Do this first.**
Take the *existing* signed-audit + capability + framework-tag projection to 15–20
regulated buyers (digital health, fintech, EU-data) and ask for a paid design-partner
LOI at ~$30–40K. **< 5 LOIs ⇒ stop; don't pivot the company.** This converts a $3M bet
into one decisive signal (teardown 10).

**Track A — No-regret moves (run in parallel; valuable whatever Gate 0 says).**
Stand up the commercial entity; **start the SOC 2 Type II clock** (it's calendar-bound,
so every week of delay is a week deal #1 slips); publish a trust portal + DPA; **file
the "Lightwork" trademark** and fix the `CONTRIBUTING.md` inbound=outbound-MIT trap +
the "no paid tier / no telemetry" positioning; lock the **OSCAL + UCF** content spine;
make **human attestation a hard product invariant** (it's both the content-liability
fix and the differentiator). None of these require the relicense or the re-architecture.

**Track B — Build (only if Gate 0 validates).** The ~30–40 pw **Governed Runtime**
track (SSO/OIDC, encryption-at-rest, *enforced* tenant isolation, SIEM export, resource
RBAC, per-tenant quotas) and the 6–9 month SaaS re-platform (Postgres+RLS, control/data
split, per-tenant KMS). Sequenced behind paying design partners, not ahead of them.

**The one architectural decision that gates the whole pivot.** CLAUDE.md rule 1 — *the
kernel is fail-open and never requires the shield* — directly collides with *a
compliance product must fail **closed** and prove it stayed closed*. There is no
"hard enforcement mode" / policy-decision-point today (teardowns 04, 09). Reconciling
these (a non-disableable enforcement profile for the Enterprise SKU, layered over the
fail-open OSS kernel) is a first-class design task, not a flag. Underestimating it is
how the pivot slips a year.

## The convergent kill-risks

1. **Microsoft / Okta commoditize the wedge** (03, 10) — the most-cited risk. Mitigation:
   don't compete on identity; occupy the self-host/air-gap/regulated square they can't.
2. **A multi-tenant data-leak before isolation is enforced** (04, 09) — today's code
   co-mingles world model + audit across tenants; for a HIPAA/PCI customer that's a
   reportable, possibly company-ending breach. **Do not host multi-tenant until
   `tenant_id` is enforced and tested.**
3. **Category timing** (10) — Credo/Holistic stalling at ~$100M valuations with tiny ARR
   says the AI-governance budget is 12–30 months out; a $3M seed can starve first.
4. **Selling "70% compliant" into a security review and getting caught** (04) — a
   credibility death. Lead with the genuinely-strong audit/capability story; be explicit
   that identity + at-rest + tenancy are in flight.
5. **The content-liability bomb** (08) — AI-authored control mappings no auditor will
   sign. Human-in-the-signed-loop is non-negotiable.
6. **Founder/brand + capital intensity** (10) — solo, non-domain founder + AI-written
   codebase selling *trust* software; certs + sales are $1M+/yr fixed cost before ARR.

## Recommendation

Reframe the directive. **"Kill the open source" is the wrong frame** — going fully
closed forfeits the self-host auditability that *is* the surviving wedge, and the agents
are unanimous that the answer is **open-core + source-available**, not proprietary. So:

- **Don't relicense, re-architect, or fundraise yet.** Run **Gate 0** first. It's free
  and it's the highest-information thing you can do this quarter.
- **Do** the Track-A no-regret moves now (entity, SOC 2 clock, trademark, positioning,
  content spine, attestation invariant) — they pay off under every outcome.
- **If ≥5 LOIs land:** execute open-core (FSL control plane, permissive kernel), build
  the Governed Runtime track behind those design partners, and make the fail-closed
  enforcement-mode decision explicit on day one.
- **If they don't:** you've spent ~8 weeks and $0 to avoid a $3M mistake. Ship the
  runtime hardening as OSS, keep the brand, and wait for the budget to arrive.

The ten detailed reports (01–10) carry the evidence, file-cited and source-cited.
</content>
