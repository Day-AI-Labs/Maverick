# Operational Procedures, Registers & Templates

This is the **operational layer** of the compliance program — the runbooks,
registers, templates, and deployment artifacts that turn the
[policies](../policies/) into things you actually *do*. Where a policy says
*what* and *why*, these say *how, who, and when*.

Most of what remains for SOC 2 / ISO 27001 / ISO 42001 is operating these
procedures and recording the evidence; the items that require real-world
execution (background checks, signing DPAs, engaging an external assessor) are
marked **[Org action]** inside each document.

## Procedures (`procedures/`)

| ID | Procedure | Operationalizes | Frameworks |
| --- | --- | --- | --- |
| PROC-01 | [Incident Response Runbook](incident-response-runbook.md) | POL-07 | ISO 27001 A.5.24–28; ISO 42001 A.10; SOC 2 CC7.3/7.4 |
| PROC-02 | [Vulnerability Management Procedure](vulnerability-management-procedure.md) | POL-06 | ISO 27001 A.8.8; SOC 2 CC7.1 |
| PROC-03 | [Change Management Procedure](change-management-procedure.md) | POL-05 | ISO 27001 A.8.31/8.32; ISO 42001 A.6.2; SOC 2 CC8.1 |
| PROC-04 | [Risk Assessment & Review Procedure](risk-assessment-and-review-procedure.md) | POL-02 | ISO 27001/42001 Cl. 6.1, 9.3, 10; SOC 2 CC3/CC4 |
| PROC-05 | [Internal Audit Plan](internal-audit-plan.md) | ISMS/AIMS Cl. 9.2 | ISO 27001/42001 Cl. 9.2 |
| PROC-06 | [HR Security Procedures](hr-security-procedures.md) | POL-10 | ISO 27001 A.6.1–6.6; ISO 42001 A.3.2/A.4.6; SOC 2 CC1.4 |
| PROC-07 | [Vendor Management Procedure](vendor-management-procedure.md) | POL-09 | ISO 27001 A.5.19–23; ISO 42001 A.10; SOC 2 CC9.2 |

## Registers (`registers/`)

| ID | Register | Purpose |
| --- | --- | --- |
| REG-01 | [Sub-processor Register](../registers/subprocessor-register.md) | Third parties processing customer data (per deployment) |
| REG-02 | [Remediation Tracker](../registers/remediation-tracker.md) | Vulnerability/finding remediation with SLAs |
| REG-03 | [Corrective Action Log (CAPA)](../registers/corrective-action-log.md) | Nonconformities + corrective actions (Cl. 10.1) |
| REG-04 | [Vendor Register](../registers/vendor-register.md) | Vendor risk tiers, DPA status, review cadence |
| REG-05 | [Asset Inventory](../registers/asset-inventory.md) | Information assets, classification, owners (A.5.9) |

Plus the [Risk Register](../risk-register.md) (RM-REG-01).

## Templates (`templates/`)

| ID | Template | Used by |
| --- | --- | --- |
| TPL-01 | [Incident Report](../templates/incident-report-template.md) | PROC-01 |
| TPL-02 | [Management Review Minutes](../templates/management-review-minutes-template.md) | PROC-04 (Cl. 9.3) |
| TPL-03 | [Acceptable Use Policy](../templates/acceptable-use-policy.md) | PROC-06 |
| TPL-04 | [Vendor Security Questionnaire](../templates/vendor-security-questionnaire.md) | PROC-07 |

## Deployment (`deployment/`)

The technical "enable the opt-in controls" step — operationalized:

| Artifact | Purpose |
| --- | --- |
| [`compliant-config.toml`](../deployment/compliant-config.toml) | Hardened reference `config.toml` with every required control ON |
| [`hardening-checklist.md`](../deployment/hardening-checklist.md) | Pre/post-deploy checklist + evidence keys (`maverick soc2`) |
| [`verify-posture.sh`](../deployment/verify-posture.sh) | Runs `maverick soc2` + `enterprise verify` + `compliance --strict` as a deploy gate |

## Evidence (`evidence/`)

Dated records produced by *operating* the procedures (Clause 9.2/9.3 outputs and
posture snapshots) — see the [evidence index](../evidence/README.md). Initial
records: the [2026-Q2 internal audit](../evidence/2026-Q2-internal-audit-report.md)
and the [first management review](../evidence/2026-06-24-management-review.md).

## How it fits together

```
Policies (what/why)  →  Procedures (how/who/when)  →  Registers (live records)
                                  │
                                  └→  Templates (fill-in artifacts)  +  Deployment (technical enablement)
                                                   │
                                          Evidence for the SOC 2 / ISO audits
```

See the program [README](../README.md) and the
[control crosswalk](../control-crosswalk.md) for the framework mapping.
