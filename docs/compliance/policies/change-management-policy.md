# Change Management Policy

| Field | Value |
| --- | --- |
| Document ID | POL-05 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Effective date | TBD |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.8.32, A.8.31; ISO/IEC 42001:2023 A.6.2.x; SOC 2 CC8.1 |

## 1. Purpose

This policy establishes the requirements for authorizing, designing, testing,
reviewing, approving, and deploying changes to Maverick and its supporting
infrastructure. It exists to ensure that changes are made in a controlled,
traceable, and authorized manner so that the confidentiality, integrity, and
availability of the platform — and the governance properties it provides to
customers as a governed agentic enterprise AI platform — are preserved through
the change lifecycle. The policy provides assurance for SOC 2, ISO/IEC
27001:2022, and ISO/IEC 42001:2023 audits.

## 2. Scope

This policy applies to all changes to:

- Source code in the Maverick monorepo (the eight `packages/` pip packages,
  `apps/installer-cli`, the FastAPI dashboard, the Tauri desktop apps, and the
  `sdks/plugin-ts` TypeScript SDK).
- Specialist packs, suites, and AI system configuration that affect the
  governed AI workforce (an AI-lifecycle change under ISO/IEC 42001).
- gRPC/proto contracts, configuration knobs, and deprecation schedules.
- CI/CD pipelines and the deployment process for the platform.

It applies to all personnel of the Organization and any contractors who propose,
review, approve, or deploy changes.

## 3. Policy statements

1. **Authorization.** Every change shall be traceable to an authorized request
   (issue, ticket, or recorded approval) before work begins. **[Process —
   Organization to operationalize]**
2. **Design & testing.** Changes shall be designed and accompanied by automated
   tests. Fixes and validation changes follow a tests-first approach, and the
   test-driven verifier guards against test-cheating.
3. **Review.** Every change shall be reviewed via pull request before it is
   merged. At least one reviewer other than the author shall approve.
   **[Process — Organization to operationalize: enforced reviewer count and
   branch-protection settings]**
4. **Automated change control.** All changes shall pass the blocking CI gates
   (lint, dead-code, secret-scanning, complexity cap, contract checks,
   accessibility, deprecation, and plugin-matrix gates) before merge. Gates
   shall not be bypassed.
5. **Approval & production deployment.** Production deployment shall require a
   documented sign-off from an authorized approver. **[Process — Organization
   to operationalize]**
6. **Segregation of duties.** The person who authors a change shall not be the
   sole party who approves and deploys it to production; development, test, and
   production environments shall be separated. **[Process — Organization to
   operationalize]**
7. **Emergency changes.** Emergency changes may bypass the normal lead time but
   shall still be reviewed, recorded, and retroactively approved within a
   defined window. **[Process — Organization to operationalize]**
8. **gRPC/proto changes** shall be additive only; removals or field renumbering
   are prohibited and are enforced by the contract gate.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Change requester / author | Raises an authorized request, designs the change, writes tests, opens a PR. |
| Reviewer / approver | Reviews the PR for correctness, security, and policy compliance; approves or rejects. **[Process — Organization to operationalize]** |
| Release / deployment approver | Provides documented production deploy sign-off. **[Process — Organization to operationalize]** |
| Head of Engineering (Owner) | Owns this policy; maintains CI gates and branch protection. |
| Management (Approver) | Approves this policy and material exceptions. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Blocking CI gates (lint, dead-code, complexity cap C901 ≤ 20) | `.github/workflows/ci.yml` (ruff lint, vulture, complexity cap) | Implemented |
| Secret scanning on change | `.github/workflows/ci.yml` (detect-secrets vs `.secrets.baseline`) | Implemented |
| Conventional Commits / PR-title enforcement | `.github/workflows/conventional-commits.yml` | Implemented |
| Custom platform CI gates | `python -m maverick.plugin_matrix --ci`, `python -m maverick.deprecations --ci`, `python -m maverick.a11y_audit --ci` (per CLAUDE.md) | Implemented |
| Additive-only proto/contract control | `python -m maverick.grpc_api.contract --check` (proto removals/renumbers fail) | Implemented |
| Test-driven verification (anti-cheat) | `packages/maverick-core/maverick/verifier.py` | Implemented |
| Peer review before merge | Pull request review requirement | Partial — tooling present; enforced reviewer count is **[Process — Organization to operationalize]** |
| Documented approval workflow | — | **[Process — Organization to operationalize]** |
| Production deploy sign-off | — | **[Process — Organization to operationalize]** |
| Segregation of duties (dev/test/prod separation) | — | **[Process — Organization to operationalize]** |
| Emergency change handling | — | **[Process — Organization to operationalize]** |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.8.32 (Change management), A.8.31 (Separation of development, test and production environments) |
| ISO/IEC 42001:2023 | A.6.2.x (AI system lifecycle — change to AI systems) |
| SOC 2 | CC8.1 (Change management) |

## 7. Exceptions & non-compliance

Exceptions to this policy require documented risk acceptance approved by
Management and shall be time-bound and reviewed at expiry. **[Process —
Organization to operationalize: exception register]** Bypassing or disabling a
blocking CI gate, merging without review, or deploying without sign-off
constitutes non-compliance and may result in reversal of the change and
disciplinary action.

## 8. Review & maintenance

This policy shall be reviewed at least annually, or upon significant change to
the platform, CI/CD pipeline, or deployment model. The Owner is responsible for
initiating the review; Management approves material revisions.
