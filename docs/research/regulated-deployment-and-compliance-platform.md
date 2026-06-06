# Maverick in Regulated Environments — and the OneTrust Replacement Question

> Strategy analysis. Date: 2026-06-06. Follow-on to
> [`agentic-os-and-enterprise-analysis.md`](./agentic-os-and-enterprise-analysis.md).
> Method: full code audit of Maverick's governance substrate (file-cited) + a
> web-sourced landscape pass on OneTrust, the AI-governance market, and the
> concrete deployment requirements of HIPAA / SOC 2 / GDPR / EU AI Act / SR 11-7 /
> FedRAMP. Load-bearing external figures are flagged **[verify]**.

## Bottom line (four verdicts)

1. **This is two questions sharing one substrate.** "Use Maverick in regulated
   environments safely" (make Maverick *deployable by* a bank/hospital/pharma —
   the agent is the thing **being governed**) and "replace OneTrust" (make
   Maverick a compliance *product* others buy to govern **their own** estate —
   the swarm is the **execution engine**) are different products for different
   buyers. But the governance machinery that answers the first **is** the core of
   the second. We built a compliance engine to police our own agents; pointed
   outward, that engine is the product. One investment, two payoffs.

2. **We are ~70% built on "be compliant," and the README undersells it.** The
   tree already holds tamper-evident signed audit, GDPR retention + erasure, a
   consent/HITL ledger, per-principal attenuating capabilities, tool-level RBAC,
   PII/secret redaction, EU AI Act Art. 50 disclosure, anonymous mode, and
   air-gapped self-host. The genuine *code* gaps are narrow — **identity
   federation (SSO/OIDC + SCIM), encryption-at-rest/KMS, finishing multi-tenancy +
   per-tenant quotas, SIEM export, and a two-person rule.** The rest (SOC 2 Type
   II, ISO 27001/42001, HIPAA BAA, FedRAMP, DPA/SCCs) is **process and legal, not
   engineering.** These items already exist on the 36-month roadmap but are
   **scattered across 2027–2028**; the move is to pull them into one named
   **Governed Runtime** track and ship it first.

3. **Do not clone OneTrust. Take the one square no incumbent owns: agent
   governance.** OneTrust is broad but is a *filing cabinet* — "configuration, not
   code," populated by humans and paid consultants. Vanta/Drata automate evidence
   but only for infosec certs. AI-governance pure-plays (Credo, Holistic) sell
   *model paperwork*. **Governing autonomous agents at runtime — registry +
   capability scoping + tamper-evident action audit as a compliance artifact — is
   a forming category (OWASP Agentic Top 10, CSA NHI, Okta/Microsoft circling it)
   that no GRC incumbent owns.** Maverick is *itself* an agent swarm, so it has a
   structural right to win it. From there, expand into **compliance-as-agentic-
   labor**: agents that *run* the DSAR, *populate* the ROPA from live discovery,
   *chase* the vendor questionnaire, *collect* SOC 2 evidence — attacking OneTrust
   exactly where it is weakest.

4. **"Replace OneTrust" is a company, not a feature — decide the business model
   before the build.** It contradicts the repo's stated positioning
   (`ROADMAP.md`: *open-source-only, no paid tiers, general consumer*). A OneTrust
   replacement needs a hosted control plane, certifications, a regulatory-content
   library, legal artifacts (DPA/BAA/SCCs), and an enterprise sales motion —
   engineering is ~30% of it. The engineering-led, defensible, near-term play is
   the **Governed Runtime + the agent-governance system of record**; the full
   OneTrust surface is a multi-year platform + GTM bet gated on a commercial-
   entity decision (see Part 6).

---

## Part 1 — The reframe: *be* compliant vs. *do* compliance

| | **Q1 — Deployable in regulated envs** | **Q2 — Replace OneTrust** |
|---|---|---|
| The agent is… | the thing **being governed** | the **execution engine** |
| Buyer | the customer's platform / security team | the customer's privacy / GRC / AI-risk team |
| We sell | a *governed runtime* they can run on PHI/PCI/EU data | a *compliance system of record + workforce* |
| Proof needed | SOC 2 / HIPAA / residency / immutable audit | regulatory content + framework mappings + workflows |
| Mostly… | engineering + certs | product surface + GTM + legal |

