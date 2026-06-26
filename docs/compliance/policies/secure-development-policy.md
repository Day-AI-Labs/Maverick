# Secure Development Policy

| Field | Value |
| --- | --- |
| Document ID | POL-06 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.8.25, A.8.26, A.8.27, A.8.28, A.8.29, A.8.30, A.8.8; ISO/IEC 42001:2023 A.6.2; SOC 2 CC8.1, PI1.x |

## 1. Purpose

This policy defines the secure software development lifecycle (SDLC)
requirements for Maverick, covering secure coding standards, dependency
management, secrets handling, security testing, sandboxed execution, and
separation of environments. Because Maverick is a governed agentic enterprise
AI platform, the policy also covers AI/ML system development practices across
the AI system lifecycle (ISO/IEC 42001). Its purpose is to ensure that security
and processing-integrity requirements are designed and built into the platform
rather than added afterward, supporting SOC 2, ISO/IEC 27001:2022, and ISO/IEC
42001:2023 audits.

## 2. Scope

This policy applies to all development activity on Maverick: the kernel
(`maverick-core`), shield, channels, dashboard, MCP server, evolve, and
knowledge components; the specialist packs and suites that constitute the
governed AI workforce; the installer CLI; the desktop apps; and the TypeScript
SDK. It applies to all developers, reviewers, and any outsourced or contracted
development performed on behalf of the Organization.

## 3. Policy statements

1. **Secure coding standards.** Code shall conform to enforced linting and
   complexity standards; ruff is the static gate, with a complexity cap and
   dead-code analysis. Surgical diffs, no speculative abstractions, and
   tests-first for fixes and validation are required practice.
2. **Sandboxed execution.** All shell and untrusted code execution shall be
   routed through `sandbox.exec()`. Direct `shell=True` usage outside the
   sandbox package is prohibited and is detected by CI. Enterprise deployments
   shall require a container backend (deny-local) with hardened isolation.
3. **Secrets handling.** Secrets shall not be committed. The detect-secrets gate
   runs against `.secrets.baseline`; new secret hashes fail the build. False
   positives are annotated with `pragma: allowlist secret`.
4. **Dependency management.** Third-party dependencies (pip, npm, cargo) shall
   be kept current via automated update proposals and reviewed before merge. New
   top-level dependencies require a config knob and follow the change-management
   process.
5. **Vulnerability management.** Known vulnerabilities in code and dependencies
   shall be triaged and remediated on a risk-prioritized basis. **[Process —
   Organization to operationalize: SLA-based remediation timelines]**
6. **Security testing.** Changes shall be exercised by automated tests, a
   test-driven verifier that resists test-cheating, and chaos/fault-injection
   testing. A preflight check validates environment and configuration before
   execution.
7. **Secure architecture & threat modeling.** Architecture shall follow the
   documented threat model (STRIDE) and audit-readiness scope; significant
   changes shall be assessed against them.
8. **Security review.** Security-relevant changes shall undergo a security review
   before release. **[Process — Organization to operationalize: formal
   security-review sign-off and triggers]**
9. **Separation of environments.** Development, test, and production
   environments shall be separated (see POL-05). **[Process — Organization to
   operationalize]**
10. **Outsourced development.** Any outsourced or contracted development shall be
    bound to this policy and its outputs reviewed and tested to the same
    standard. **[Process — Organization to operationalize]**
11. **AI system lifecycle.** Development of specialist packs and AI system
    configuration shall follow the same secure SDLC controls and be governed
    across the AI lifecycle (design, verification, deployment, monitoring).

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Developer | Writes code to secure-coding standards, adds tests, handles secrets and dependencies correctly. |
| Security reviewer | Performs security review of security-relevant changes. **[Process — Organization to operationalize]** |
| Head of Engineering (Owner) | Owns this policy; maintains CI security gates, sandbox hardening, and threat model. |
| Management (Approver) | Approves this policy and material exceptions. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Sandboxed execution (8 isolation backends; enterprise `require_container` deny-local) | `packages/maverick-core/maverick/sandbox/` | Implemented |
| Docker hardening (`--network=none`, `--cap-drop=ALL`, `--no-new-privileges`, `--pids-limit`, `--memory`) | `packages/maverick-core/maverick/sandbox/docker.py` | Implemented |
| All shell routed through `sandbox.exec()`; `shell=True` outside sandbox blocked | CI grep gate (per CLAUDE.md) + `packages/maverick-core/maverick/sandbox/` | Implemented |
| Secrets handling | detect-secrets + `.secrets.baseline` gate in `.github/workflows/ci.yml` | Implemented |
| Test-driven verification (anti-cheat) | `packages/maverick-core/maverick/verifier.py` | Implemented |
| Chaos / fault-injection testing | `packages/maverick-core/maverick/chaos.py` | Implemented |
| Preflight environment/config validation | `packages/maverick-core/maverick/preflight.py` | Implemented |
| Dependency updates (pip/npm/cargo, weekly) | `.github/dependabot.yml` | Implemented |
| Threat model (STRIDE) | `docs/security/threat-model.md` | Implemented |
| Pen-test scope / audit readiness | `docs/security/audit-readiness.md` | Implemented |
| Secure coding / complexity gates | `.github/workflows/ci.yml` (ruff, vulture, complexity cap) | Implemented |
| Security-review sign-off process | — | **[Process — Organization to operationalize]** |
| Vulnerability remediation SLAs | — | **[Process — Organization to operationalize]** |
| Outsourced-development controls | — | **[Process — Organization to operationalize]** |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.8.25 (Secure development lifecycle), A.8.26 (Application security requirements), A.8.27 (Secure system architecture and engineering principles), A.8.28 (Secure coding), A.8.29 (Security testing in development and acceptance), A.8.30 (Outsourced development), A.8.8 (Management of technical vulnerabilities) |
| ISO/IEC 42001:2023 | A.6.2 (AI system lifecycle) |
| SOC 2 | CC8.1 (Change management), PI1.x (Processing integrity) |

## 7. Exceptions & non-compliance

Exceptions require documented, time-bound risk acceptance approved by
Management. **[Process — Organization to operationalize: exception register]**
Disabling a security gate, committing secrets, bypassing the sandbox, or
shipping outsourced work without review constitutes non-compliance and may
result in reversal of the change and disciplinary action.

## 8. Review & maintenance

This policy shall be reviewed at least annually, or upon significant change to
the SDLC, sandbox model, dependency tooling, or threat model. The Owner
initiates the review; Management approves material revisions.
