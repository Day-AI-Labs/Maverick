# Vendor Security Assessment Questionnaire

| Field | Value |
| --- | --- |
| Document ID | TPL-04 |
| Owner | Security Lead / Legal |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | SOC 2 CC9.2; ISO/IEC 27001:2022 A.5.19, A.5.20, A.5.21, A.5.22, A.5.23; ISO/IEC 42001:2023 A.10.2, A.10.3 |

> Issued by the Organization to a prospective or existing vendor as **Step 3** of
> the Vendor & Supplier Management Procedure (PROC-07). Depth of review follows
> the vendor's risk tier (PROC-07 §3): Critical/High vendors complete the whole
> questionnaire and supply an assurance report; Low vendors may self-attest.
> The Organization issues, collects, and scores this form — **[Org action]**.

**Vendor:** `<legal name>`  **Service assessed:** `<…>`  **Date issued:** `<YYYY-MM-DD>`
**Assigned risk tier (PROC-07 §3):** `<Critical / High / Medium / Low>`
**Reviewer (Organization):** `<name>`

---

## Section A — Company & contact

| # | Question | Response |
| --- | --- | --- |
| A1 | Legal entity name, headquarters country, and entities involved in delivering the service. | |
| A2 | Primary **security contact** (name, email) and **breach-notification** contact. | |
| A3 | Where is the service operated from, and where is the support team located? | |
| A4 | Number of employees and years in operation. | |

## Section B — Certifications & independent assurance

| # | Question | Response |
| --- | --- | --- |
| B1 | Do you hold a current **SOC 2 Type II** report? Report period and date? (Attach or share under NDA.) | |
| B2 | Are you certified to **ISO/IEC 27001**? Certificate number, scope, expiry, certification body. | |
| B3 | (AI vendors) Are you certified to or aligned with **ISO/IEC 42001** (AI management system)? | |
| B4 | Other relevant attestations (ISO 27017/27018, PCI DSS, HIPAA, FedRAMP, CSA STAR)? | |
| B5 | Date and summary of your most recent **independent third-party audit / pen test**. | |

## Section C — Data handling & residency

| # | Question | Response |
| --- | --- | --- |
| C1 | What categories of Organization/customer data will the service process? | |
| C2 | In which **regions / countries** is data stored and processed? Can residency be pinned (e.g. EU-only)? | |
| C3 | Is data **logically or physically segregated** by tenant/customer? | |
| C4 | What is your **data retention** period, and how is data deleted on request / on termination? | |
| C5 | Do you support **data export / portability** and assistance with data-subject requests (DSARs)? | |
| C6 | Are international transfers covered by **SCCs**, adequacy, or equivalent safeguards? | |

## Section D — Encryption

| # | Question | Response |
| --- | --- | --- |
| D1 | Encryption **in transit** (TLS version, mTLS, cipher policy)? | |
| D2 | Encryption **at rest** (algorithm, e.g. AES-256; scope: DB, backups, object storage)? | |
| D3 | **Key management** — KMS/HSM, rotation policy, customer-managed keys (CMEK) support? | |

## Section E — Access control & authentication

| # | Question | Response |
| --- | --- | --- |
| E1 | Is **MFA** enforced for all staff with access to customer data and production systems? | |
| E2 | Is access granted on **least-privilege / RBAC** and reviewed periodically? | |
| E3 | **SSO / OIDC / SAML** support for our administrators? | |
| E4 | How is **privileged / production access** controlled, logged, and time-bound? | |
| E5 | Offboarding: how quickly is access revoked when your staff leave? | |

## Section F — Sub-processors

| # | Question | Response |
| --- | --- | --- |
| F1 | List your **sub-processors** that would process our data (name, purpose, region). | |
| F2 | How do you **notify** customers before adding/changing a sub-processor, and what notice period? | |
| F3 | How do you flow down security and data-protection obligations to sub-processors? | |

## Section G — Incident response & breach notification

