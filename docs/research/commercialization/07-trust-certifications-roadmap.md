# Trust & Certifications Roadmap — The Meta-Compliance Problem

> Teardown #7 for the commercial pivot. Date: 2026-06-06. Follow-on to
> [`regulated-deployment-and-compliance-platform.md`](../regulated-deployment-and-compliance-platform.md).
> The thesis under the knife: *to sell compliance you must **be** compliant,
> visibly, before any bank/hospital signs.* Dollar figures are market-sourced and
> flagged **[verify]** — re-price against actual auditor/vendor quotes before
> committing budget.

## Bottom line

The meta-compliance trap is real and it is the single biggest non-engineering
gate on the pivot: a seed-stage startup with zero certs **cannot** clear a
bank's or hospital's vendor-security review, no matter how good the product is.
But the trap has a documented escape, and Lightwork is unusually well-positioned
to take it. **Three moves de-risk deal #1 without waiting 12+ months for a
Type II report: (1) lead with self-host so customer data never leaves their
boundary — this deletes whole sections of the security questionnaire; (2) stand
up a public Trust Center + a fresh third-party pen test + a completed SIG-Lite
self-assessment in ~6–8 weeks to survive procurement triage; (3) start the
SOC 2 Type II observation clock NOW so the report exists before the pipeline
matures.** The cruel irony — and the wedge — is that the product's entire
premise is automating the very vendor-security questionnaires we'll be drowning
in. We are customer zero. Document that journey; it is the demo.

What actually blocks deal #1 is **not** a single cert — it's the *absence of a
trust surface*. A startup that publishes a Trust Center, a recent pen-test
attestation letter, a SOC 2 Type II **in progress** (with auditor named and
window started), and a signable DPA can get **conditionally** approved by most
mid-market security teams and many enterprise ones under a risk exception. A
startup with a blank security page gets filtered out before a human reads the
pitch.

## Sequenced cost / timeline table

Ordered by when you need it. "Blocks deal #1?" is the load-bearing column.

| # | Artifact | Realistic cost (yr 1) **[verify]** | Time to "have it" | Blocks deal #1? |
|---|---|---|---|---|
| 1 | **Trust Center / public security page** (SafeBase/Vanta) | $8k–$20k/yr platform, or $0 hand-rolled | 1–3 wks | **Soft-blocks** — no page = filtered in triage |
| 2 | **Third-party penetration test** (annual) | $10k–$25k (startup scope) | 2–4 wks + remediation | **Yes** — enterprise expects a current report |
| 3 | **GDPR DPA + SCCs + sub-processor list** (legal) | $5k–$15k counsel; SCCs are free EU templates | 2–4 wks | **Yes for any EU data** — must sign customer's or yours |
| 4 | **Vendor-questionnaire kit** (SIG-Lite / CAIQ self-assessment) | staff time; bundled in Trust Center | 2–4 wks | **Yes** — you *will* be sent one |
| 5 | **HIPAA compliance + signable BAA** (no cert exists) | $10k–$30k (policies, training, counsel-drafted BAA) | 4–8 wks | **Yes for any hospital/PHI deal** — hard gate |
| 6 | **SOC 2 Type I** (point-in-time) | $15k–$40k all-in (audit + GRC tool + pen test) | 4–8 wks readiness, then audit | Bridges the gap until Type II |
| 7 | **SOC 2 Type II** (the one buyers want) | $35k–$60k boutique; $50k–$150k+ broader | **6–18 mo** (3–6 mo min observation window) | **Yes, eventually** — start the clock NOW |
| 8 | **ISO 27001** (international / EU-favored) | $14k–$50k (Stage 1 + Stage 2 + impl.) | 6–10 mo | Lags; needed for EU/UK + as ISO 42001 base |
| 9 | **ISO 42001** (AI management system) | $50k–$150k SMB; **30–50% cheaper atop ISO 27001** | 4–6 mo if 27001 exists; else 6–12 mo | Differentiator, not yet a hard gate — **leverage as a "we govern AI" claim** |
| 10 | **FedRAMP ATO** (US gov only) | **$350k–$500k Low; $800k–$2M Moderate** | 12–24 mo (20x may cut to <3 mo for prepared CSPs) | **Only if chasing US gov — do NOT until a sponsored deal funds it** |

