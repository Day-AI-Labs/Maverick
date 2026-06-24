# Vendor & Supplier Management Procedure

| Field | Value |
| --- | --- |
| Document ID | PROC-07 |
| Owner | Security Lead / Legal |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | SOC 2 CC9.2; ISO/IEC 27001:2022 A.5.19, A.5.20, A.5.21, A.5.22, A.5.23; ISO/IEC 42001:2023 A.10.2, A.10.3 |

## 1. Purpose & scope

This procedure operationalizes the Supplier Security Policy (POL-09). It defines
how the Organization identifies, risk-tiers, assesses, contracts with, monitors,
and offboards third parties that support **Maverick** — the Organization's
governed agentic enterprise AI platform.

It applies to **any third party** that:

- **Processes Organization or customer data** on the Organization's behalf
  (a sub-processor under the Data Processing Agreement), **or**
- **Forms part of the Maverick software supply chain** — i.e. supplies code,
  models, infrastructure, or services into the platform or its runtime.

In scope, non-exhaustively:

| Category | Examples | Typical data exposure |
| --- | --- | --- |
| LLM / model providers | Anthropic, OpenAI, Azure OpenAI, Bedrock, self-hosted vLLM/Ollama (no-egress) | Prompts + tool I/O sent at inference time |
| Cloud / infrastructure | AWS, GCP, Azure, hosting / Kubernetes provider | All hosted state at rest + in transit |
| Telemetry / observability | Sentry, log/metrics aggregation | Scrubbed error events, operational metadata |
| Channels | Email/SMS (e.g. SendGrid, Twilio), Slack, messaging | Message content + recipient identifiers |
| Vector stores / object storage | Managed vector DB, S3-class object storage | RAG knowledge, attachment content |
| Developer supply chain | Package registries, plugin/pack authors, MCP tool publishers, external agents | Code, dependencies, executable tool definitions |

Out of scope: purchases that neither touch Organization/customer data nor feed
software/services into Maverick (e.g. office supplies). When in doubt, treat the
vendor as in scope and let the risk-tiering step (Section 2, step 2) decide the
depth of diligence.

This procedure is operated by the Organization outside the codebase; steps that
require real-world execution are marked **[Org action]**. The software
supply-chain *integrity* controls in Section 5 exist in the Maverick codebase.

## 2. Vendor onboarding workflow

No in-scope vendor is approved until every applicable step below is complete and
recorded. Work the checklist top to bottom.

- [ ] **Step 1 — Identify data exposure.** **[Org action]** Determine what
      Organization/customer data the vendor will process or could access
      (categories, sensitivity, volume, whether personal data / special-category
      data) and where the vendor sits in the supply chain (data processor,
      infrastructure, or executable supply-chain input). Record in the vendor
      register (REG-04).
- [ ] **Step 2 — Risk-tier the vendor.** **[Org action]** Assign a tier —
      **Critical / High / Medium / Low** — as a function of **data sensitivity**
      and **criticality to the service** (see the matrix in Section 3). The tier
      determines the required diligence in the following steps.
- [ ] **Step 3 — Security review.** **[Org action]** Issue the Vendor Security
      Questionnaire (**TPL-04**) and request the vendor's independent assurance
      evidence — a current **SOC 2 Type II** report or **ISO/IEC 27001**
      certificate (and **ISO/IEC 42001** for AI vendors, where available). Review
      the responses and evidence; record findings and any exceptions. Depth of
      review follows the tier (Section 3).
- [ ] **Step 4 — Contractual controls.** **[Org action]** Execute the required
      agreements **before** any data is processed:
      - A signed **Data Processing Agreement** for any vendor processing personal
        data, using `docs/enterprise/legal/dpa-template.md` (GDPR Art. 28; covers
        confidentiality, security, sub-processing notice, breach notification,
        DSAR assistance, deletion/return).
      - A **Service Level Agreement** where availability/support matters, using
        `docs/enterprise/legal/sla-template.md`.
      - Confirm the vendor's own DPA / sub-processor terms are acceptable.
- [ ] **Step 5 — Register the vendor.** **[Org action]** Add the vendor to the
      **vendor register** (`docs/compliance/registers/vendor-register.md`,
      REG-04). If the vendor processes customer data, also add it to the
      **subprocessor register**
      (`docs/compliance/registers/subprocessor-register.md`) and the
      customer-facing disclosure `docs/enterprise/legal/subprocessors.md`.
- [ ] **Step 6 — Approve.** **[Org action]** The approver per the matrix in
      Section 3 records the approval decision, tier, and review-due date in
      REG-04. Critical/High vendors require Management approval.

## 3. Risk-tier × required-diligence matrix

Tier is the higher of (a) data sensitivity exposed and (b) criticality to
service continuity. A vendor processing customer personal data, or whose outage
takes Maverick down, is at least **High**.

| Tier | When it applies | Independent assurance required | Contract | Re-review cadence | Approver |
| --- | --- | --- | --- | --- | --- |
| **Critical** | Processes customer personal data **and** is single-point-of-failure for the service (e.g. primary LLM provider, primary cloud host) | Current **SOC 2 Type II** *or* **ISO/IEC 27001** certificate (AI vendors: also ISO/IEC 42001 where available); full TPL-04 reviewed | Signed **DPA** + **SLA**; sub-processor notice clause | **Annual** + on any material change | Management |
| **High** | Processes sensitive/personal data **or** is service-critical (not both) | Current **SOC 2 Type II** *or* **ISO/IEC 27001**; full TPL-04 reviewed | Signed **DPA** (if personal data) + SLA | **Annual** | Management |
| **Medium** | Processes limited / scrubbed / non-sensitive data, moderate criticality (e.g. telemetry on scrubbed events) | Lighter review: TPL-04 completed; assurance report requested, gaps risk-accepted if absent | DPA if any personal data; standard terms otherwise | **Every 18–24 months** | Security Lead |
| **Low** | No Organization/customer data exposure, easily replaceable, minimal criticality | **Self-attestation** via TPL-04; no report required | Standard terms | **Every 24 months** or on change | Security Lead |

