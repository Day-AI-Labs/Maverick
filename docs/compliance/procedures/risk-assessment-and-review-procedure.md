# Risk Assessment & Review Procedure

| Field | Value |
| --- | --- |
| Document ID | PROC-04 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Review cycle | Annual |
| Frameworks | ISO/IEC 27001:2022 Cl. 6.1, 8.2, 8.3, 9.1, 10.1; ISO/IEC 42001:2023 Cl. 6.1, 8.2–8.4, 10.1; SOC 2 CC3.1–CC3.4, CC4.1–CC4.2 |

This procedure defines the **operating cadence** by which the Organization
(Maverick) keeps its risk picture current. It operationalizes the
[Risk Management Methodology](../risk-management-methodology.md) (RM-METH-01) and
the [Risk Management Policy](../policies/risk-management-policy.md) (POL-02), and
keeps the [Risk Register](../risk-register.md) (RM-REG-01) live. Its outputs feed
the [Internal Audit Plan](internal-audit-plan.md) (PROC-05), the
[Management Review](../templates/management-review-minutes-template.md) (TPL-02),
and the [Corrective Action Log](../registers/corrective-action-log.md) (REG-03).

This procedure does **not** redefine scoring, treatment options, or risk
appetite — those live in the methodology. It defines **who does what, when, with
what inputs, producing what outputs.**

## 1. Roles

| Role | Responsibility in this procedure |
| --- | --- |
| Security Lead / ISMS Manager | Owns the register and the cadence; chairs the quarterly review; signs off treatment changes. |
| AI / Responsible-AI Lead | Owns AI risks (R-19…R-25) and AI system impact assessments (AIRA). |
| Engineering Lead | Owns engineering/availability risks; raises change-triggered re-assessments. |
| Risk owners (named in register) | Maintain the status of their own risks; execute treatments. |
| Management | Approves residual-risk acceptance above appetite; provides resources (Cl. 9.3). |

## 2. Quarterly risk-register review

The standing control loop. Cadence: **once per calendar quarter** (target: second
week of Jan / Apr / Jul / Oct).

**Chaired by:** Security Lead / ISMS Manager.
**Attendees:** AI Lead, Engineering Lead, named risk owners.

**Inputs (gathered before the meeting):**

- Current [Risk Register](../risk-register.md) (all `R-NN` and `AIRA-NN` entries).
- New entries from the identification sources in methodology §2 (STRIDE threat
  model, pen-test readiness scope, SOC 2 control gaps, Dependabot/CI alerts,
  AI-Act classifier output).
- Open items in the [Corrective Action Log](../registers/corrective-action-log.md).
- Control-posture report: `maverick soc2` (automated control/evidence status).
- Incidents closed since the last review (POL-07 records).
- Any trigger-based re-assessments completed during the quarter (§3).

**Activities:**

1. Walk every open risk; confirm or adjust Likelihood × Impact per the
   methodology scale.
2. Re-confirm residual score vs. risk appetite; flag any residual now above
   appetite for management acceptance.
3. Confirm treatment progress; close treatments that are complete and verified.
4. Add newly identified risks; assign an ID, owner, and initial score.
5. Reconcile against the two SoAs
   ([ISO 27001](../iso-27001/statement-of-applicability.md),
   [ISO 42001](../iso-42001/statement-of-applicability.md)) — a control whose
   status regressed becomes a register/CAPA item.

**Outputs:**

- Updated, version-bumped [Risk Register](../risk-register.md).
- New/updated rows in the [Corrective Action Log](../registers/corrective-action-log.md)
  for every treatment gap (source = `risk`).
- Residual-risk-acceptance list for the next management review (TPL-02).
- A one-paragraph quarterly risk summary attached to the review record.

## 3. Trigger-based re-assessment

Independent of the quarterly cycle, a **targeted** re-assessment is performed
within the SLA below whenever a trigger fires. The risk owner runs it; the
Security Lead records the outcome in the register.

| Trigger | SLA to complete | Mandatory AIRA? |
| --- | --- | --- |
| **New AI capability / specialist pack or material model change** | 10 business days, before production enablement | Yes — see §5 |
| **New deployment context** (new tenant class, new data category, new jurisdiction) | 10 business days | Yes |
| **Security incident** (any POL-07 incident at Sev-2 or above) | 5 business days after incident closure | If AI-behavioral |
| **Major change** (new external integration, MCP/plugin, auth/sandbox change) | Before merge to release branch | If it alters AI autonomy or oversight |
| **New/changed regulation or contractual obligation** | 20 business days | If AI-Act relevant |
| **Significant vulnerability** (critical CVE in a runtime dependency) | 5 business days | No |
| **Failed control** discovered by audit (PROC-05) or monitoring | Per CAPA due date (REG-03) | As applicable |