**Realistic minimum spend to be credible in commercial (non-gov) enterprise,
year 1: ~$70k–$130k** (Trust Center + pen test + DPA + HIPAA/BAA + SOC 2
Type I→II in flight), plus the SOC 2 Type II completing in months 9–15. ISO
27001/42001 stack onto year 2. FedRAMP is a separate, sponsor-funded program —
not seed-stage table stakes.

### The observation-window problem (why this gates everything)

SOC 2 Type II is the cert enterprise buyers actually demand, and it is the one
you **cannot buy your way through quickly**: it attests that controls *operated
effectively over a 3–12 month window*. There is no shortcut — the clock is the
clock. Worse, exceptions are permanent: if a control fails in month 2 of a
6-month window, that exception is in the final report. Two consequences: (a)
**start the window immediately** (even pre-revenue) so the report exists when
deals land; (b) **discipline must hold for the entire window** — a sloppy month
poisons the artifact. Type I (point-in-time) is the bridge: it proves controls
are *designed* correctly and ships in weeks, letting you tell a buyer "Type I
today, Type II window underway, report by [month]."

### What is easier *because* Lightwork self-hosts

Self-host is a genuine compliance moat, not just marketing — several artifacts
shrink or partially disappear when customer data stays inside the customer's
boundary:

- **HIPAA/PHI:** if PHI never reaches our infrastructure, our BAA surface and
  breach-exposure shrink dramatically — the customer's own controls cover the
  data plane. Self-host is the strongest possible answer to "where does PHI
  live?"
- **GDPR residency / SCCs / TIA:** no cross-border transfer of customer data
  means the Schrems-II Transfer Impact Assessment burden and SCC complexity
  collapse for the data plane. Data residency is solved by topology, not paperwork.
- **Sub-processor list:** a self-hosted deployment has a *short* sub-processor
  list (our LLM provider(s), maybe telemetry) vs. a SaaS that processes all
  customer data — fewer entries to disclose, fewer to get authorized.
- **Vendor questionnaire:** dozens of "how do you encrypt/segregate/back up
  customer data at rest" questions become "customer-controlled — data does not
  reside on vendor infrastructure," which is the cleanest answer a reviewer can get.

This is the fastest credible path: **lead the sale with self-host**, scope the
SOC 2 to the control plane / update channel, and let the customer's existing
HIPAA/GDPR posture cover the data plane.

## What would kill us

- **Selling ahead of the trust surface and getting blacklisted.** Failing a
  bank's security review doesn't just lose the deal — procurement remembers.
  Pitching a regulated buyer with a blank security page burns the logo.
- **Claiming compliance we don't have.** "SOC 2 compliant" before the report
  exists, or "HIPAA certified" (no such thing) — these are misrepresentations
  that legal/security teams catch instantly and that can void deals or invite
  liability. Say "Type II window in progress," never "compliant."
- **The Type II window started too late.** If we wait for a signed deal to start
  the clock, the report is 6–18 months out and the deal dies in the gap. Not
  starting now is the default failure mode.
- **Being our own worst questionnaire reference.** We sell questionnaire
  automation; if our *own* security questionnaire responses are slow, thin, or
  inconsistent, every prospect's security team notices. Dogfooding failure is an
  existential credibility hit for *this specific product*.
- **FedRAMP gravity.** Chasing a gov logo and sinking $800k–$2M + 18–24 months
  before commercial revenue exists would starve the company. It is a trap for a
  seed-stage team unless a sponsored, funded deal pulls it.
- **Cert sprawl.** Pursuing SOC 2 + ISO 27001 + ISO 42001 + HIPAA + FedRAMP
  simultaneously burns cash and focus. Sequence them; don't parallelize them all.

## Recommendations

1. **Week 0–8 (the "don't-get-eliminated" minimum trust surface):** publish a
   Trust Center (start hand-rolled if cash-tight; the page matters more than the
   vendor); commission a third-party pen test and post the attestation letter;
   have counsel produce a signable DPA (with EU SCCs annexed) + a public
   sub-processor list; pre-fill a SIG-Lite / CAIQ self-assessment. This is the
   floor to survive procurement triage.