| # | Question | Response |
| --- | --- | --- |
| G1 | Do you maintain a documented **incident response plan**? Last tested when? | |
| G2 | What is your **breach-notification SLA** to customers (target hours)? | |
| G3 | How are security logs retained, and are they available to customers during an incident? | |

## Section H — Business continuity & disaster recovery

| # | Question | Response |
| --- | --- | --- |
| H1 | Documented **BCP/DR** plan? Last tested when? | |
| H2 | Stated **RPO** and **RTO** for the service. | |
| H3 | Backup cadence, retention, and restore testing. | |
| H4 | Published **uptime SLA** and historical availability. | |

## Section I — Vulnerability management & testing

| # | Question | Response |
| --- | --- | --- |
| I1 | Frequency of **vulnerability scanning** and **penetration testing** (and who performs it)? | |
| I2 | Remediation SLAs by severity (critical/high/medium). | |
| I3 | Secure development practices (SAST/DAST, dependency scanning, code review)? | |
| I4 | Do you operate a **vulnerability disclosure / bug-bounty** program? | |

## Section J — Privacy, GDPR & DPA

| # | Question | Response |
| --- | --- | --- |
| J1 | Will you sign **our DPA** (`docs/enterprise/legal/dpa-template.md`) or provide your own GDPR Art. 28 DPA? | |
| J2 | Lawful basis and any processing of **special-category** data? | |
| J3 | Privacy-by-design measures, data minimization, and a named DPO (if applicable). | |

## Section K — AI / model governance (AI & LLM vendors only)

| # | Question | Response |
| --- | --- | --- |
| K1 | Do you use customer **prompts, completions, or tool I/O to train or improve models**? Can this be disabled / is it off by default for our tier? | |
| K2 | **Retention** of inference inputs/outputs — duration and deletion controls (e.g. zero-retention / no-logging mode)? | |
| K3 | Model **governance** — documented evaluation, safety testing, bias/robustness assessment, and model/version change management (ISO/IEC 42001). | |
| K4 | **Training-data provenance** — how is training data sourced, and are there IP/licensing or data-rights assurances? | |
| K5 | Human oversight, abuse monitoring, and content-filtering controls relevant to our use. | |
| K6 | Sub-processors specific to inference (GPU/hosting providers) and their regions. | |

---

## Scoring & decision

Reviewer scores each applicable section **0–4**; weight Critical/High vendors
toward Sections B, C, D, E, G, J (and K for AI vendors).

| Score | Meaning |
| --- | --- |
| 4 | Fully meets requirements with independent evidence |
| 3 | Meets requirements; minor gap, no material risk |
| 2 | Partial; remediation or compensating control needed |
| 1 | Significant gap; risk acceptance required to proceed |
| 0 | Does not meet a mandatory requirement; **do not onboard** without remediation |

| Section | Score (0–4) | Notes / evidence |
| --- | --- | --- |
| A — Company & contact | | |
| B — Certifications & assurance | | |
| C — Data handling & residency | | |
| D — Encryption | | |
| E — Access control & auth | | |
| F — Sub-processors | | |
| G — Incident & breach | | |
| H — BC/DR | | |
| I — Vuln mgmt & testing | | |
| J — Privacy / GDPR / DPA | | |
| K — AI / model governance (if AI vendor) | | |

**Mandatory gate (Critical/High):** a current SOC 2 Type II **or** ISO/IEC 27001
report **and** a signed DPA (where personal data is processed). A `0` on any
mandatory item blocks onboarding absent a documented risk acceptance.

**Overall risk rating:** `<Low / Medium / High / Critical>`
**Outstanding gaps / compensating controls:** `<…>`
**Decision:** `<Approve / Approve with conditions / Reject>`  — **[Org action]**
**Reviewer:** `<name>`  **Approver (per PROC-07 §3):** `<name>`  **Date:** `<YYYY-MM-DD>`
**Next review due:** `<YYYY-MM-DD>`

> Record the outcome in the vendor register
> (`docs/compliance/registers/vendor-register.md`, REG-04) and, for data
> processors, the subprocessor register
> (`docs/compliance/registers/subprocessor-register.md`).
