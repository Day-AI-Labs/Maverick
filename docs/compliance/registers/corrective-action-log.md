# Corrective Action Log (CAPA Register)

| Field | Value |
| --- | --- |
| Document ID | REG-03 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | ISO/IEC 27001:2022 Cl. 10.1, 10.2; ISO/IEC 42001:2023 Cl. 10.1, 10.2; SOC 2 CC4.2 |

This is the consolidated corrective-action (CAPA) register of the Organization
(Maverick), satisfying ISO 27001 / ISO 42001 **Clause 10.1** (nonconformity and
corrective action). It is the single destination for nonconformities raised by
internal audit ([PROC-05](../procedures/internal-audit-plan.md)), incidents
(POL-07), the risk process ([PROC-04](../procedures/risk-assessment-and-review-procedure.md)),
and management review ([TPL-02](../templates/management-review-minutes-template.md)).

## How to use this register

1. **Open** a row whenever a nonconformity is identified. Set **Source** to the
   originating process (`audit` / `incident` / `risk` / `review`).
2. **Describe** the nonconformity factually (what was expected vs. observed).
3. **Correction** = the immediate fix / containment. **Corrective action** = the
   action that removes the *root cause* so it does not recur (Clause 10.1 b–d).
   Record the **root cause** explicitly — do not skip to the fix.
4. **Owner** and **Due date** are mandatory on open. Status flows
   `Open → In progress → Pending verification → Closed`.
5. **Verification of effectiveness** is mandatory before **Closed**: confirm, at
   or after the due date, that the corrective action worked and the
   nonconformity has not recurred. Record what was checked and by whom.
6. Major/Minor classification follows PROC-05 §6. Each row links back to its
   source record (audit finding ID, incident ID, risk ID, or review action ID).
7. The register is reviewed every quarter (PROC-04) and reported at each
   management review (TPL-02). Closure rate is a tracked ISMS/AIMS metric.

## Register

| ID | Source | Class | Nonconformity description | Root cause | Correction (immediate) | Corrective action (root-cause) | Owner | Due date | Status | Verification of effectiveness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CA-EX-01 _(EXAMPLE — delete)_ | audit (PROC-05, finding A1-04) | Minor | One production change merged to the release branch without the required second reviewer, contrary to POL-05. | Branch-protection rule allowed self-approval for one repo; reviewer-required gate not enforced on that repo. | Reverted/re-reviewed the change retroactively; reviewer confirmed no issue. | Enabled mandatory-reviewer + block-self-approval branch protection across all repos; added CI check; updated change-management runbook. | Engineering Lead | 2026-07-31 | Pending verification | At next audit window, sample 10 merges and confirm 100% had an independent reviewer. _(to be completed)_ |
| CA-EX-02 _(EXAMPLE — delete)_ | incident (POL-07, INC-2026-014, Sev-2) | Major | At-rest encryption (`crypto_at_rest.py`) was disabled in a staging tenant holding production-like data, contrary to the SoA (A.8.24) and R-07 treatment. | Encryption defaults to opt-in; environment provisioning template omitted the enable flag; no startup guard alerted on the gap. | Enabled at-rest encryption on the affected tenant; rotated exposed data keys; scoped impact (no external disclosure). | Made encryption-enabled a deployment precondition (`maverick doctor` hard fail when off for non-dev tenants); added the flag to the installer wizard step; updated R-07 in the register. | Security Lead | 2026-07-15 | Closed | Verified 2026-07-18: re-ran provisioning on a fresh tenant; `maverick doctor` blocked startup until encryption enabled; confirmed across all non-dev tenants. No recurrence at the Q3 review. |
| | | | | | | | | | | |
| | | | | | | | | | | |

> Rows prefixed `CA-EX-` are **illustrative examples** showing the expected level
> of detail; delete them before the register goes live. Real entries are numbered
> sequentially `CA-NN`.
