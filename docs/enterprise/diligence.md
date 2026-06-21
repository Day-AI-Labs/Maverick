# Security & compliance data room

A single entry point for technical and security due diligence. Each row maps a
question a reviewer will ask to the artifact that answers it and, where it
exists, the command that **verifies** the claim on a live install — so a "yes"
can be exercised, not just asserted.

This page is deliberately honest about status: **code-enforced** controls ship
and are testable today; **company-process** controls are owned outside this
repo; **in progress** items are named, not implied.

## Posture in one paragraph

Lightwork is a governed, self-hostable AI agent runtime designed to run on
private/regulated data without that data leaving the customer boundary
(Enterprise mode: egress lock, fail-closed consent, capability scoping,
encryption at rest — see [security-overview.md](security-overview.md)). Safety
is defense-in-depth (detection + action-layer containment), measured and
reproducible ([shield benchmark](../security/shield-benchmark.md)). Evidence is
tamper-evident (Ed25519 hash-chained audit). The product is proprietary,
commercially licensed software ([LICENSE](../../LICENSE)). SOC 2 Type II and a
third-party penetration test are in progress; the code controls those reports
rely on are in place and verifiable now.

## Diligence map

| Area | What reviewers ask | Artifact | Verify |
|---|---|---|---|
| **Data handling / residency** | Can our data reach a third party? | Enterprise data-boundary guarantee — [security-overview.md](security-overview.md#the-data-boundary-guarantee-enterprise-mode) | `maverick enterprise verify` (exercises the egress lock + at-rest sealing) |
| **Encryption at rest** | Are sensitive stores encrypted? | [encryption.md](../encryption.md) (AES-256-GCM) | `maverick enterprise verify`; `maverick encryption migrate` |
| **Access control** | AuthN/Z, least privilege, tenancy? | [security-overview.md §Identity & access](security-overview.md#identity--access) (OIDC, RBAC, attenuating capabilities, per-tenant) | capability + OIDC + tenancy test suites (see [audit-readiness.md](../security/audit-readiness.md#5-security-test-suites-by-area)) |
| **Audit & evidence** | Tamper-evident, exportable logs? | [security-overview.md §Audit](security-overview.md#audit--evidence) | `maverick audit verify` (validates the hash chain); `maverick audit export` |
| **Threat model** | What's defended, what isn't? | [threat-model.md](../security/threat-model.md) (STRIDE, trust boundaries, out-of-scope) | n/a (design doc; cross-referenced by the test suites) |
| **AI/agent safety** | Prompt-injection / unsafe actions? | [shield-benchmark.md](../security/shield-benchmark.md) (layered detection + a decode/defang pre-pass that defeats base64/hex/homoglyph obfuscation on input, tool-call, and output surfaces + confirm-gated writes + container-isolated shell + budget caps) | `python benchmarks/security/detector_score.py`; latency/ReDoS CI gate |
| **Vulnerability mgmt** | Deps, SAST, secrets? | [audit-readiness.md §Static-analysis gates](../security/audit-readiness.md#4-reproducible-verification-harness) | `pip-audit`; `bandit`; detect-secrets baseline; all blocking in CI |
| **Supply chain** | SBOM, provenance, third-party code? | SBOM produced in CI (CycloneDX); third-party **plugin isolation** (out-of-process under enterprise) + **content-hash lockfile** (drifted/unpinned plugins refused) | CI `audit` job artifact; `[plugins] isolation` / `lock_policy` |
| **SOC 2 readiness** | Control coverage + gaps? | [soc2-controls.md](../compliance/soc2-controls.md) (CC1–CC9, A/PI/C/P mapping + honest gap list) | `python -c "from maverick.soc2 import collect_soc2_evidence as c; print(c())"` |
| **Deployment / topology** | How does it run in our env? | [security-overview.md §Reference architecture](security-overview.md#reference-architecture-self-host--air-gap) (laptop / VPC / k8s / air-gap) | `maverick enterprise verify` on the target host |
| **Regulatory mapping** | GDPR / EU AI Act / DSAR? | [regulated-deployment.md](../regulated-deployment.md); `ai_act.py`; DSAR via `dsar.py` | `maverick compliance --strict` |
| **IP / licensing** | What are we acquiring? | [LICENSE](../../LICENSE) (proprietary), [editions.md](editions.md), dependency licenses | CI license gate (denies strong-copyleft) |

## Honest status

**Code-enforced and verifiable today:** egress lock, fail-closed consent,
capability scoping, encryption at rest, OIDC SSO, per-tenant isolation,
hash-chained signed audit, SBOM + dependency/secret/SAST CI gates, the shield's
layered detection + obfuscation-decoding pre-pass + action-layer containment,
container-default sandbox and third-party-plugin isolation + hash-lock under the
enterprise profile, and the SOC 2 evidence collector. The whole regulated posture
is selectable with one knob (`MAVERICK_PROFILE=enterprise`), each control still
individually overridable.

**Must be enabled for a compliant deployment (opt-in by design):** several
controls (capabilities, tenant isolation, quotas, OIDC, encryption at rest,
audit signing) ship off by default so single-tenant local use is unchanged. A
regulated deployment turns them on — `maverick compliance --strict` gates on the
[`REGULATED_PROFILE`](../regulated-deployment.md), and the evidence snapshot must
show `audit_log = ok` (signed), not `unsigned`.

**Company-process controls (owned outside this repo):** change-management
policy, vendor/sub-processor management (incl. LLM providers), incident-response
program, HR controls, physical/environmental security (inherited from the
hosting provider's SOC 2), and a documented risk-assessment program. These are
enumerated in [soc2-controls.md §Gap summary](../compliance/soc2-controls.md).

**In progress (named, not implied):** SOC 2 Type II attestation, a third-party
penetration test, and SCIM/SAML provisioning (OIDC ships today).

## Reproduce the whole verification pass

```bash
maverick enterprise verify          # egress lock + at-rest sealing actually hold
maverick compliance --strict        # regulated profile is fully enabled
maverick audit verify               # audit hash-chain is intact
python benchmarks/security/detector_score.py   # shield detection numbers (offline)
# CI also runs, blocking: pip-audit, bandit, detect-secrets, license gate, SBOM
```

No hyperscaler dependency and no product telemetry; everything above runs inside
the customer boundary.