**The double-duty insight.** Every primitive Q1 needs — signed audit, consent,
retention, erasure, PII redaction, capabilities, AI-Act disclosure, RBAC — is
*also* a building block of Q2. The audit chain that proves *our* agents behaved
is, projected through a framework mapping, the *evidence* a OneTrust buyer wants.
The capability model that scopes *our* sub-agents is the *agent registry +
least-privilege* control a customer wants over *their* agents. Build Q1 well and
Q2's foundation is already poured.

---

## Part 2 — What Maverick already has (code-verified)

The first enterprise analysis already corrected the "we're behind on governance"
framing. A second, deeper audit against `main` makes the point starker: the
*regulated-deployment* control set is largely present.

| Regulated-env control | Status | Evidence (file) |
|---|---|---|
| Tamper-evident action audit | ✅ Ed25519 Merkle chain **+ cross-file anchor ledger** (detects whole-day-file deletion) + `verify_chain` | `audit/signing.py` |
| Append-only audit sink + rotation | ✅ NDJSON, chmod 600 | `audit/writer.py` |
| Versioned audit event schema | ✅ incl. `capability_denied`, `consent_*`, `secret_redacted`, `erase`, `halt` | `audit/events.py` |
| Data-retention enforcement | ✅ opt-in; audit files + world-model rows | `audit/retention.py` |
| GDPR Art. 17 erasure | ✅ scrub/delete by subject; **re-anchors the signed chain** | `audit/erase.py` |
| Consent / HITL approvals | ✅ ledger + dashboard approval queue, fully audited | `safety/consent.py` |
| RBAC (tool-level) | ✅ global / per-channel / per-user + `max_risk` ceiling | `safety/tool_acl.py` |
| Per-agent identity / least privilege | ✅ signed, **attenuating** capabilities (child ≤ parent), opt-in | `capability.py` |
| Risk classification | ✅ low/medium/high per tool | `safety/tool_risk.py` |
| PII + secret redaction | ✅ | `safety/pii_detector.py`, `safety/secret_detector.py` |
| EU AI Act Art. 50 disclosure | ✅ first-turn chatbot disclosure, configurable | `compliance.py` |
| Data-minimized / anonymous logs | ✅ hashes ids, scrubs PII/paths | `privacy.py` |
| Kill-switch | ✅ `~/.maverick/HALT` polled per tool call | `killswitch.py` |
| Content safety / injection defense | ✅ Shield at 3 chokepoints, fail-open | `packages/maverick-shield/` |
| Cost governance | ✅ hard caps (per-run) | `budget.py` |
| Tenant isolation | 🟡 in progress: data-path + memory done; world-model/audit next | `paths.py` |
| Air-gapped / on-prem | ✅ self-host default, `--network=none`, local models | `sandbox/` |
| Observability | ✅ OpenTelemetry + Prometheus (opt-in) | (shipped, Q2) |

**The discipline that makes this real (and reusable for a product):** every one
of these is **opt-in, config-gated, fail-open**, and surfaced in the installer
wizard (`apps/installer-cli/.../wizard.py` already has safety profile, capability
enforcement, per-user tenancy, and audit-retention steps). That is exactly the
posture a multi-tenant SaaS control plane needs: per-deployment policy, no
kernel forks.

---

## Part 3 — The "be compliant" gap (Q1: regulated deployment)

### Code gaps (narrow, mostly already on the roadmap — just scattered)

1. **Identity federation — SSO/OIDC + SAML + SCIM.** *The* gap. Today identity is
   channel-qualified strings (`tg:123`, `slack:U02`) feeding the ACL/capability/
   tenant layers. No `grep` hit for `oidc|saml|scim` anywhere in `packages/` or
   `apps/`. Regulated buyers require federated SSO + MFA + automated
   de-provisioning as table stakes across *every* regime. This is also the P0
   from the prior analysis — it closes the enterprise gap **and** unlocks
   regulated deployment in one build. New `identity/` module → maps a federated
   principal onto the existing `Capability.principal` and tenant id.

2. **Encryption at rest / KMS.** `world.db` and the audit NDJSON are plaintext on
   disk (the only `encrypt` usages in core are *signing*, *transport*, and
   *cookie* stores — not data-at-rest). Regulated buyers need envelope encryption
   with a per-tenant DEK, key via OS keychain or an external KMS. Reuse the
   existing `cryptography` dep; config `[encryption]`. (Roadmap already lists
   "encrypted audit at rest AES-GCM via OS keychain" — in **2027 H1**. Pull
   forward.)

