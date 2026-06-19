# Commercialization Execution Plan — 90 Days

> Operationalizes the teardown ([`00-synthesis.md`](./00-synthesis.md) + 01–10) into a
> runnable program. Three lanes, hard gates, owners, costs. Companion artifacts:
> the design-partner kit ([`12`](./12-gate0-design-partner-kit.md)), the Governed-Runtime
> build spec ([`13`](./13-governed-runtime-build-spec.md)), and the licensing/positioning
> execution checklist ([`14`](./14-licensing-and-positioning-execution.md)). Date: 2026-06-06.

## The one rule

**No irreversible spend or outward-facing move before Gate 0.** Do not relicense, file
the trademark publicly, re-architect for SaaS, sign a content OEM, or buy certs *ahead*
of **≥5 paid design-partner LOIs**. The teardown's strongest, cheapest finding: an 8-week,
~$0 test gates a ~$3M bet against Microsoft (teardown 10). Everything below is sequenced
around that gate.

## Lane 1 — Gate 0: falsify the thesis (weeks 1–8)

Sell the *existing* product (signed-audit + capability + framework-tag projection) to
regulated buyers and ask for money. Full playbook in [`12`](./12-gate0-design-partner-kit.md).

| Wk | Action | Output |
|---|---|---|
| 1 | Build the target list (40–60 accounts: digital-health, fintech, EU-data; self-host-mandated; *not* Microsoft-agent shops) + the one-meeting demo off the current CLI/audit | List + demo script |
| 2–3 | Founder-led outbound on the **EU AI Act Aug-2-2026** forcing function; book 15–20 discovery calls | 15–20 meetings |
| 4–6 | Run the demo; convert interest to **paid design-partner LOIs (~$30–40K)** | LOIs in flight |
| 7–8 | Close. Count signed/verbal-committed LOIs | **Gate 0 decision** |

**Gate 0 (end of week 8):**
- **≥5 paid LOIs ⇒ GO.** Trigger Lane 3 build + the relicense/raise in [`14`](./14-licensing-and-positioning-execution.md).
- **<5 ⇒ STOP the pivot.** Ship the runtime hardening as OSS, keep the brand and the
  community, and re-test when the budget signal is stronger. You spent ~8 weeks and ~$0
  to avoid a company-scale mistake.

## Lane 2 — No-regret moves (weeks 1–12, parallel; valuable under *either* Gate 0 outcome)

These pay off whether or not you pivot, so they don't wait on the gate:

1. **Stand up the commercial entity** (C-corp) — needed to sign LOIs and certs anyway.
2. **Start the SOC 2 Type II clock now.** It's calendar-bound (3–12 mo observation window);
   every idle week is a week deal #1 slips (teardown 07). ~$35–60K boutique [verify].
3. **Trust surface:** a public trust page, a DPA + SCC + sub-processor draft, and a
   pre-filled SIG-Lite/CAIQ. Lead the sale with self-host to shrink the questionnaire (07).
4. **Trademark clearance** on "Lightwork" (the real enforcement lever; currently unguarded) —
   *clearance now, public filing gated to Gate 0* (teardown 01, [`14`](./14-licensing-and-positioning-execution.md)).
5. **Fix the cross-tenant leak as a security patch** — `server.py:81-88` writes the world
   model/audit outside `tenant_scope`. This is a correctness/safety fix independent of the
   full tenancy track; do it now, do **not** offer hosted multi-tenant until the full
   `tenant_id` work in [`13`](./13-governed-runtime-build-spec.md) lands (teardown 04, 09).
6. **Content spine:** open conversations with **UCF** (OEM) and stand up **OSCAL** ingest;
   make **human attestation a hard product invariant** — it's the content-liability fix
   *and* the differentiator (teardown 08).

## Lane 3 — Build the Governed Runtime (spec weeks 6–12; build only if Gate 0 = GO)

The ~30–40 person-week track that turns ~15–20% readiness into a closeable regulated POC.
Full spec, file-pointed, in [`13`](./13-governed-runtime-build-spec.md):

- SSO/OIDC (+ SCIM) → federated principal onto `Capability.principal`.
- Encryption-at-rest / KMS / per-tenant DEK for `world.db` + audit.
- **Enforced** tenant isolation: `tenant_id` columns (SQLite + Postgres) + call-site fix.
- Immutable audit: WORM/Object-Lock + SIEM (Splunk/Sentinel) export of the signed NDJSON.
- Resource-level RBAC + approver identity + N-of-M on the approvals table.
- Per-tenant quotas (extend `Budget` to a persisted per-principal aggregate).
- **The fail-closed enforcement mode** that reconciles CLAUDE.md rule 1 (fail-open OSS
  kernel) with a compliance product that must fail closed *and prove it* — a
  non-disableable Enterprise enforcement profile layered over the OSS kernel.

The 6–9-month SaaS re-platform (Postgres+RLS, control/data-plane split, per-tenant KMS;
teardown 09) is **gated behind paying design partners** — do not start it speculatively.

## Money & people (teardown 10)

- **Raise:** $1.5M pre-seed now → $2.5–3.5M seed on Gate 0 = GO. Buy *one falsification
  cycle*, not three years of runway into a maybe-market.
- **Use of funds (~$3M / 24 mo):** ~60% the first 5 hires, ~15% certs/legal, ~10% content,
  ~15% GTM + buffer.
- **First 5 hires:** (1) founding enterprise AE; (2) ex-OneTrust/Vanta compliance & content
  lead (also offsets the AI-written-codebase trust gap); (3) platform engineer (Lane 3);
  (4) forward-deployed/solutions engineer; (5) content/DevRel marketer.

## Owners (solo-founder reality)

| Lane | Founder | First hire that takes it over |
|---|---|---|
| Gate 0 / GTM | **Founder leads every call** | Enterprise AE |
| Certs / content / trust | Founder kicks off | Compliance & content lead |
| Build (Lane 3) | Founder specs + reviews | Platform engineer |

## Kill criteria (when to stop, honestly)

- **<5 LOIs at week 8** ⇒ don't pivot (primary gate).
- **A multi-tenant data-leak incident** before `tenant_id` is enforced ⇒ pull hosted
  multi-tenant immediately; it's a reportable HIPAA/PCI breach (teardown 04).
- **Microsoft/Okta bundle the wedge free and LOIs evaporate mid-cycle** ⇒ retreat to the
  self-host/air-gap regulated niche or stop (teardown 03, 10).

## What this plan deliberately does *not* do

Clone OneTrust's breadth (cookie CMP, ethics hotline, 55-framework corpus), build an IdP
against Okta/Entra, chase FedRAMP at seed stage, or go fully closed-source — each is a
losing fight per the teardown. Lead with the one defensible square: the **self-hostable,
provable, regulated agent runtime with human-attested evidence.**
</content>
