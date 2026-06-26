# Maverick Compliance Program

This directory is the home of Maverick's compliance documentation. It supports
three audit/certification tracks that share one backbone of organizational
controls:

- **SOC 2** (AICPA Trust Services Criteria) — Type I then Type II attestation.
- **ISO/IEC 27001:2022** — Information Security Management System (ISMS).
- **ISO/IEC 42001:2023** — Artificial Intelligence Management System (AIMS).

> **Honesty note.** None of these is a code audit. Maverick's engineering
> controls satisfy a large share of each framework's *technical* requirements,
> but every framework also requires *organizational* controls (governance,
> management review, HR, vendor management, incident-response programs) that
> live with the company, not the repository. Throughout these docs those items
> are marked **Process** and must be owned and operated by the Organization.

SOC 1 is intentionally **out of scope** — Maverick is not a system of record
for customers' financial statements (ICFR), so a SOC 1 report does not apply
unless a customer pushes Maverick into their financial-reporting chain.

> **Ownership.** All ISMS/AIMS roles and document owners currently resolve to a
> single accountable individual, **Christopher Day**, who is the named Owner and
> Approver throughout. This is the reality of a small/solo operation; where a
> control assumes segregation of duties between an owner and an approver, that is
> a recognized small-org situation handled by compensating controls (the
> tamper-evident audit log, CI gates, and external assessor review). Functional
> role names in the procedures (Security Lead, AI Lead, Incident Commander, …)
> are hats worn by the same person until the team grows.

## How the frameworks relate

There is one shared control backbone. Write it once; it feeds all three tracks.

```
        Policies + Risk Register + Risk Methodology   (this directory)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
     SOC 2                ISO 27001             ISO 42001
  (TSC attestation)     (ISMS cert)         (AIMS cert; stacks
   Type I → Type II      Clauses 4–10 +      on ISO 27001, ~30–50%
                         Annex A (93 ctrls)   cheaper as add-on)
```

- **SOC 2** is the hard procurement gate enterprise buyers ask for first.
- **ISO 27001** reuses the same risk register, policies, and many controls,
  adding the formal ISMS clauses and a Statement of Applicability.
- **ISO 42001** stacks on top of ISO 27001 and adds AI-specific governance
  (lifecycle, transparency, human oversight, AI risk/impact, data provenance).

## Document map

| Document | Purpose |
| --- | --- |
| [`control-crosswalk.md`](control-crosswalk.md) | One table mapping SOC 2 TSC ↔ ISO 27001 Annex A ↔ ISO 42001 Annex A to the controls and codebase evidence. The master index for auditors. |
| [`risk-management-methodology.md`](risk-management-methodology.md) | How risk is identified, scored, treated, and reviewed (IS + AI risk). |
| [`risk-register.md`](risk-register.md) | The consolidated risk register: live risks, scores, treatment, owners. |
| [`policies/`](policies/) | The 12 ISMS/AIMS policies (see below). |
| [`soc2-controls.md`](soc2-controls.md) | SOC 2 Trust Services Criteria → control mapping (pre-existing; the model the crosswalk extends). |
| [`soc2/README.md`](soc2/README.md) | SOC 2 readiness, Type I → Type II path, and the control "turn-on" guide. |
| [`iso-27001/README.md`](iso-27001/README.md) | ISMS scope, mandatory-document checklist, gap analysis, certification roadmap. |
| [`iso-27001/statement-of-applicability.md`](iso-27001/statement-of-applicability.md) | SoA for all 93 ISO 27001:2022 Annex A controls. |
| [`iso-42001/README.md`](iso-42001/README.md) | AIMS scope, gap analysis, certification roadmap. |
| [`iso-42001/statement-of-applicability.md`](iso-42001/statement-of-applicability.md) | SoA for the ISO 42001 Annex A controls. |
| [`procedures/README.md`](procedures/README.md) | **Operational layer index** — the runbooks, registers, templates, and deployment artifacts that operate the policies. |
| [`procedures/`](procedures/) | 7 operational procedures (incident response, vuln mgmt, change mgmt, risk review, internal audit, HR security, vendor mgmt). |
| [`registers/`](registers/) | 5 live registers (sub-processors, remediation, CAPA, vendors, assets). |
| [`templates/`](templates/) | 4 fill-in templates (incident report, management-review minutes, AUP, vendor questionnaire). |
| [`deployment/`](deployment/) | Hardened reference config + checklist + `verify-posture.sh` that operationalize "enable the opt-in controls." |
| [`evidence/`](evidence/) | Dated operating records (first internal audit + management review) produced by running the procedures. |

## Policy set

