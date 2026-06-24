# Information Security Policy

| Field | Value |
| --- | --- |
| Document ID | POL-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Effective date | TBD |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO 27001:2022 Clause 5.2, A.5.1; ISO 42001:2023 Clause 5.2; SOC 2 CC1.x, CC2.x |

## 1. Purpose

This is the top-level Information Security Policy of the Organization. It establishes the
Organization's overarching commitment to protecting the confidentiality, integrity, and
availability of information assets — its own and those entrusted to it by customers — across
the design, development, operation, and support of the Maverick platform.

This policy constitutes the Information Security Management System (ISMS) mandate required by
ISO/IEC 27001:2022 Clause 5.2 and the Artificial Intelligence Management System (AIMS) mandate
under ISO/IEC 42001:2023 Clause 5.2. It is the umbrella document under which all subordinate
security, privacy, and AI-governance policies are authorized and maintained. Where a more
specific subordinate policy exists, that policy governs the detail; this policy governs intent,
authority, and direction.

## 2. Scope

This policy applies to:

- All information assets owned, processed, stored, or transmitted by the Organization,
  including source code, customer data, learning artifacts, audit records, and the Operating
  Record.
- All components of the Maverick platform: the `maverick-core` kernel, agent shield, channels,
  dashboard, MCP server, evolve/learning subsystem, and knowledge subsystem.
- All employees, contractors, and third parties acting on behalf of the Organization.
- All environments (development, build/CI, and production) and all supporting infrastructure.

The ISMS scope boundary is the people, processes, and technology involved in delivering and
operating Maverick as a governed agentic enterprise platform. Detailed scope boundaries,
asset inventories, and interfaces are maintained in the Statement of Applicability and risk
register. **[Process — Organization to operationalize]**

## 3. Policy statements

3.1 The Organization is committed to preserving the confidentiality, integrity, and
availability of all information assets within the ISMS scope, and commits to satisfying
applicable legal, regulatory, contractual, and customer requirements.

3.2 The Organization adopts and maintains a documented ISMS aligned to ISO/IEC 27001:2022 and
an AIMS aligned to ISO/IEC 42001:2023, and supports SOC 2 Trust Services Criteria.

3.3 Security is governed by a secure-by-default posture. Maverick ships hardened-but-functional
defaults; insecure configurations are rejected or warned at startup rather than silently
permitted.

3.4 Information security risk is identified, assessed, and treated through a defined risk
management process. Risk treatment decisions are recorded and linked to the Statement of
Applicability. (See subordinate Risk Management Policy, POL-02.)

3.5 This policy authorizes and is supported by the following subordinate policies, each of which
elaborates the relevant control domain:

- Access Control Policy
- Cryptography Policy
- Change Management Policy
- Incident Response Policy
- Supplier / Third-Party Security Policy
- Data Protection & Privacy Policy
- Human Resources Security Policy
- Business Continuity & Disaster Recovery Policy
- Secure Development Policy
- AI Management Policy
- Risk Management Policy (POL-02)

3.6 All policy enforcement that can be technically encoded is implemented through Maverick's
governance and policy engine rather than left to discretion, so that controls are evaluated
consistently and auditably at runtime.

3.7 All security-relevant actions taken by the platform are recorded in the audit subsystem to
provide a tamper-evident, reviewable Operating Record.

3.8 The Organization commits to continual improvement of the ISMS and AIMS, and to conducting
management reviews at planned intervals to confirm continuing suitability, adequacy, and
effectiveness. **[Process — Organization to operationalize]**

3.9 The kernel operates without the optional agent shield: security controls fail open with a
warning rather than blocking core function, while still recording the degraded posture. This is
a deliberate availability/resilience design decision and does not waive the requirement to run
the shield in governed production deployments.

3.10 Violations of this policy or its subordinate policies are handled per Section 7.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Management / CEO | Approves this policy; owns the ISMS/AIMS mandate; allocates resources; chairs management review. **[Process — Organization to operationalize]** |
| CISO / Security Lead | Owns and maintains this policy and the ISMS; oversees risk treatment, control implementation, and subordinate policies. |
| Engineering | Implements and maintains technical controls within Maverick (governance engine, secure defaults, preflight, audit). |
| All personnel | Comply with this policy and subordinate policies; report security events and weaknesses. **[Process — Organization to operationalize]** |
| Third parties / suppliers | Comply with applicable security obligations per the Supplier Security Policy. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Secure-by-default posture (hardened but functional defaults) | `packages/maverick-core/maverick/security_defaults.py` | Implemented |
| Startup configuration validation (reject/warn on insecure config) | `packages/maverick-core/maverick/preflight.py` | Implemented |
| Policy engine / runtime governance enforcement | `packages/maverick-core/maverick/governance.py` | Implemented |
| Tamper-evident audit / Operating Record | `packages/maverick-core/maverick/audit/` | Implemented |
| Documented security hardening guidance | `docs/security-hardening.md` | Implemented |
| Enterprise security posture overview | `docs/enterprise/security-overview.md` | Implemented |
| ISMS scope, SoA, asset inventory, management review records | ISMS register (organizational) | Process |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | Clause 5.2 (Policy); A.5.1 (Policies for information security); supports Clauses 4–10 ISMS framework |
| ISO/IEC 42001:2023 | Clause 5.2 (AI policy); establishes AIMS umbrella for A.* controls |
| SOC 2 | CC1.x (Control Environment); CC2.x (Communication & Information) |

## 7. Exceptions & non-compliance

Exceptions to this policy must be requested in writing, risk-assessed, time-bound, and approved
by the CISO / Security Lead with management awareness; approved exceptions are tracked in the
risk register. **[Process — Organization to operationalize]**

Non-compliance may result in disciplinary action up to and including termination, and for third
parties may result in contract termination. Suspected violations are handled through the
Incident Response Policy where they constitute a security event.

## 8. Review & maintenance

This policy is reviewed at least annually, and upon any significant change to the Organization,
the Maverick platform, the threat landscape, or applicable regulatory obligations. Review and
approval are conducted as part of management review. The Owner maintains version history and
ensures subordinate policies remain consistent with this umbrella policy.
**[Process — Organization to operationalize]**
