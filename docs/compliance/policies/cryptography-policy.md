# Cryptography Policy

| Field | Value |
| --- | --- |
| Document ID | POL-04 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO 27001:2022 A.8.24, A.5.33; SOC 2 CC6.1, CC6.7, C1.1 |

## 1. Purpose

This policy defines the Organization's requirements for the use of cryptography within the Maverick platform to protect the confidentiality, integrity, and tamper-evidence of information. It establishes approved algorithms, key management practices, and the application of cryptography to data at rest, data in transit, and audit integrity. The policy supports the Organization's obligations under ISO/IEC 27001:2022 and SOC 2.

## 2. Scope

This policy applies to:

- Encryption of data at rest, including the world database and agent memory.
- Encryption of data in transit between Maverick components and external services.
- Cryptographic key generation, storage, rotation, and destruction, including local keys and externally managed (KMS) keys.
- Use of cryptography for integrity and tamper-evidence, including the audit hash-chain and sealing of closed audit files.
- All deployments of Maverick operated by or on behalf of the Organization.

**Critical deployment note:** At-rest encryption and audit signing are **on by default** under the secure-by-default profile (`security_defaults.py`). A deployment is **not compliant** with this policy if they are explicitly disabled (`MAVERICK_SECURE_DEFAULT=0`, or the per-control knobs `[encryption] at_rest = false` / `[audit] sign = false`). The Organization shall deploy with the hardened defaults or equivalent explicit configuration.

## 3. Policy statements

1. **Approved algorithms.** Symmetric confidentiality shall use **AES-256-GCM**. Digital signatures and integrity for the audit chain shall use **Ed25519**. Deprecated or weakened algorithms shall not be used. **[Process — Organization to operationalize]** maintenance of the approved-algorithm and deprecation list.
2. **Encryption at rest.** The world database and agent memory shall be encrypted with AES-256-GCM. At-rest encryption shall be enabled in all production deployments.
3. **Encryption in transit.** All network communication carrying sensitive data shall use TLS. **[Process — Organization to operationalize]** the minimum TLS version, cipher-suite baseline, and certificate management standard.
4. **Key storage.** The local at-rest key shall be stored at `~/.maverick/keys/at_rest.key` with file mode `0600`. Where an external KMS is used, the key shall be supplied via `MAVERICK_ENCRYPTION_KEY` and the local key file shall not hold long-lived secrets.
5. **Key management & envelope encryption.** Multi-tenant deployments shall use per-tenant envelope encryption (data-encryption keys wrapped by key-encryption keys) integrated with a managed KMS (AWS KMS, GCP KMS, or HashiCorp Vault).
6. **Key rotation.** Keys shall be rotated on a defined schedule and on suspected compromise or personnel change. **[Process — Organization to operationalize]** the rotation cadence (KEK and DEK) and emergency-rotation runbook.
7. **Integrity & tamper-evidence.** Audit records shall be protected by an Ed25519 Merkle hash-chain; closed audit day-files shall be sealed with AES-256-GCM. Audit signing shall be enabled in all production deployments.
8. **Secret handling.** Secrets shall be scrubbed from logs and outputs and shall never be committed to source control.
9. **Protection of records.** Cryptographic protection of records shall be sufficient to ensure their confidentiality, integrity, and admissibility for the required retention period. **[Process — Organization to operationalize]** the records retention schedule.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Management / Approver | Approves this policy; owns accountability for the cryptography program. |
| Security Lead / CISO (Owner) | Maintains the policy; approves algorithms and key-management standards; ensures at-rest encryption and audit signing are enabled. |
| Platform / Operations | Deploys the hardened profile; configures KMS integration; manages key storage, permissions, and rotation. |
| Audit / Compliance | Verifies tamper-evidence of audit records and evidence of key controls. |
| All users / developers | Avoid handling raw keys; never embed secrets in source. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| AES-256-GCM at-rest encryption of world DB + memory; local key at `~/.maverick/keys/at_rest.key` (mode 0600); `MAVERICK_ENCRYPTION_KEY` for external KMS | `packages/maverick-core/maverick/crypto_at_rest.py` | **On by default (secure-by-default) — keep enabled** |
| Per-tenant envelope encryption (DEK + KEK; wrappers for AWS/GCP/Vault KMS) | `packages/maverick-core/maverick/tenant/kms.py` | Operational (multi-tenant) |
| Ed25519 Merkle hash-chain for tamper-evident audit | `packages/maverick-core/maverick/audit/signing.py` | **On by default (secure-by-default) — keep enabled** |
| AES-256-GCM sealing of closed audit day-files | `packages/maverick-core/maverick/audit/sealing.py` | Operational |
| Secret scrubbing | `packages/maverick-core/maverick/secrets.py` | Operational |
| Hardened profile: at-rest encryption + audit signing ON by default | `packages/maverick-core/maverick/security_defaults.py` | Enable hardened profile |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.8.24 use of cryptography; A.5.33 protection of records |
| SOC 2 | CC6.1 logical access (cryptographic protection of data); CC6.7 protection of data in transmission/movement; C1.1 confidentiality of information |

## 7. Exceptions & non-compliance

Any deployment that does not enable at-rest encryption and audit signing is non-compliant with this policy and shall not process production or regulated data until remediated. Use of an algorithm outside the approved list requires documented risk acceptance approved by the Owner and Management, with a defined expiry. **[Process — Organization to operationalize]** the cryptographic exception register. Violations may result in remediation directives and disciplinary action.

## 8. Review & maintenance

This policy shall be reviewed at least annually and upon any significant change to Maverick's cryptographic implementation, key-management architecture, KMS provider, or the cryptographic threat environment (including algorithm deprecation guidance). The Owner is responsible for initiating review and recording approval.