3. **Finish multi-tenancy + add per-tenant quotas.** `paths.py` lands the
   data-path primitive and routes memory; the **world model and audit log still
   need to migrate onto `data_dir()`** (the commit's own "follow-on increments").
   Then extend `Budget` from per-run to **aggregate per-principal/tenant/time-
   window** caps with usage accounting — the quotas/chargeback gap the prior
   analysis flagged (`budget.py` is per-run today: `Budget.check()`).

4. **SIEM export + immutable retention.** The audit is already signed,
   append-only NDJSON — so this is a *shipper* (Splunk/Sentinel/S3-Object-Lock
   WORM) plus optional `chattr +a`, not new crypto. Config `[audit.export]`.
   (Roadmap: "SOC2-aligned audit export," 2027 H1.)

5. **Segregation of duties / two-person rule.** Extend `safety/consent.py` to
   require **N-of-M** approvals for irreversible/high-risk ops, reusing the
   existing approvals queue. (Roadmap: "two-person rule for irreversible ops,"
   2027 H1.)

6. **Policy-as-code with framework tags.** A thin layer that tags each ACL/
   capability/consent rule with the control it satisfies (e.g. *"this denial =
   EU AI Act Art. 14 human oversight"*; *"this audit field = SR 11-7 override
   record"*). This is the **bridge from Q1 to Q2**: it makes the existing audit
   export double as framework-mapped *evidence*.

### Non-code (necessary, not differentiating — process & legal)

SOC 2 Type II and ISO 27001/**42001** (AI management system — increasingly
demanded of AI vendors); a signable **HIPAA BAA**; **DPA satisfying GDPR
Art. 28(3)** + **SCCs** for EEA transfers + EU **data-residency** options;
**FedRAMP** ATO for US-gov (high barrier; run on an authorized CSP *and*
authorize the product). These are a clock to start and a budget to spend, not an
engineering problem — but several have **code prerequisites we now largely have**
(immutable audit, RBAC, erasure, residency-via-self-host).

### Per-regime mapping (what we have / what's missing)

| Regime | Already satisfied (code) | Missing |
|---|---|---|
| **HIPAA** | audit logging, RBAC, erasure, self-host keeps PHI in-boundary | BAA (legal), encryption-at-rest, SSO+MFA |
| **GDPR** | Art. 17 erasure, retention, consent ledger, PII redaction, Art. 50 disclosure | DPA/SCCs (legal), residency pinning |
| **EU AI Act** (high-risk, 2 Aug 2026) | **logging** (signed audit), **human oversight** (consent/HITL + kill-switch), transparency (Art. 50) | risk-classification helper, conformity-doc generator |
| **SR 11-7 / model risk** | per-run cost+outcome audit, override records (consent), versioned events | model-card/registry, drift/eval monitoring export |
| **SOC 2 / ISO 27001** | tamper-evident audit, access control, change records | the attestation itself; SIEM export; SSO |
| **FedRAMP** | air-gapped self-host, audit, least-privilege | ATO (process), FIPS crypto, continuous-monitoring tooling |

The recurring pattern: **the universal control across all of these — "every
action is attributable, scoped, logged immutably, reversible, and human-
overridable" — we already largely have.** That single property is the spine.

---

## Part 4 — The OneTrust question (Q2)

### What OneTrust is, and why it's vulnerable

OneTrust ("the AI-Ready Governance Platform") spans six areas: **Privacy
Automation** (DSAR, data mapping/ROPA, PIA/DPIA, discovery), **Consent &
Preferences** (the cookie CMP), **Data Use Governance**, **Tech Risk & Compliance
(GRC)** (policy/control/evidence/audit, 55+ frameworks), **Third-Party Management
(TPRM)**, and a newer **AI Governance** pillar. ~$400–500M ARR; last marked
~$4.5B (2023 down-round from a $5.3B peak); reportedly in PE-sale talks late 2025
**[verify — figures diverge]**.

**The structural weakness is consistent across every review:** "configuration,
not code"; weeks-to-months implementations needing dedicated teams + paid
consultants; **questionnaire-and-spreadsheet workflows that humans must
populate**; infosec evidence automation *weaker* than the continuous-compliance
vendors. **OneTrust sells the filing cabinet; humans and consultants do the
filing.**

### The market map — three incumbents, three different gaps

- **OneTrust** — broad, but a **manual workflow shell**. Weak where the work is
  labor.
- **Vanta / Drata / Secureframe** — **automate evidence**, but only for **infosec
  certs** (SOC 2/ISO/HIPAA). They proved enterprises will pay for *automated*
  evidence; none does privacy DSAR/ROPA, TPRM, or AI/agent governance.
- **AI-governance pure-plays** (Credo AI, Holistic AI, IBM watsonx.governance,
  Securiti, Collibra, ServiceNow) — govern **models** with inventories and
  assessments; largely **documentation tools**.
- **Agent governance** — governing *autonomous agents* (identity, capability,
  action audit) — is a **forming category with no GRC incumbent.** OWASP shipped
  the **Agentic Top 10 (Dec 2025)**; CSA is standardizing non-human-identity
  governance; Okta and Microsoft are circling from the *identity* side; Zenity /
  Prisma AIRS from the *security* side. **No one owns "the agent registry + agent
  action audit as a compliance artifact."**

### The wedge (three moves, in order of defensibility)

1. **Own agent governance as a compliance artifact.** Maverick is a recursive
   swarm with signed action audit + attenuating capabilities + a kill-switch —
   it can answer the Okta/Microsoft question (*"where are my agents, what can they
   do, what did they do, prove it"*) not as paperwork but as **live, enforced,
   tamper-evident runtime state**. This maps 1:1 onto EU AI Act logging/oversight,
   SR 11-7 monitoring/override, and SOC 2 audit-trail clauses. Category-defining,
   and mostly a **projection of data we already emit.**

2. **Compliance-as-agentic-labor.** Reframe each "human + questionnaire +
   spreadsheet" workflow as a Maverick **goal template + connectors**: run the
   DSAR end-to-end (locate→retrieve→redact→fulfil), populate/maintain the ROPA
   from live system discovery, chase & complete vendor questionnaires, collect
   SOC 2/ISO evidence continuously. This extends Vanta's "automated evidence"
   thesis from infosec into privacy + TPRM + AI, and hits OneTrust where it is
   weakest. The repo already has the substrate: goal **templates**, **skills**,
   MCP **connectors**, the **scheduler**.

3. **Self-host as the moat.** Regulated buyers must keep PHI/PCI/classified and
   EU-resident data in-boundary. Maverick's default-self-host + 7 sandboxes +
   local models sidestep the residency/data-egress objections that slow SaaS GRC
   sales — *if* Q1's encryption-at-rest and tenancy land.

### What is **not** agent-shaped (don't chase it)

The **cookie/consent CMP** (a real-time browser SDK + global cookie database),
the **ethics/whistleblower hotline**, and the **regulatory-content library** (the
55-framework corpus OneTrust's lawyers maintain) are *not* swarm work and are a
breadth slog against a deep incumbent. Partner or skip; do not clone.

---

## Part 5 — The plan (sequenced)

**Phase 0 — Governed Runtime (now; engineering-led; reuses the substrate).**
Close the narrow Q1 gaps as a single named track, each item config-gated +
wizard-surfaced + fail-open per house rules:
- `identity/` SSO-OIDC/SAML + SCIM → principal/tenant mapping.
- Encryption-at-rest (per-tenant DEK; OS-keychain or KMS).
- Finish tenancy (migrate world-model + audit onto `data_dir()`); per-tenant
  **quotas** on `Budget`.
- Audit **SIEM export** + WORM retention.
- Two-person rule in `consent.py`.
- Policy-as-code **framework tags** on ACL/capability/consent rules.

Outcome: Maverick is deployable in regulated environments **and** the Q2
foundation is poured. Valuable **regardless of the business-model decision.**

**Phase 1 — Agent/AI governance system of record (the unowned wedge).**
An **AI/agent registry** (owner, purpose, EU AI Act / NIST AI RMF / ISO 42001
risk tier, capabilities, data access) — mostly a projection over the capability
model + tool registry + world model — plus **framework-mapped evidence export**
that turns the signed audit chain into auto-populated control evidence, and the
**"where are my agents"** surface in the dashboard.

**Phase 2 — Compliance-as-agentic-labor.** Goal templates + connectors for DSAR
fulfillment, evidence collection (the Vanta adjacency, agent-run), ROPA-from-
discovery, and vendor-questionnaire completion. Ships incrementally; each
template is independently demoable.

**Phase 3 — Broader OneTrust surface (gated on Part 6).** Privacy-ops platform,
full TPRM, GRC console — only once a commercial entity and GTM exist.

---

## Part 6 — The commercial fork (founder decision, not an engineering one)

A OneTrust replacement is at odds with *open-source-only, no paid tiers*. Three
honest options:

- **(A) Open-core.** OSS Governed Runtime (Phase 0) stays free; the
  agent-governance **control plane + framework content + hosted multi-tenant SaaS**
  (Phases 1–3) is the commercial product. Most common path for this category;
  preserves the brand and the community while funding the enterprise build.
- **(B) Stay pure-OSS.** Ship Phase 0 (which the project wants anyway) and let
  third parties build the commercial product on top. Lowest risk, forgoes the
  prize.
- **(C) Full commercial pivot.** Bet the company on the compliance product. Highest
  ceiling, highest cost (certs, content, legal, sales), and the largest departure
  from current positioning.

**Recommendation:** ship **Phase 0 now** (it is on the roadmap, closes the
enterprise gaps, and is option-neutral), stand up **Phase 1** as the differentiated
wedge, and make the A/B/C call **before** Phase 2 — because Phase 2's connectors,
content, and support model are where the business model stops being optional.

---

## Part 7 — Fit with the house rules (CLAUDE.md)

- **Kernel runs without the shield / fail-open.** Every Phase-0 control is opt-in
  and config-gated (the existing pattern: capabilities, tenancy, consent, retention
  all default to no-op). Compliance enforcement is a *chokepoint a deployment turns
  on*, never a hard dependency of the kernel.
- **Users own model choice; budget caps mandatory; sandbox-mediate shell.**
  Unchanged — quotas *extend* `Budget`, they don't bypass `check()`.
- **No new top-level dep without a config knob; the wizard is the source of truth.**
  Each new capability (`[identity]`, `[encryption]`, `[audit.export]`, `[quotas]`)
  gets a wizard step, per rule 6.
- **Simplicity / surgical.** Most of Phase 1 is a *projection* of data we already
  emit; reuse the Ed25519 infra (`audit/signing.py`, `capability.py`) rather than
  new crypto. Resist building the OneTrust breadth that isn't agent-shaped.

---

## Confidence & caveats

- **High (code-verified):** every "what we have" row (file-cited from `main`); the
  identity/encryption-at-rest/quota gaps (`grep` negative for `oidc|saml|scim`;
  `Budget.check()` is per-run; no at-rest envelope encryption of `world.db`/audit).
- **High (multi-source):** OneTrust's "configuration-not-code / manual-workflow"
  weakness; Vanta/Drata = infosec-evidence automation; agent governance is an
  unowned, forming category (OWASP Agentic Top 10; CSA NHI; Okta/Microsoft entries).
- **Directional / [verify]:** OneTrust revenue (~$400–500M ARR), valuation
  (~$4.5B last marked vs. rumored $10B+ PE talks), and the maturity of its 2026
  *AI-agent* features (third-party-reported, not prominent on OneTrust's own site);
  EU AI Act **agentic-specific** obligations are still preliminary per the
  Commission; SR 26-2 as an SR 11-7 modernization is unconfirmed. Re-check load-
  bearing numbers against primary sources before any external use.
- **Analytical (mine):** "two questions, one substrate" and "own agent governance,
  don't clone OneTrust" are syntheses grounded in the audit + landscape, not
  sourced facts.

## Sources

- OneTrust: <https://www.onetrust.com/>, <https://research.contrary.com/company/onetrust>,
  <https://news.crunchbase.com/enterprise/onetrust-funding-valuation-down-round/>,
  <https://www.ketch.com/blog/posts/what-onetrust-cannot-do>, <https://sprinto.com/blog/onetrust-alternatives/>
- AI / agent governance: <https://www.modulos.ai/best-ai-governance-platforms/>,
  <https://credo.ai/>, <https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit-open-source-runtime-security-for-ai-agents/>,
  <https://www.okta.com/newsroom/articles/ai-agents-at-work-2026-agentic-enterprise-security/>,
  <https://labs.cloudsecurityalliance.org/research/csa-whitepaper-nonhuman-identity-agentic-ai-governance-v1-cs/>,
  OWASP Top 10 for Agentic Applications (Dec 2025)
- Regulated deployment: <https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai>,
  <https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/standard-contractual-clauses-scc_en>,
  <https://advisera.com/articles/iso-42001-certification/>, <https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7>,
  <https://sprinto.com/blog/fedramp-vs-soc-2/>
- Continuous compliance: <https://drata.com/blog/secureframe-vs-vanta-vs-drata>,
  <https://www.secureleap.tech/blog/soc-2-tools-vanta-drata-secureframe-guide-2025>
</content>