Where a Critical/High vendor cannot provide a current SOC 2 Type II or ISO/IEC
27001 report, onboarding requires a documented **risk acceptance** with
compensating controls and Management approval (POL-09 §7). **[Org action]**

## 4. Ongoing monitoring

Vendor risk is managed across the whole relationship, not just at onboarding.

- **Periodic re-assessment.** **[Org action]** Re-run the applicable TPL-04
  review and refresh the assurance evidence on the cadence set by the tier
  (Section 3). Update `last review date` and `next review due` in REG-04.
- **Assurance currency.** **[Org action]** Track expiry of each vendor's SOC 2
  Type II / ISO certificate; a lapsed report triggers a review before the normal
  cadence.
- **Incident & breach watch.** **[Org action]** Monitor for the vendor's own
  security incidents, breaches, or material control failures (advisories, status
  pages, breach notifications received under the DPA). A confirmed vendor breach
  triggers an out-of-cycle re-review and is logged in the risk register.
- **Scope-change trigger.** **[Org action]** Re-review whenever the engagement
  changes materially — new data categories, a new region, a new sub-processor
  introduced by the vendor, or a change in how the vendor uses data (e.g. an LLM
  provider changing training-data or retention terms).

## 5. Software supply-chain integrity controls (existing in Maverick)

For the developer/executable supply chain, Maverick enforces integrity controls
in code. These are **implemented** and operate independently of the process
controls above:

| Control | Implementation |
| --- | --- |
| MCP command **hash-pinning** + tool-description **scanning** at registration | MCP tool registration path; `packages/maverick-core/maverick/mcp_oauth.py` |
| Plugin **default-deny allowlist** (`MAVERICK_PLUGINS_ALLOW`) + skill-body scan + **hash-pin** at install | `packages/maverick-core/maverick/plugin_manifest.py` |
| Automated **dependency monitoring** / update alerting | `.github/dependabot.yml` |
| **Provenance tagging** (`vendor:agent_id`) of external agent contributions in fleet memory | `packages/maverick-core/maverick/fleet_memory.py` |

Plugins and MCP tools are **denied by default** and admitted only via explicit
allowlisting plus integrity verification. This default-deny posture is not
weakened without a documented risk acceptance (POL-09 §7).

## 6. Sub-processor change management

Adding a new sub-processor that will process customer data is a controlled
change governed by the DPA's change-notification clause.

- [ ] **[Org action]** Risk-tier and assess the candidate sub-processor via the
      onboarding workflow (Section 2) **before** it begins processing.
- [ ] **[Org action]** Update the **subprocessor register**
      (`docs/compliance/registers/subprocessor-register.md`) and the
      customer-facing `docs/enterprise/legal/subprocessors.md`.
- [ ] **[Org action]** **Notify affected customers before** the sub-processor is
      activated, giving the notice period and right-to-object stated in the DPA
      (`docs/enterprise/legal/dpa-template.md` §6). Record the notification date.
- [ ] **[Org action]** Handle any customer objection per the DPA before
      activation.

Self-hosted / egress-locked LLM deployments add **no** LLM sub-processor —
inference stays on the customer's infrastructure; state this explicitly in the
register rather than listing a provider.

## 7. Offboarding a vendor

On termination or replacement of a vendor:

- [ ] **[Org action]** **Revoke access** — API keys, credentials, network
      allowlists, SSO grants, and any data-sharing integrations. Rotate any
      shared secrets the vendor held.
- [ ] **[Org action]** **Confirm data return / destruction** per the DPA: obtain
      written confirmation of deletion (or return) of Organization/customer data,
      including backups, within the contractual window.
- [ ] **[Org action]** **Update the registers** — set the vendor's status to
      *Offboarded* in REG-04; remove it from the subprocessor register and the
      customer-facing `subprocessors.md`; **notify customers** if a disclosed
      sub-processor was removed.
- [ ] **[Org action]** For executable supply-chain inputs, remove the vendor's
      plugin/MCP entries from the allowlist (`MAVERICK_PLUGINS_ALLOW`) so the
      default-deny posture re-applies.
- [ ] **[Org action]** Record offboarding completion (date, evidence of
      destruction) as audit evidence.

## 8. Records & evidence

The following are retained as audit evidence for SOC 2 CC9.2 / ISO 27001
A.5.19–A.5.23 / ISO 42001 A.10.2–A.10.3: completed TPL-04 questionnaires, vendor
assurance reports, signed DPAs/SLAs, the vendor register (REG-04), the
subprocessor register, approval and risk-acceptance decisions, monitoring and
re-review records, sub-processor change notifications, and offboarding
confirmations.

## 9. Related documents

- Supplier Security Policy — `docs/compliance/policies/supplier-security-policy.md` (POL-09)
- Vendor Security Questionnaire — `docs/compliance/templates/vendor-security-questionnaire.md` (TPL-04)
- Vendor Register — `docs/compliance/registers/vendor-register.md` (REG-04)
- Subprocessor Register — `docs/compliance/registers/subprocessor-register.md`
- DPA template — `docs/enterprise/legal/dpa-template.md`
- SLA template — `docs/enterprise/legal/sla-template.md`
- Customer-facing sub-processor disclosure — `docs/enterprise/legal/subprocessors.md`
