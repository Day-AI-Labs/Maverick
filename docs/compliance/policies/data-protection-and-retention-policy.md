# Data Protection & Retention Policy

| Field | Value |
| --- | --- |
| Document ID | POL-11 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.5.33, A.5.34, A.8.10, A.8.11, A.8.12; ISO/IEC 42001:2023 A.7.x; SOC 2 C1.1, C1.2, Privacy P1–P8 |

## 1. Purpose

This policy establishes how the Organization classifies, handles, retains, and disposes of data processed by Maverick, and how it protects personal data (PII) and the rights of data subjects. It defines the controls that ensure data is held only as long as necessary, protected against leakage and unauthorized exposure, and erasable on demand. It supports the Organization's obligations under the EU General Data Protection Regulation (GDPR), ISO/IEC 27001:2022, ISO/IEC 42001:2023, and the SOC 2 Confidentiality and Privacy criteria.

## 2. Scope

This policy applies to all data created, ingested, derived, stored, or transmitted by Maverick — including the world model (operational state), the signed audit chain, fleet/shared memory, share-link artifacts, and any data used for or produced by AI systems. It covers all tenants, all environments (development, staging, production), all personnel and automated agents acting on the Organization's behalf, and all data classifications from public through restricted/personal data. It applies to data at rest, in transit, and in use.

## 3. Policy statements

1. **Data classification.** All data handled by Maverick shall be classified (e.g. Public, Internal, Confidential, Restricted/Personal) and handled according to its classification. Personal data and secrets are treated as the highest-sensitivity classes. **[Process — Organization to operationalize]** the formal classification scheme, labelling convention, and the mapping of Maverick data stores to classes.
2. **Data minimization.** Maverick shall collect and retain only the personal data necessary for its stated purpose. Identifying fields shall be minimized, redacted, or anonymized wherever the processing purpose does not require them.
3. **Data handling.** Personal and confidential data shall be encrypted at rest, isolated per tenant and per owner, and protected against accidental or malicious leakage. Sensitive tokens shall never be stored in recoverable plaintext.
4. **Retention limitation (GDPR Art. 5(1)(e)).** Data shall be retained only for as long as required by its purpose or by a documented legal/contractual obligation. Time-to-live (TTL) retention windows shall be enforced and expired data scheduled for deletion. **[Process — Organization to operationalize]** the retention schedule (per data category, with retention periods and legal bases).
5. **Disposal & deletion (Art. 17).** Expired data and data subject to an erasure request shall be securely deleted from all stores, including derived and audit data, and the integrity of remaining records preserved.
6. **Data-subject rights.** The Organization shall honor data-subject requests for access and portability (GDPR Art. 15/20) and erasure (Art. 17) within the statutory timeframe, and shall be able to demonstrate erasure completeness. **[Process — Organization to operationalize]** the DSAR intake, identity-verification, tracking, and response SLA workflow.
7. **PII & secret detection.** Inputs and outputs shall be scanned for PII and secrets, with redaction applied before storage, logging, or transmission where appropriate.
8. **Data masking.** Personal and sensitive fields shall be masked or anonymized in non-production, diagnostic, and shared contexts.
9. **Records protection (A.5.33).** The audit/operating record shall be protected against unauthorized alteration; cryptographic integrity shall be maintained across any permitted deletion.
10. **AI data quality & provenance (ISO 42001 A.7.x).** Data used by or produced for AI systems shall carry provenance and be subject to the same privacy, quality, and retention controls as all other data.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Data Protection Officer (DPO) | Owns this policy; oversees DSAR/erasure handling, retention schedule, and GDPR compliance. |
| Security Lead | Owns at-rest encryption, tenant isolation, leakage prevention, and secret handling. |
| Engineering | Implements and maintains the technical controls listed in Section 5. |
| Tenant/Data Owner | Classifies data they introduce and raises retention/erasure needs. |
| Management | Approves this policy and the retention schedule; accepts residual risk. |

**[Process — Organization to operationalize]** named individuals/teams for each role.

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| DSAR access & portability bundle (GDPR Art. 15/20) — export of world + audit data | `packages/maverick-core/maverick/dsar.py` | Implemented |
| TTL retention enforcement + Art. 17 erasure scheduling | `packages/maverick-core/maverick/audit/retention.py` | Implemented |
| Subject deletion: scrub world DB + audit, re-sign chain | `packages/maverick-core/maverick/audit/erase.py` | Implemented |
| Erasure completeness verification | `packages/maverick-core/maverick/erasure_verify.py` | Implemented |
| Anonymous mode — strip identifying fields (data minimization) | `packages/maverick-core/maverick/privacy.py` | Implemented |
| Per-column at-rest encryption, tenant isolation, per-user owner scoping; share-link tokens stored as SHA-256 only | `packages/maverick-core/maverick/world_model.py` | Implemented |
| PII detection & redaction | `packages/maverick-core/maverick/safety/pii_detector.py` | Implemented |
| Secret detection & redaction | `packages/maverick-core/maverick/safety/secret_detector.py` | Implemented |
| Per-tenant data directory isolation | `packages/maverick-core/maverick/paths.py` | Implemented |
| Retention check tooling | `packages/maverick-core/maverick/tools/retention_check.py` | Implemented |
| Regulated-deployment guidance | `docs/regulated-deployment.md` | Reference |
| Retention schedule (per-category periods & legal bases) | — | **[Process — Organization to operationalize]** |
| DSAR intake / identity-verification / SLA workflow | — | **[Process — Organization to operationalize]** |
| Formal data classification scheme & labelling | — | **[Process — Organization to operationalize]** |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.5.33 (protection of records — signed, re-signable audit chain), A.5.34 (privacy & PII protection — DSAR, anonymous mode, PII detection), A.8.10 (information deletion — TTL + erasure + verifier), A.8.11 (data masking — redaction & anonymization), A.8.12 (data leakage prevention — encryption, tenant/owner isolation, hashed share tokens, secret detection) |
| ISO/IEC 42001:2023 | A.7.x (data for AI systems — quality, provenance, privacy controls applied to AI data) |
| SOC 2 | C1.1, C1.2 (confidentiality — identification, retention, and disposal of confidential information); Privacy P1–P8 (notice, choice/consent, collection minimization, use/retention/disposal, access, disclosure, quality, monitoring/enforcement) — technical enablers; **[Process — Organization to operationalize]** the privacy notice and consent records |

## 7. Exceptions & non-compliance

Exceptions to this policy require documented risk assessment and written approval from the DPO and Management, with a defined expiry and compensating controls. Legal holds override routine deletion and must be recorded. Non-compliance may result in remediation, revocation of access, and disciplinary action. Suspected personal-data breaches shall be escalated under the incident-response process and assessed against statutory notification obligations (GDPR Art. 33/34). **[Process — Organization to operationalize]** the exception register and breach-notification runbook.

## 8. Review & maintenance

This policy is reviewed at least annually and upon any significant change to data flows, regulatory obligations, or the technical controls in Section 5. The DPO maintains the policy; Management approves material changes. Each review shall confirm that the file/module references in Section 5 remain accurate and that the retention schedule is current.
