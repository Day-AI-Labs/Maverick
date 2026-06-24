# Statement of Applicability (SoA) — ISO/IEC 27001:2022

| Field | Value |
| --- | --- |
| Document ID | ISMS-SOA-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Standard | ISO/IEC 27001:2022, Annex A (93 controls) |

The SoA is a **mandatory** ISO 27001 document (Clause 6.1.3 d). It records, for
every Annex A control: whether it is **Applicable**, the **justification**, the
**implementation status**, and the **evidence**. Inclusion/exclusion is driven
by the [risk assessment](../risk-register.md) and
[methodology](../risk-management-methodology.md).

**Status:** Implemented · Implemented (opt-in) · Partial · Process · Gap (see the
[crosswalk](../control-crosswalk.md) legend). **Applicable:** Y / N.

> Summary: of 93 controls, **all are Applicable**. Physical controls (A.7) are
> applicable but **inherited** from the cloud hosting provider and evidenced via
> the provider's own certification. No controls are excluded.

## A.5 Organizational controls (37)

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.5.1 | Policies for information security | Y | Process (drafted) | [POL-01](../policies/information-security-policy.md) + full policy set |
| A.5.2 | Information security roles & responsibilities | Y | Process | POL-01 §4; org chart; `MAINTAINERS.md` |
| A.5.3 | Segregation of duties | Y | Implemented | Dashboard RBAC — auditor role read-only, separate from operator/admin (`rbac.py`); capability attenuation |
| A.5.4 | Management responsibilities | Y | Process | POL-01; management review (Cl. 9.3) |
| A.5.5 | Contact with authorities | Y | Process | Breach-notification contacts; `SECURITY.md` disclosure |
| A.5.6 | Contact with special interest groups | Y | Process | Security community engagement; advisories |
| A.5.7 | Threat intelligence | Y | Partial | STRIDE threat model `docs/security/threat-model.md`; Shield rule updates `maverick/shield_updates.py` |
| A.5.8 | Information security in project management | Y | Partial | Secure-dev policy POL-06; threat model per capability |
| A.5.9 | Inventory of information & associated assets | Y | Partial | Asset list in ISMS scope; world-model/audit stores; to formalize register |
| A.5.10 | Acceptable use of information & assets | Y | Process | POL-10 acceptable-use; `CODE_OF_CONDUCT.md` |
| A.5.11 | Return of assets | Y | Process | Offboarding (POL-10) |
| A.5.12 | Classification of information | Y | Partial | Data classes in POL-11; tenant/owner scoping; to formalize labelling scheme |
| A.5.13 | Labelling of information | Y | Partial | Provenance tagging in fleet memory; secret/PII detection |
| A.5.14 | Information transfer | Y | Implemented | Secret redaction, exfil detection, capability host scopes, TLS |
| A.5.15 | Access control | Y | Implemented (opt-in) | Capabilities + RBAC + tool ACLs (`capability.py`, `rbac.py`, `tool_acl.py`); POL-03 |
| A.5.16 | Identity management | Y | Implemented (opt-in) | OIDC/SAML subject → principal mapping (`oidc.py`, `saml.py`) |
| A.5.17 | Authentication information | Y | Implemented (opt-in) | OIDC asymmetric token verification; share-link tokens stored as SHA-256 |
| A.5.18 | Access rights | Y | Implemented (opt-in) | Capability grant/attenuation/expiry; RBAC role assignment |
| A.5.19 | Information security in supplier relationships | Y | Process | POL-09; LLM/infra vendor management |
| A.5.20 | Addressing security in supplier agreements | Y | Process | DPA/SLA templates `docs/enterprise/legal/` |
| A.5.21 | Managing security in the ICT supply chain | Y | Implemented + Process | MCP/plugin hash-pinning + allowlist (`plugin_manifest.py`); Dependabot; vendor reviews are Process |
| A.5.22 | Monitoring/review/change of supplier services | Y | Process | Periodic vendor re-assessment (POL-09) |
| A.5.23 | Information security for cloud services | Y | Process | Cloud provider config + their attestations |
| A.5.24 | IR management planning & preparation | Y | Process | POL-07 (runbooks/on-call to operationalize) |
| A.5.25 | Assessment & decision on security events | Y | Implemented + Process | Audit/shield/consent events; triage process is POL-07 |
| A.5.26 | Response to security incidents | Y | Implemented | Killswitch + circuit breakers (`killswitch.py`); POL-07 |
| A.5.27 | Learning from security incidents | Y | Process | Post-incident review (POL-07) |
| A.5.28 | Collection of evidence | Y | Implemented | Tamper-evident signed audit log (`audit/signing.py`) |
| A.5.29 | Information security during disruption | Y | Implemented + Process | Checkpoint/resume, circuit breakers; DR is Process (POL-08) |
| A.5.30 | ICT readiness for business continuity | Y | Partial | Durable job queue/checkpoint; RTO/RPO to define (POL-08) |
| A.5.31 | Legal, statutory, regulatory & contractual requirements | Y | Partial | GDPR/EU AI Act mapping (`maverick/compliance.py`, `ai_act.py`); `docs/regulated-deployment.md` |
| A.5.32 | Intellectual property rights | Y | Process | Licensing/dependency compliance; proprietary code controls |
| A.5.33 | Protection of records | Y | Implemented (opt-in) | Signed + sealed audit records; encryption at rest |
| A.5.34 | Privacy & protection of PII | Y | Implemented | DSAR, erasure, retention, PII detector (`dsar.py`, `audit/erase.py`, `privacy.py`); POL-11 |
| A.5.35 | Independent review of information security | Y | Process / Gap | Internal audit (Cl. 9.2) + planned third-party pen test |
| A.5.36 | Compliance with policies/standards | Y | Partial | CI gates enforce technical standards; compliance monitoring is Process |
| A.5.37 | Documented operating procedures | Y | Partial | `docs/` operational guides; deployment playbook |

