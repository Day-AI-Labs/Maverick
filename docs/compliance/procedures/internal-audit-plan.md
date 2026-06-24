# Internal Audit Plan & Programme

| Field | Value |
| --- | --- |
| Document ID | PROC-05 |
| Owner | Security Lead / ISMS Manager |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | ISO/IEC 27001:2022 Cl. 9.2; ISO/IEC 42001:2023 Cl. 9.2; SOC 2 CC4.1 |

This document defines the internal audit programme of the Organization
(Maverick) required by ISO 27001 / ISO 42001 **Clause 9.2**. It establishes the
annual plan, audit scope, auditor independence, the audit checklist, the
classification of findings, and how findings flow into corrective action. It
audits the management system against the two Statements of Applicability
([ISO 27001](../iso-27001/statement-of-applicability.md),
[ISO 42001](../iso-42001/statement-of-applicability.md)) and the
[policy set](../policies/).

## 1. Programme objectives

The internal audit programme provides assurance that:

1. The ISMS/AIMS conforms to the requirements of ISO 27001, ISO 42001, the SOC 2
   Trust Services Criteria, and the Organization's own policies.
2. The ISMS/AIMS is **effectively implemented and maintained** — controls listed
   as Implemented in the SoAs are operating as described.
3. Nonconformities are identified, classified, and driven to closure via the
   [Corrective Action Log](../registers/corrective-action-log.md) (REG-03).

## 2. Annual audit plan

- **Cycle length:** 12 months, aligned to the certification/audit year.
- **Coverage rule:** every Annex A control (ISO 27001: 93 controls; ISO 42001:
  Annex A controls) is audited **at least once per certification cycle**. Each
  internal audit window samples a **risk-prioritized subset** so that, summed
  across the year, full coverage is achieved.
- **Risk prioritization:** controls mitigating risks scored residual ≥ 9 in the
  [Risk Register](../risk-register.md) (e.g. R-01 sandbox, R-02 prompt injection,
  R-03 secret exfiltration, R-05 audit-log integrity, R-06 access control) are
  audited **every cycle**; lower-residual controls rotate.
- **Frequency:** a minimum of **two internal audit windows per year** (mid-year
  + pre-management-review), plus ad-hoc audits triggered by a major incident or
  significant change (see PROC-04 §3).
- **Inputs to planning:** prior audit results, open items in REG-03, the latest
  `maverick soc2` control-posture report, and the current risk register.

## 3. Scope per cycle

Each audit window selects a scope sheet naming:

- The **control areas** in scope (mapped to SoA control IDs).
- The **systems / repos / evidence stores** to be inspected.
- The **owners** to be interviewed.
- The **sampling basis** (e.g. "5 of the last 20 production changes").

A single window does **not** attempt all 93+ controls; it takes a defensible
sample, and the annual plan guarantees union coverage.

## 4. Auditor independence

- Auditors **must not audit their own work.** The owner/implementer of a control
  cannot be the auditor for that control area.
- Internal audits are coordinated by the ISMS Manager but **executed by an
  independent reviewer** — a different team member, a rotated peer, or an
  external contractor. Where the ISMS Manager owns a control, an alternate
  auditor is assigned.
- Auditor independence and objectivity are recorded on each audit's cover sheet
  and confirmed in the [Management Review](../templates/management-review-minutes-template.md).

## 5. Internal-audit checklist

For each control area the auditor records the evidence inspected and a verdict
(**Pass** / **Fail** / **Observation**, see §6). Sample checklist:

