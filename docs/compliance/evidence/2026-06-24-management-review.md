# Management Review — 2026-06-24 (Review 1)

| Field | Value |
| --- | --- |
| Document ID | MR-2026-06-24-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — prepared for conduct & ratification by management |
| Template | [TPL-02 Management Review Minutes](../templates/management-review-minutes-template.md) |
| Clause | ISO 27001 / ISO 42001 Clause 9.3 |

> **Nature of this record.** These minutes are **pre-filled from the current
> state of the ISMS/AIMS** so the first management review (Clause 9.3) can be
> conducted and ratified efficiently. Items in _[brackets]_ are decisions for the
> reviewer to confirm. Conducting and signing the review is management's act.

## Attendees

| Name | Role | Present |
| --- | --- | --- |
| Christopher Day | ISMS/AIMS Owner, Management (all functional roles) | ☐ |

(Solo operation — see the [program ownership note](../README.md).)

## Standing agenda — inputs (Clause 9.3.2)

### a. Status of actions from previous reviews
None — this is Review 1.

### b. Changes in internal/external issues
- New ISMS/AIMS established: full policy set (POL-01…12), risk methodology +
  register, two Statements of Applicability, 7 procedures, 5 registers, 4
  templates, and a hardened deployment profile.
- External driver: SOC 2 / ISO 27001 / ISO 42001 sought for enterprise sales;
  ISO 42001 increasingly expected of AI vendors.

### c. ISMS/AIMS performance
- **Incidents:** none recorded this period.
- **Internal audit results:** [IA-2026Q2-01](2026-Q2-internal-audit-report.md) —
  3 Minor NCs, 3 Observations, no Major NCs. Technical design conforms; NCs are
  operational (enable opt-in controls; approve docs; schedule pen test).
- **Risk status:** [risk register](../risk-register.md) — 0 Critical, 1 High
  residual (R-01 sandbox escape), 15 Medium, 6 Low; R-22/R-24/R-25 **Closed**
  (AI build gaps implemented this period).
- **Control posture (`maverick soc2`):** opt-in controls `disabled` on the
  default profile; `encryption_at_rest`/`data_subject_export` enabled. Hardening
  required before audit (NC-01/NC-02).
- **Objectives progress:** technical/AI build objectives met; "all opt-in controls
  enabled in production" and "policies approved" outstanding.

### d. Feedback from interested parties
None formally received this period.

### e. Results of risk assessment & treatment status
Register reviewed; appetite (no unaccepted High/Critical residual) holds except
R-01, targeted by the planned pen test. AI build-gap risks closed.

### f. Opportunities for continual improvement
Enable opt-in controls by default in a "compliance profile"; wire `maverick soc2`
into CI as a posture gate; schedule recurring fairness-monitor reporting.

## Outputs — decisions (Clause 9.3.3)

| # | Decision | Status |
| --- | --- | --- |
| D-1 | _[Approve POL-01…12 + all procedures; set effective date 2026-06-24]_ | ☐ |
| D-2 | _[Accept the risk register and the R-01 treatment plan (pen test)]_ | ☐ |
| D-3 | _[Approve enabling the opt-in controls on production via `compliant-config.toml`]_ | ☐ |
| D-4 | _[Schedule the first third-party penetration test for <date>]_ | ☐ |
| D-5 | _[Adopt quarterly internal audit + quarterly management review cadence]_ | ☐ |
| D-6 | _[Resourcing: no additional resource required this cycle / TBD]_ | ☐ |

## Action items

| ID | Action | Owner | Due |
| --- | --- | --- | --- |
| A-1 | Approve documentation set; set effective dates | Christopher Day | <date> |
| A-2 | Apply `compliant-config.toml`; verify `maverick soc2` all-`enabled`/`ok` (NC-01/NC-02) | Christopher Day | <date> |
| A-3 | Schedule third-party penetration test (OBS-01 / R-01) | Christopher Day | <date> |
| A-4 | Configure governance human-oversight gates on production (OBS-03) | Christopher Day | <date> |
| A-5 | Engage SOC 2 assessor; begin Type II observation window | Christopher Day | <date> |

Action items are tracked in the [Corrective Action Log](../registers/corrective-action-log.md).

**Next review:** 2026-Q3 (quarterly cadence).
