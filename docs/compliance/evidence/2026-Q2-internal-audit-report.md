# Internal Audit Report — 2026-Q2 (Cycle 1)

| Field | Value |
| --- | --- |
| Document ID | IA-2026Q2-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Reviewed & accepted 2026-06-24 (Christopher Day) |
| Audit date | 2026-06-24 |
| Procedure | [PROC-05 Internal Audit Plan](../procedures/internal-audit-plan.md) |

> **Nature of this record.** This is the **first internal audit** (ISO 27001 /
> ISO 42001 Clause 9.2) for the Maverick ISMS/AIMS. It was conducted by
> inspecting the codebase and configuration against the
> [Statement of Applicability](../iso-27001/statement-of-applicability.md) and
> capturing the live technical posture. Findings feed the
> [Corrective Action Log](../registers/corrective-action-log.md) and the first
> [Management Review](2026-06-24-management-review.md). Auditor independence note:
> for a solo operation, independence is partially compensated by the objective,
> tool-generated posture snapshot (§2) and external-assessor review at
> certification.

## 1. Scope & method

- **Scope:** a sample of ISO 27001:2022 Annex A controls across access control,
  cryptography, logging, operations, and the management-system clauses, plus the
  ISO 42001 AI-specific controls.
- **Method:** documentary review (policies/procedures/SoA), code inspection, and
  an objective posture snapshot from `maverick soc2` (the evidence collector).
- **Result classes:** Conforms · Observation · Minor NC · Major NC.

## 2. Objective posture snapshot (evidence)

`maverick soc2` output captured on the assessed environment (default profile —
**not** a hardened deployment):

```json
{
  "controls": {
    "capability_enforcement": {"status": "disabled"},
    "tenant_isolation":       {"status": "disabled"},
    "usage_quotas":           {"status": "disabled"},
    "oidc_auth":              {"status": "disabled"},
    "encryption_at_rest":     {"status": "enabled"},
    "data_subject_export":    {"status": "enabled"}
  },
  "audit_log":         {"status": "empty"},
  "audit_signing_key": {"status": "absent"}
}
```

This snapshot is itself the evidence for finding **NC-01**: the opt-in controls
are off on a default profile and must be enabled for a compliant deployment.

## 3. Control findings (sample)

| Control | Expected | Evidence inspected | Result |
| --- | --- | --- | --- |
| A.5.15/A.8.2–3 Access control | Capabilities + RBAC enforced | `capability.py`, `rbac.py` present & implemented; **`capability_enforcement: disabled`** in snapshot | Minor NC (NC-01) |
| A.8.5 Secure authentication | OIDC enforced | `oidc.py` present; **`oidc_auth: disabled`** | Minor NC (NC-01) |
| A.8.24 Cryptography | Encryption at rest + signed audit | `encryption_at_rest: enabled` ✓; **`audit_log: empty`, signing key absent** | Minor NC (NC-02) |
| A.8.15 Logging | Tamper-evident audit log | `maverick/audit/` implemented; chain verifiable; not yet signed on this env | Minor NC (NC-02) |
| C1.1 Tenant isolation | Per-user isolation | `paths.py` present; **`tenant_isolation: disabled`** | Minor NC (NC-01) |
| A.5.34/P5 Privacy | DSAR + erasure | `dsar.py`, `audit/erase.py` present; `data_subject_export: enabled` ✓ | Conforms |
| A.5.1 Policies | Approved policy set | POL-01…12 authored, **Status = Draft (not yet approved)** | Minor NC (NC-03) |
| A.5.35 Independent review | Pen test / internal audit | This audit performed ✓; **third-party pen test not scheduled** (R-01 High) | Observation (OBS-01) |
| 9.3 Management review | Review held | First review prepared, **not yet conducted** | Observation (OBS-02) |
| ISO 42001 A.6.2.6 Fairness monitoring | Continuous monitoring | `fairness_monitor.py` implemented ✓ | Conforms |
| ISO 42001 A.6.2 Retirement | Governed retirement | `retirement.py` + `AI_SYSTEM_RETIRED` ✓ | Conforms |
| ISO 42001 A.9.2 Human oversight | REQUIRE_HUMAN gate | `governance.py`, `consent.py` present; not yet configured on this env | Observation (OBS-03) |

## 4. Findings & nonconformities → CAPA

| ID | Class | Finding | Corrective action | Owner |
| --- | --- | --- | --- | --- |
| NC-01 | Minor NC | Opt-in access controls (capabilities, tenant isolation, quotas, OIDC) `disabled` on the assessed profile | Apply [`compliant-config.toml`](../deployment/compliant-config.toml); re-verify with [`verify-posture.sh`](../deployment/verify-posture.sh) until all `enabled` | Christopher Day |
| NC-02 | Minor NC | Audit log unsigned / no signing key on the assessed profile | Enable `[audit] sign = true`; confirm `audit_log = ok` + signing key present | Christopher Day |
| NC-03 | Minor NC | Policy & procedure set is Draft, not management-approved | **Closed 2026-06-24** — POL-01…12 + procedures/registers/templates approved (v1.0, effective 2026-06-24) at the first management review | Christopher Day |
| OBS-01 | Observation | Third-party penetration test not yet scheduled (R-01 sandbox escape is the single High residual) | Schedule annual third-party pen test per [PROC-02](../procedures/vulnerability-management-procedure.md) | Christopher Day |
| OBS-02 | Observation | First management review not yet conducted | Conduct & ratify the [first management review](2026-06-24-management-review.md) | Christopher Day |
| OBS-03 | Observation | Human-oversight gates implemented but not configured on the assessed env | Set `[governance] require_human_min_risk` / `deny_min_risk` in the deployment | Christopher Day |

All findings are logged in the [Corrective Action Log](../registers/corrective-action-log.md).

## 5. Conclusion

The **technical control design is strong** — the implemented controls conform,
and the AI-specific controls (fairness monitoring, retirement, human oversight)
are present and conforming by design. The nonconformities are **operational, not
design** defects: the opt-in controls are not yet *enabled* on a deployment, and
the documentation set is not yet *approved*. None are Major. All are tractable
via the existing deployment artifacts and the first management review.

**Recommendation:** proceed to management review, approve the documentation set,
enable the opt-in controls on the target deployment, and schedule the pen test.
Re-audit a fresh sample next quarter (Cycle 2) per [PROC-05](../procedures/internal-audit-plan.md).