## A.6 People controls (8)

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.6.1 | Screening | Y | Process | Background checks (POL-10) |
| A.6.2 | Terms & conditions of employment | Y | Process | Employment agreements (POL-10) |
| A.6.3 | Security awareness, education & training | Y | Process | Annual training (POL-10; objective in [ISMS README §3](README.md)) |
| A.6.4 | Disciplinary process | Y | Process | POL-10; `CODE_OF_CONDUCT.md` enforcement |
| A.6.5 | Responsibilities after termination/change | Y | Process | Offboarding (POL-10) |
| A.6.6 | Confidentiality / NDAs | Y | Process | NDAs at onboarding (POL-10) |
| A.6.7 | Remote working | Y | Process | Remote-work security (POL-10) |
| A.6.8 | Information security event reporting | Y | Implemented + Process | `maverick/issue_report.py`; `SECURITY.md`; reporting channel is Process |

## A.7 Physical controls (14) — inherited from cloud provider

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.7.1 | Physical security perimeters | Y | Process (inherited) | Cloud provider data centers; evidenced via provider SOC 2/ISO |
| A.7.2 | Physical entry | Y | Process (inherited) | Cloud provider |
| A.7.3 | Securing offices, rooms & facilities | Y | Process | Company office policy + cloud provider |
| A.7.4 | Physical security monitoring | Y | Process (inherited) | Cloud provider |
| A.7.5 | Protecting against physical & environmental threats | Y | Process (inherited) | Cloud provider |
| A.7.6 | Working in secure areas | Y | Process | Company policy |
| A.7.7 | Clear desk & clear screen | Y | Process | POL-10 / company policy |
| A.7.8 | Equipment siting & protection | Y | Process (inherited) | Cloud provider |
| A.7.9 | Security of assets off-premises | Y | Process | Endpoint/remote-work policy (POL-10) |
| A.7.10 | Storage media | Y | Process (inherited) | Cloud provider media handling |
| A.7.11 | Supporting utilities | Y | Process (inherited) | Cloud provider |
| A.7.12 | Cabling security | Y | Process (inherited) | Cloud provider |
| A.7.13 | Equipment maintenance | Y | Process (inherited) | Cloud provider |
| A.7.14 | Secure disposal/re-use of equipment | Y | Process (inherited) | Cloud provider media destruction; app-level erasure (`audit/erase.py`) |

