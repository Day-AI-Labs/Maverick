# Remediation Tracker

| Field | Value |
| --- | --- |
| Document ID | REG-02 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Review cycle | Annual |
| Frameworks | SOC 2 CC7.1; ISO/IEC 27001:2022 A.8.8; Secure Development Policy (POL-06) |

## How to use

This is the single register of technical vulnerabilities and security findings
for Maverick, operated under the
[Vulnerability Management Procedure (`PROC-02`)](../procedures/vulnerability-management-procedure.md).

- **One row per finding.** Add a row at intake from any source (Dependabot, CI,
  pen-test, external report). Never delete rows — closed findings are audit
  evidence.
- **Set the SLA due date at triage** = triage/confirmation date + the SLA for
  the assigned severity (Critical 7d / High 30d / Medium 90d / Low best-effort,
  per `PROC-02` §3).
- **Status values:** `open` → `in-progress` → `remediated` _or_ `accepted`.
  Use `accepted` only with Management approval and a Risk Register cross-
  reference (e.g. `R-10`); record a time-boxed re-review date.
- **Verification is mandatory before `remediated`** — record the method (re-run
  scan, confirm fixed version, re-test surface) and date in the Verification
  column.
- **ID format:** `VLN-NNNN`, sequential, never reused.
- Findings accepted as risk are mirrored in the
  [Risk Register](../risk-register.md); SLA breaches are escalated to Management
  per `PROC-02` §3.

## Severity / SLA quick reference

| Severity | CVSS band | SLA |
| --- | --- | --- |
| Critical | 9.0–10.0 | 7 days |
| High | 7.0–8.9 | 30 days |
| Medium | 4.0–6.9 | 90 days |
| Low | 0.1–3.9 | Best-effort (≤180d) |

## Register

> The three rows below are **ILLUSTRATIVE EXAMPLES** to show how the register is
> populated. Delete them before the register goes live, or mark them clearly as
> seed data.

| ID | Source | Description | CVSS / Severity | Affected component | Discovered | SLA due | Owner | Status | Verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VLN-0001 _(example)_ | dependabot | Vulnerable transitive dependency flagged by weekly Dependabot PR; upgrade available | 7.5 / High | `packages/maverick-core` (pip) | 2026-06-10 | 2026-07-10 | Eng — Core | in-progress | Pending — confirm fixed version + green CI on upgrade PR |
| VLN-0002 _(example)_ | CI (detect-secrets) | New secret-like hash introduced in a PR diff, failed the `detect-secrets` gate vs `.secrets.baseline` | 9.1 / Critical | `apps/installer-cli` | 2026-06-18 | 2026-06-25 | Security Lead | remediated | Secret rotated; commit history scrubbed; baseline re-verified clean in CI on 2026-06-20 |
| VLN-0003 _(example)_ | pen-test | SSRF reachable to internal host when `MAVERICK_FETCH_ALLOW_PRIVATE=1` set in a misconfigured deployment | 5.4 / Medium | `maverick/tools/_ssrf.py` | 2026-05-02 | 2026-07-31 | Security Lead | accepted | Accepted as low residual — compensating control (default-on private-IP block); linked to Risk Register **R-04**; re-review 2026-12-31 |

## Open-items summary (maintained at each quarterly review)

| Severity | Open | In-progress | Past SLA |
| --- | --- | --- | --- |
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 0 | 0 | 0 |
| Low | 0 | 0 | 0 |

_Counts exclude the illustrative example rows above. Update this summary during
the quarterly full review (`PROC-02` §5)._