| # | Control area (SoA ref) | Evidence to inspect | Verdict |
| --- | --- | --- | --- |
| 1 | Access control & RBAC (A.5.15–A.5.18, A.8.2–A.8.5) | OIDC/SAML config; RBAC role definitions (`rbac.py`); capability grants (`capability.py`); sample of access reviews | |
| 2 | Cryptography & secrets (A.8.24; POL-04) | At-rest encryption enabled (`crypto_at_rest.py`); secret scrubber config (`maverick/secrets.py`); detect-secrets CI gate run logs | |
| 3 | Audit logging & integrity (A.8.15–A.8.16; R-05) | Ed25519 hash-chain enabled; chain-verification output (`maverick/audit/signing.py`); WORM retention evidence | |
| 4 | Sandbox / isolation (R-01) | Container backend flags (`--network=none`, `--cap-drop=ALL`); `require_container` policy; CI grep for `shell=True` violations | |
| 5 | Change management (A.8.32; POL-05) | Sample of merged PRs: review approval, CI gates green, change-management policy adherence | |
| 6 | Vulnerability & dependency mgmt (R-10; A.8.8) | Dependabot alerts triage; CI gate logs; remediation SLAs | |
| 7 | Incident response (A.5.24–A.5.27; POL-07) | Sample incident records: detection, classification, post-mortem, CAPA linkage | |
| 8 | Budget / resource controls (R-11) | Budget caps configured (`budget.py`); per-principal quotas (`quotas.py`); killswitch test | |
| 9 | AI human oversight (ISO 42001 A.9; POL-12) | `REQUIRE_HUMAN` scope; sample of human-approval gates exercised | |
| 10 | AI impact assessment (ISO 42001 A.6; methodology §6) | Completed `AIRA-NN` records for capabilities shipped this cycle; EU AI-Act classification (`maverick/ai_act.py`) | |
| 11 | AI data provenance & fairness (ISO 42001 A.7) | Fleet-memory provenance records; bias-eval output (`maverick/tools/bias_eval.py`) | |
| 12 | Risk management operation (Cl. 6.1; PROC-04) | Evidence quarterly reviews ran; register version history; CAPA closures | |
| 13 | Supplier / MCP-plugin security (A.5.19–A.5.22; POL-09; R-08) | Plugin allowlist + hash-pin (`plugin_manifest.py`); supplier review records | |
| 14 | Management review operation (Cl. 9.3) | Prior review minutes (TPL-02): required inputs present, outputs/actions tracked | |

The auditor attaches the populated checklist (with evidence references and
verdicts) to the audit record.

## 6. Nonconformity classification

| Class | Definition | Action |
| --- | --- | --- |
| **Major** | Total breakdown of a required control, or a nonconformity that puts certification or data at material risk (e.g. a control marked Implemented in the SoA is absent, or audit-log integrity is off in production). | CAPA opened immediately; flagged to management; may halt the affected activity. |
| **Minor** | A single or isolated lapse in an otherwise functioning control (e.g. one change merged without the required reviewer). | CAPA opened with a standard due date. |
| **Observation** | No nonconformity, but an improvement opportunity or early-warning signal. | Logged; may become an opportunity-for-improvement at management review. |

## 7. Flow of findings to corrective action

1. Each **Major** and **Minor** finding is recorded as a row in the
   [Corrective Action Log](../registers/corrective-action-log.md) (REG-03) with
   source = `audit`, capturing the nonconformity, root cause, correction, and
   corrective action.
2. The auditor assigns a finding ID and references it from the audit record; the
   control owner is the CAPA owner.
3. **Observations** are tracked in the audit record and surfaced to the
   [Management Review](../templates/management-review-minutes-template.md) (TPL-02)
   as opportunities for improvement.
4. Effectiveness of each corrective action is **verified** at follow-up (next
   audit window or the verification date in REG-03) before the finding is closed
   — satisfying Clause 10.1.
5. Audit results (counts by class, closure rate) are a standing input to the
   management review (Clause 9.3).

## 8. Sample annual audit schedule

| Window | Month | Control areas in scope (checklist rows) | Auditor | Output |
| --- | --- | --- | --- | --- |
| A1 (mid-year) | June | High-residual security set: 1, 2, 3, 4, 6, 8 + change mgmt (5) | Independent reviewer (rotated) | Checklist + findings → REG-03 |
| A2 (pre-review) | November | AI set: 9, 10, 11 + incident (7), supplier (13), risk/mgmt-system ops (12, 14) | Independent reviewer / external contractor | Checklist + findings → REG-03 |
| Ad-hoc | On trigger | Scope limited to the incident/change (PROC-04 §3) | Independent of the change owner | Targeted findings → REG-03 |

Across A1 + A2 the cycle achieves full SoA coverage; every-cycle high-residual
controls (rows 1–4) appear in A1, and AI-specific controls appear in A2.