2. **Start the SOC 2 Type II observation clock NOW**, in parallel, via a GRC
   automation platform (Vanta/Drata/Secureframe) — and ship **Type I** first as
   the point-in-time bridge. Scope tightly to control plane + self-host update
   channel.
3. **Lead every regulated sale with self-host.** Make "your data never leaves
   your boundary" the headline. It deletes the largest, slowest sections of the
   security review and is the credible answer to HIPAA residency / GDPR transfer
   objections while certs are pending.
4. **Stand up HIPAA policies + a counsel-drafted BAA before the first hospital
   conversation**, not after. There is no HIPAA "certificate" — the signable BAA
   plus a Security Rule control narrative *is* the artifact. Self-host keeps the
   BAA surface small.
5. **Sequence ISO: 27001 in year 2, then ISO 42001 stacked on top** (30–50%
   cheaper that way **[verify]**). ISO 42001 is the future-proof "we govern AI"
   differentiator increasingly asked of AI vendors — claim the *intent/roadmap*
   now, certify when 27001 is in place.
6. **Defer FedRAMP** until a sponsored, funded US-gov deal justifies the
   $350k–$2M+ and 12–24 months. Note FedRAMP 20x may compress timelines, but it
   is still a separate program, not seed-stage table stakes.
7. **Dogfood publicly and turn the meta-problem into the demo.** Use Lightwork to
   run our *own* questionnaire responses, evidence collection, and DPA/ROPA
   upkeep, and publish that as the reference customer story. The thing that
   threatens credibility (we must be compliant to sell compliance) becomes the
   proof point (here is the product doing exactly that, on us).

## Sources

- SOC 2 cost/timeline/observation window:
  <https://www.humanr.ai/intelligence/soc-2-type-2-cost-benchmarks-timeline-120k>,
  <https://www.brightdefense.com/resources/soc-2-certification-cost/>,
  <https://www.dsalta.com/resources/soc-2/soc-2-type-1-vs-type-2-timeline-cost-guide>,
  <https://www.complyjet.com/blog/soc-2-compliance-cost>
- ISO 27001 cost/timeline/stages:
  <https://elevateconsult.com/insights/iso-27001-audit-blueprint-costs-timelines-2026/>,
  <https://sprinto.com/blog/iso-27001-certification-cost/>,
  <https://www.complyjet.com/blog/iso-27001-certification-timeline>
- ISO 42001 cost/timeline + ISO 27001 cost savings:
  <https://certbetter.com/blog/iso-42001-cost-what-ai-certification-actually-costs-in-2026>,
  <https://www.cycoresecure.com/blogs/iso-42001-certification-cost-timeline-requirements-faq>,
  <https://elevateconsult.com/insights/iso-42001-certification-timeline-budget-for-founders/>
- HIPAA BAA (no certification; contractual safeguards):
  <https://www.hipaajournal.com/hipaa-business-associate-agreement/>,
  <https://www.hhs.gov/hipaa/for-professionals/covered-entities/sample-business-associate-agreement-provisions/index.html>
- GDPR DPA / SCCs / sub-processor list / TIA:
  <https://gdpr-info.eu/art-28-gdpr/>,
  <https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/new-standard-contractual-clauses-questions-and-answers-overview_en>,
  <https://nocodelisted.com/blog/sub-processor-list-gdpr-template>
- Trust Center / vendor questionnaires (SIG/CAIQ) / SafeBase-Drata:
  <https://www.vanta.com/resources/best-trust-center-software>,
  <https://safebase.io/>,
  <https://soc2auditors.org/insights/drata-pricing/>
- Penetration testing cost for SOC 2:
  <https://www.getastra.com/blog/security-audit/soc-2-penetration-testing/>,
  <https://www.startupdefense.io/soc-2-costs-for-startups-complete-breakdown-and-budget-guide>
- FedRAMP cost/timeline + 20x:
  <https://elevateconsult.com/insights/fedramp-ato-in-2026-timeline-budget-sponsorship-guide/>,
  <https://www.convox.com/blog/fedramp-authorization-2026-guide-saas-companies>,
  <https://www.workstreet.com/blog/fedramp-20x-phase-3>
