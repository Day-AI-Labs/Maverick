# Vendor Risk Register

| Field | Value |
| --- | --- |
| Document ID | REG-04 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | SOC 2 CC9.2; ISO/IEC 27001:2022 A.5.19, A.5.20, A.5.22, A.5.23; ISO/IEC 42001:2023 A.10.2, A.10.3 |

## How to use this register

This register is the Organization's authoritative inventory of in-scope vendors
and suppliers, maintained under the Vendor & Supplier Management Procedure
(PROC-07). It is operated by the Organization — **[Org action]** — and reviewed
at least annually and on material change.

- **One row per vendor** that processes Organization/customer data or feeds the
  Maverick software supply chain (see PROC-07 §1 for scope).
- **Add a vendor** at onboarding Step 5 (PROC-07 §2) once risk-tiered, reviewed
  (TPL-04), and contracted. Vendors that process **customer data** must **also**
  appear in `docs/compliance/registers/subprocessor-register.md` and the
  customer-facing `docs/enterprise/legal/subprocessors.md`.
- **Risk tier** (Critical / High / Medium / Low) is assigned per PROC-07 §3 and
  drives the diligence required and the re-review cadence (Critical/High:
  annual; Medium: 18–24 months; Low: 24 months).
- **Keep `next review due` current.** A row past its review date, or a vendor
  whose SOC 2 / ISO assurance has lapsed, is overdue and must be re-assessed.
- **On offboarding**, set **Status** to *Offboarded* (do not delete the row —
  retain it as audit evidence) and remove the vendor from the subprocessor
  register and customer-facing disclosure per PROC-07 §7.

### Columns

| Column | Meaning |
| --- | --- |
| Vendor | Legal/trading name of the third party |
| Service | What they provide to Maverick |
| Data exposed | Categories of Organization/customer data processed or accessible |
| Risk tier | Critical / High / Medium / Low (PROC-07 §3) |
| SOC2 / ISO status | Independent assurance held and its currency/expiry |
| DPA signed | Y/N + date a DPA was executed (— if not applicable) |
| Last review | Date of most recent assessment (TPL-04) |
| Next review due | Date the next re-assessment is due |
| Owner | Christopher Day |
| Status | Active / Pending review / Offboarded / Risk-accepted |

## Register

> The rows below are **ILLUSTRATIVE EXAMPLES** showing how to complete the
> register. They are **not assertions of fact** — no real agreements, dates, or
> assurance status are implied. Replace with the Organization's actual vendors
> before this register is used as audit evidence. **[Org action]**

| Vendor | Service | Data exposed | Risk tier | SOC2 / ISO status | DPA signed | Last review | Next review due | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *(example)* `<LLM provider>` | LLM inference for agent turns | Prompts + tool I/O at inference time | Critical | SOC 2 Type II `<period>`; ISO 27001 `<expiry>` | Y — `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | Security Lead | Active |
| *(example)* `<Cloud host>` | Production hosting & storage | All hosted state at rest/in transit | Critical | SOC 2 Type II `<period>`; ISO 27001 `<expiry>` | Y — `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | Head of Engineering | Active |
| *(example)* `<Telemetry provider>` | Error tracking | Scrubbed error events only | Medium | SOC 2 Type II `<period>` | Y — `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | `<YYYY-MM-DD>` | Security Lead | Active |

## Related documents

- Vendor & Supplier Management Procedure — `docs/compliance/procedures/vendor-management-procedure.md` (PROC-07)
- Vendor Security Questionnaire — `docs/compliance/templates/vendor-security-questionnaire.md` (TPL-04)
- Subprocessor Register — `docs/compliance/registers/subprocessor-register.md`
- Supplier Security Policy — `docs/compliance/policies/supplier-security-policy.md` (POL-09)
- DPA template — `docs/enterprise/legal/dpa-template.md`
- Customer-facing sub-processor disclosure — `docs/enterprise/legal/subprocessors.md`