## A.8 Technological controls (34)

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.8.1 | User endpoint devices | Y | Process | Endpoint policy (POL-10) |
| A.8.2 | Privileged access rights | Y | Implemented (opt-in) | RBAC admin role; capability max_risk ceilings |
| A.8.3 | Information access restriction | Y | Implemented (opt-in) | Capability path/host scopes; tenant isolation (`paths.py`) |
| A.8.4 | Access to source code | Y | Process | Repo access controls; branch protection |
| A.8.5 | Secure authentication | Y | Implemented (opt-in) | OIDC asymmetric-only, alg-confusion hardened (`oidc.py`) |
| A.8.6 | Capacity management | Y | Implemented | Budget caps, quotas, concurrency limits (`budget.py`, `quotas.py`) |
| A.8.7 | Protection against malware | Y | Implemented | Sandbox isolation; plugin/skill scan + hash-pin; detect-secrets |
| A.8.8 | Management of technical vulnerabilities | Y | Partial | Dependabot + CI gates; pen-test cadence is Process (POL-06) |
| A.8.9 | Configuration management | Y | Partial | Preflight validation (`preflight.py`); config-as-code |
| A.8.10 | Information deletion | Y | Implemented | GDPR erase + retention TTL (`audit/erase.py`, `retention.py`) |
| A.8.11 | Data masking | Y | Implemented | Secret/PII redaction; anonymous mode (`privacy.py`) |
| A.8.12 | Data leakage prevention | Y | Implemented | Secret scrubber, exfil detection, detect-secrets gate |
| A.8.13 | Information backup | Y | Partial | Durable checkpoint/job queue; deployment backup is Process (POL-08) |
| A.8.14 | Redundancy of processing facilities | Y | Partial | Circuit breakers, resume; infra redundancy is Process |
| A.8.15 | Logging | Y | Implemented | Append-only signed audit log (`audit/`) |
| A.8.16 | Monitoring activities | Y | Implemented | OpenTelemetry, health checks, anomaly events (`observability.py`) |
| A.8.17 | Clock synchronization | Y | Process | Host/cloud NTP; audit timestamps |
| A.8.18 | Use of privileged utility programs | Y | Implemented | Shell routed through `sandbox.exec()`; CI greps for violations |
| A.8.19 | Installation of software on operational systems | Y | Implemented | Plugin default-deny allowlist + hash-pin (`plugin_manifest.py`) |
| A.8.20 | Networks security | Y | Implemented | Sandbox `--network=none`; SSRF guards; host allow-globs |
| A.8.21 | Security of network services | Y | Implemented | Capability host scopes; TLS; webhook HMAC |
| A.8.22 | Segregation of networks | Y | Implemented | Container network isolation; tenant isolation |
| A.8.23 | Web filtering | Y | Implemented | SSRF private-IP block; host allow-globs; egress lock (enterprise) |
| A.8.24 | Use of cryptography | Y | Implemented (opt-in) | AES-256-GCM at rest; Ed25519 audit chain; KMS (`crypto_at_rest.py`, `tenant/kms.py`); POL-04 |
| A.8.25 | Secure development life cycle | Y | Partial | POL-06; verifier; threat model |
| A.8.26 | Application security requirements | Y | Partial | Security-by-default; preflight; consent gates |
| A.8.27 | Secure system architecture & engineering principles | Y | Implemented | Capability chokepoint; sandbox mediation; fail-closed defaults |
| A.8.28 | Secure coding | Y | Implemented | ruff/vulture/complexity gates; no-shell=True rule; detect-secrets |
| A.8.29 | Security testing in development & acceptance | Y | Partial | Red-team corpus, chaos testing, verifier; pen test is Process |
| A.8.30 | Outsourced development | Y | Process | Contributor/vendor code controls (POL-06/POL-09) |
| A.8.31 | Separation of dev, test & production | Y | Implemented | Sandbox backends; enterprise require_container; env isolation |
| A.8.32 | Change management | Y | Partial | CI gates + PR review + conventional-commits; approval process is Process (POL-05) |
| A.8.33 | Test information | Y | Partial | Test fixtures use placeholders; `.secrets.baseline` excludes test data |
| A.8.34 | Protection of information systems during audit testing | Y | Partial | Read-only auditor RBAC role; scoped capabilities for audit access |

---

## Exclusions

**None.** All 93 Annex A:2022 controls are determined Applicable. Physical
controls (A.7) are satisfied through inheritance from the cloud hosting provider
and will be evidenced via the provider's current SOC 2 Type II / ISO 27001
certification at audit time.
