# SOC 2 Readiness & Control Turn-On Guide

This is the SOC 2 workstream entry point. The detailed control mapping lives in
[`../soc2-controls.md`](../soc2-controls.md); this document covers **readiness
posture**, the **Type I → Type II path**, and the **control turn-on guide** that
a compliant deployment must follow.

> SOC 1 is out of scope — Maverick is not a financial-reporting system for
> customers (no ICFR relevance). See the program [README](../README.md).

## 1. Type I vs Type II

| Report | What it attests | Effort |
| --- | --- | --- |
| **SOC 2 Type I** | Controls are suitably *designed* at a point in time | ~4–8 weeks once policies + process docs exist |
| **SOC 2 Type II** | Controls *operated effectively* over a window (typically 3–6+ months of evidence) | Type I + the observation window |

Enterprise buyers generally require **Type II**. The practical sequence is:
approve policies → close Process gaps → enable opt-in controls → **Type I** →
run the observation window collecting evidence → **Type II**.

## 2. Trust Services Categories in scope

- **Security (Common Criteria, CC)** — mandatory; Maverick's strongest area.
- **Availability (A)** — budget/quota caps, checkpoint/resume, circuit breakers.
- **Processing Integrity (PI)** — verifier gates, signed audit, output shield.
- **Confidentiality (C)** — tenant isolation, encryption at rest, redaction.
- **Privacy (P)** — DSAR, erasure, retention, Art.50 disclosure.

The Organization decides which optional categories (A/PI/C/P) to include in the
report scope; all five are substantially supported.

## 3. Control turn-on guide (REQUIRED for a compliant deployment)

Several strong controls ship **off-by-default** so single-tenant local use is
unchanged. For a SOC 2 (and ISO 27001) deployment they must be **enabled and
shown enabled** in the evidence snapshot. This is configuration, not new code.

| Control | Enable via | Evidence key (`collect_soc2_evidence()`) | Target |
| --- | --- | --- | --- |
| Capability enforcement | `[capability]` / deployment profile | `controls.capability_enforcement` | `enabled` |
| Tenant isolation | enterprise/multi-tenant config | `controls.tenant_isolation` | `enabled` |
| Usage quotas | `[quotas]` enforcement | `controls.usage_quotas` | `enabled` |
| OIDC authentication | `[auth]` OIDC config | `controls.oidc_auth` | `enabled` |
| Encryption at rest | `[crypto]` / `MAVERICK_ENCRYPTION_KEY` | `controls.encryption_at_rest` | `enabled` |
| Audit signing | `[audit] sign = true` / `MAVERICK_AUDIT_SIGN=1` | `audit_log` | `ok` (not `unsigned`) |

The hardened-but-functional defaults live in `maverick/security_defaults.py`;
the enterprise deployment profile turns these on as a group. See
`docs/security-hardening.md` and `docs/enterprise/security-overview.md`.

## 4. Verifying posture (evidence collection)

Maverick ships a machine-readable evidence collector:

```bash
python -c "import json; from maverick.soc2 import collect_soc2_evidence; \
print(json.dumps(collect_soc2_evidence(), indent=2))"
```

A SOC 2-ready snapshot shows `capability_enforcement`, `tenant_isolation`, and
`usage_quotas` as `enabled`, `oidc_auth` and `encryption_at_rest` as `enabled`,
`audit_log` as `ok`, and `audit_signing_key` present.

The **`maverick soc2`** CLI command does exactly this — it prints the evidence
snapshot as JSON and **exits non-zero unless every required control is in a
ready posture** (the `_soc2_posture_ready` gate: required controls `enabled`,
`audit_log` `ok`, signing key present). Wire it into CI or a deploy gate the
same way as `maverick compliance --strict`:

```bash
maverick soc2            # pretty JSON; exit 1 if not SOC 2-ready
maverick soc2 --json     # compact single-line JSON for log capture
```

Capture this snapshot periodically during the Type II window as design +
operating evidence.

### Standing posture gate (CI)

The [`Compliance Posture`](../../../.github/workflows/compliance-posture.yml)
GitHub Actions workflow runs the gate automatically: it applies
[`compliant-config.toml`](../deployment/compliant-config.toml) and fails unless
`maverick soc2` is compliant-ready. It runs weekly, on demand
(`workflow_dispatch`), and on any change to the controls/config that affect
posture — a **regression gate** so a code change can't silently break the
ability to pass (it would have caught the off-host-key false-negative). It also
uploads each run's `soc2-evidence.json` as an artifact. This workflow is
`pull_request`-triggered and executes code from the checked-out tree, so keep it
on GitHub-hosted runners only; do **not** retarget it to a production or other
privileged self-hosted runner. To gate a *live* deployment, run
[`verify-posture.sh`](../deployment/verify-posture.sh) on the deployment host
from a trusted, protected ref or another trusted deployment automation path.

## 5. Process controls to operate (NOT code)

A Type II report cannot pass on engineering controls alone. These are owned by
the Organization. Each now has a **drafted operational procedure** (see the
[operations index](../procedures/README.md)) — what remains is *operating* it to
produce evidence over the observation window:

- Change-management process (CC8) → [PROC-03](../procedures/change-management-procedure.md)
- Vendor / sub-processor management (CC9.2) → [PROC-07](../procedures/vendor-management-procedure.md) + [REG-01](../registers/subprocessor-register.md)/[REG-04](../registers/vendor-register.md)
- Incident-response program (CC7.4) → [PROC-01](../procedures/incident-response-runbook.md) + [TPL-01](../templates/incident-report-template.md)
- HR controls (CC1.4) → [PROC-06](../procedures/hr-security-procedures.md) + [TPL-03](../templates/acceptable-use-policy.md)
- Risk-assessment program (CC3) → [PROC-04](../procedures/risk-assessment-and-review-procedure.md) + [methodology](../risk-management-methodology.md)/[register](../risk-register.md)
- Vulnerability management / pen-test cadence (CC7.1) → [PROC-02](../procedures/vulnerability-management-procedure.md) + [REG-02](../registers/remediation-tracker.md)
- Physical/environmental security (CC6/A1) → cloud provider's own SOC 2/ISO report

## 6. Readiness checklist

- [ ] Policies POL-01…POL-12 approved by Management with effective dates
- [ ] Risk register reviewed and accepted
- [ ] Opt-in controls enabled; evidence snapshot shows all targets met
- [ ] Process gaps (§5) operationalized with owners
- [ ] Cloud provider attestations collected (inherited physical/env controls)
- [ ] Auditor (CPA firm) engaged for Type I
- [ ] Observation window started for Type II evidence collection