A trigger-based re-assessment reuses the methodology scoring and produces the
same register/CAPA outputs as §2, scoped to the affected risks only.

## 4. Annual full risk assessment

Once per year (target: **Q1, ahead of the annual management review**) the
Security Lead runs a **complete** re-assessment, not just a delta review.

**Inputs:** all methodology §2 sources refreshed; the full prior-year register;
all SoA control statuses; all closed CAPA items; external audit / pen-test
results if available; the threat model and AI-Act classification refreshed.

**Activities:**

1. Re-derive the asset and threat inventory from the STRIDE model.
2. Re-score **every** risk from inherent → residual (do not carry forward
   stale scores).
3. Re-confirm the completeness of the register against both SoAs (no Annex A /
   Annex A AI control should map to zero risks without justification).
4. Re-validate risk appetite and acceptance decisions with management.
5. Produce the annual risk-assessment report as a primary input to the
   [Management Review](../templates/management-review-minutes-template.md).

**Output:** version-bumped register, annual risk-assessment report, and the
refreshed residual-risk-acceptance set for management sign-off.

## 5. AI system impact assessment (AIRA) scheduling

AIRAs are defined in methodology §6 and recorded as `AIRA-NN` entries
cross-referenced from the register. This procedure sets **when** they run:

- **On trigger** — every new materially-new AI capability or new deployment
  context (see the §3 table) requires a completed AIRA **before** production
  enablement. No AIRA → the capability does not ship.
- **On significant model/learning change** — any change to the learning loop
  inputs (fleet-memory provenance), human-oversight design (`REQUIRE_HUMAN`
  scope), or fairness posture re-runs the relevant AIRA section.
- **Annual refresh** — all live `AIRA-NN` entries are reviewed in the annual
  full assessment (§4) for continued validity of purpose, affected parties,
  EU AI Act classification, oversight design, data provenance, fairness, and
  transparency obligations (methodology §6 bullet list).

Each AIRA references the EU AI Act classification produced by
`maverick/ai_act.py` / `maverick/tools/ai_act_classifier.py` and is owned by the
AI / Responsible-AI Lead.

## 6. Calendar of activities

| Activity | Frequency | Owner | Primary output |
| --- | --- | --- | --- |
| Quarterly risk-register review | Quarterly (Jan/Apr/Jul/Oct) | Security Lead / ISMS Manager | Updated register + CAPA rows + quarterly summary |
| Trigger-based re-assessment | On trigger (SLA per §3) | Risk owner | Updated affected register entries |
| New-capability AIRA | Before each production enablement | AI / Responsible-AI Lead | `AIRA-NN` entry + go/no-go |
| Control-posture pull (`maverick soc2`) | Quarterly (+ ad hoc) | Security Lead | Control/evidence status snapshot |
| Annual full risk assessment | Annual (Q1) | Security Lead / ISMS Manager | Annual risk-assessment report + re-scored register |
| AIRA annual refresh | Annual (within full assessment) | AI / Responsible-AI Lead | Revalidated `AIRA-NN` entries |
| Residual-risk acceptance review | Annual + as flagged | Management | Signed acceptance decisions |
| Register reconciliation vs. SoAs | Quarterly + annual | Security Lead | Coverage confirmation / gap CAPA items |

## 7. Tie to continual improvement (Clause 10)

This cadence is the Check-and-Act half of the ISMS/AIMS PDCA loop:

- Every gap surfaced by a review or re-assessment is logged in the
  [Corrective Action Log](../registers/corrective-action-log.md) (REG-03) with a
  source of `risk` and driven to closure under Clause 10.1.
- Recurring or systemic findings (e.g. the same control regressing across
  quarters) are escalated as **opportunities for improvement** into the
  [Management Review](../templates/management-review-minutes-template.md) (TPL-02),
  where decisions on changes and resources are recorded (Clause 9.3 / 10.1).
- Effectiveness of treatments and corrective actions is verified at the next
  quarterly review and confirmed-closed in REG-03 before a risk's residual score
  is lowered — closing the loop from identification to verified improvement.