| ID | Policy | Primary frameworks |
| --- | --- | --- |
| POL-01 | [Information Security Policy](policies/information-security-policy.md) | ISO 27001 5.2 / A.5.1; ISO 42001 5.2; SOC 2 CC1–CC2 |
| POL-02 | [Risk Management Policy](policies/risk-management-policy.md) | ISO 27001 6.1/8.2/8.3; ISO 42001 6.1; SOC 2 CC3 |
| POL-03 | [Access Control Policy](policies/access-control-policy.md) | ISO 27001 A.5.15–18, A.8.2–5; SOC 2 CC6 |
| POL-04 | [Cryptography Policy](policies/cryptography-policy.md) | ISO 27001 A.8.24, A.5.33; SOC 2 CC6.1/6.7/C1.1 |
| POL-05 | [Change Management Policy](policies/change-management-policy.md) | ISO 27001 A.8.31/8.32; ISO 42001 A.6.2; SOC 2 CC8 |
| POL-06 | [Secure Development Policy](policies/secure-development-policy.md) | ISO 27001 A.8.25–30, A.8.8; ISO 42001 A.6.2; SOC 2 CC8/PI |
| POL-07 | [Incident Response Policy](policies/incident-response-policy.md) | ISO 27001 A.5.24–28, A.6.8; ISO 42001 A.10; SOC 2 CC7.3/7.4 |
| POL-08 | [Business Continuity Policy](policies/business-continuity-policy.md) | ISO 27001 A.5.29/5.30, A.8.13/8.14; SOC 2 A1 |
| POL-09 | [Supplier Security Policy](policies/supplier-security-policy.md) | ISO 27001 A.5.19–23; ISO 42001 A.10; SOC 2 CC9.2 |
| POL-10 | [Human Resources Security Policy](policies/human-resources-security-policy.md) | ISO 27001 A.6.1–8; ISO 42001 A.3.2/A.4.6; SOC 2 CC1.4 |
| POL-11 | [Data Protection & Retention Policy](policies/data-protection-and-retention-policy.md) | ISO 27001 A.5.33/5.34, A.8.10–12; ISO 42001 A.7; SOC 2 C1/Privacy |
| POL-12 | [AI Management Policy](policies/ai-management-policy.md) | ISO 42001 5.2 / A.2–A.9; EU AI Act; SOC 2 PI |

## Program status (point-in-time)

| Track | Technical controls | Documentation | Organizational controls | Audit status |
| --- | --- | --- | --- | --- |
| SOC 2 | Strong (see crosswalk) | **Approved v1.0** | Procedures approved; operationalization in progress | Not started — readiness phase |
| ISO 27001 | Strong | **Approved v1.0** (SoA, policies, register, procedures) | Procedures approved; operationalization in progress | Not started — readiness phase |
| ISO 42001 | Strong / differentiated (model-card export, governed retirement, continuous fairness monitoring all implemented) | **Approved v1.0** (SoA, AI policy, procedures) | Procedures approved; AI build gaps closed | Not started — readiness phase |

The documentation set was **approved v1.0, effective 2026-06-24** (Christopher
Day), at the [first management review](evidence/2026-06-24-management-review.md),
informed by the [first internal audit](evidence/2026-Q2-internal-audit-report.md).
What remains is **operating** the approved [procedures](procedures/README.md) to
produce evidence and (for SOC 2 Type II / ISO certifications) an operating window
before an external auditor is engaged — see the open action items in the
management review.

## Recommended sequence

1. ~~**Approve** the policy set (POL-01…POL-12) and the operational procedures —
   assign owners, set effective dates, run the first management review.~~ **Done
   2026-06-24** — approved v1.0; see the
   [management review](evidence/2026-06-24-management-review.md) and
   [internal audit](evidence/2026-Q2-internal-audit-report.md).
2. **Operate the Process procedures** (now drafted) to generate evidence: change
   management ([PROC-03](procedures/change-management-procedure.md)), vendor
   management ([PROC-07](procedures/vendor-management-procedure.md)), incident
   response ([PROC-01](procedures/incident-response-runbook.md)), HR security
   ([PROC-06](procedures/hr-security-procedures.md)), risk review
   ([PROC-04](procedures/risk-assessment-and-review-procedure.md)) + internal
   audit ([PROC-05](procedures/internal-audit-plan.md)), and vulnerability
   management ([PROC-02](procedures/vulnerability-management-procedure.md)).
3. **Enable the opt-in technical controls** for compliant deployments — apply
   [`deployment/compliant-config.toml`](deployment/compliant-config.toml) and
   verify with [`deployment/verify-posture.sh`](deployment/verify-posture.sh)
   (see also [`soc2/README.md`](soc2/README.md)).
4. **SOC 2 Type I**, then run the observation window → **Type II**.
5. **ISO 27001** certification (Stage 1 + Stage 2 audit).
6. **ISO 42001** stacked on the certified ISMS.
