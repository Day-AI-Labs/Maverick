# Human Resources Security Policy

| Field | Value |
| --- | --- |
| Document ID | POL-10 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Effective date | TBD |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.6.1, A.6.2, A.6.3, A.6.4, A.6.5, A.6.6, A.6.7, A.6.8; ISO/IEC 42001:2023 A.3.2, A.4.6; SOC 2 CC1.4 |

## 1. Purpose

This policy establishes the information-security requirements that apply to the
people lifecycle at the Organization — before, during, and after employment or
engagement — for everyone who works on or has access to Maverick, the
Organization's governed agentic enterprise AI platform, and its supporting
systems and data. It exists to ensure that personnel are suitable for their
roles, understand their security and AI-governance responsibilities, are
competent to discharge them, and that responsibilities and access are handled
correctly on change or termination. The policy provides assurance for SOC 2,
ISO/IEC 27001:2022, and ISO/IEC 42001:2023 audits.

> **Note:** This policy is **almost entirely an Organization process** rather
> than a set of platform controls. Human-resources security is a classic SOC 2
> and ISO/IEC 27001 process area: the controls live in HR procedures, records,
> and agreements, not in the Maverick codebase. Section 5 is therefore
> dominated by **[Process — Organization to operationalize]** items, with only
> a small number of repository artifacts (conduct, contribution, and governance
> documents) providing partial, code-adjacent support.

## 2. Scope

This policy applies to:

- All employees, contractors, contributors, interns, and third-party personnel
  who are engaged by the Organization and who have, or may have, access to
  Maverick, its source code, its infrastructure, or Organization or customer
  data.
- All phases of the engagement lifecycle: screening, terms of engagement,
  awareness and training, conduct and discipline, role change, and termination.
- Acceptable use of Maverick and supporting systems, and confidentiality
  obligations governing Organization and customer information.

## 3. Policy statements

1. **Screening.** Candidates for roles with access to Maverick or to
   Organization/customer data shall undergo background verification
   proportionate to the role's risk and to applicable law, completed and
   recorded before access is granted. **[Process — Organization to
   operationalize]**
2. **Terms and conditions of employment.** Engagement terms shall state the
   personnel member's information-security and AI-governance responsibilities,
   and shall reference this policy and the acceptable-use requirements.
   **[Process — Organization to operationalize]**
3. **Confidentiality / NDAs.** All personnel and relevant third parties shall
   sign confidentiality or non-disclosure agreements before being granted
   access to confidential Organization or customer information. **[Process —
   Organization to operationalize]**
4. **Security awareness, education, and training.** All personnel shall complete
   security-awareness training at onboarding and periodically thereafter, and
   personnel involved in the development, operation, or governance of Maverick's
   AI capabilities shall receive role-appropriate AI-governance and competence
   training, with completion recorded. **[Process — Organization to
   operationalize]**
5. **Acceptable use and conduct.** All personnel and contributors shall adhere
   to the Organization's acceptable-use requirements and code of conduct, and
   shall acknowledge them at onboarding.
6. **Disciplinary process.** A formal, fair disciplinary process shall be
   available to act against personnel who commit information-security
   violations. **[Process — Organization to operationalize]**
7. **Responsibilities on termination or change.** Information-security
   responsibilities that remain valid after termination or role change shall be
   defined and communicated; access shall be revoked or adjusted promptly and
   assets returned. **[Process — Organization to operationalize]**
8. **Return of assets.** On termination or change, all Organization assets
   (devices, credentials, tokens, data) shall be returned or revoked.
   **[Process — Organization to operationalize]**
9. **Remote working.** Personnel working remotely shall apply the Organization's
   remote-working security requirements (device, network, and data handling).
   **[Process — Organization to operationalize]**
10. **Reporting security events.** All personnel shall know how to, and shall,
    report information-security events and weaknesses promptly. **[Process —
    Organization to operationalize]**

## 4. Roles & responsibilities

- **Management** — approves this policy and the disciplinary process, and owns
  the resourcing of HR security controls.
- **Head of People / HR (Owner)** — owns screening, terms of engagement, NDAs,
  onboarding/offboarding checklists, training records, and the disciplinary
  process.
- **Head of Security** — defines security-awareness and AI-governance training
  content and the security responsibilities embedded in role descriptions.
- **Hiring managers** — ensure screening, agreements, training, and asset
  return are completed for their teams and that access matches role.
- **Maintainers / Engineering leadership** — uphold the conduct and contribution
  standards for the codebase and govern contributor roles per `MAINTAINERS.md`.
- **All personnel and contributors** — meet their security, confidentiality,
  acceptable-use, conduct, and event-reporting obligations.

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Conduct standard for contributors and community (Contributor Covenant) | `CODE_OF_CONDUCT.md` | Implemented (partial — conduct standard only) |
| Contributor guidelines and CI gates (expected behavior, quality requirements) | `CONTRIBUTING.md` | Implemented (partial — contributor obligations) |
| Governance roles and maintainer responsibilities | `MAINTAINERS.md` | Implemented (partial — role definition) |
| Pre-employment screening / background checks | HR screening procedure | **[Process — Organization to operationalize]** |
| Terms & conditions of employment with security responsibilities | Employment terms | **[Process — Organization to operationalize]** |
| Confidentiality / non-disclosure agreements | NDA procedure | **[Process — Organization to operationalize]** |
| Security-awareness and AI-governance training and records | Training program | **[Process — Organization to operationalize]** |
| Acceptable-use policy acknowledgement | Acceptable-use procedure | **[Process — Organization to operationalize]** |
| Disciplinary process | Disciplinary procedure | **[Process — Organization to operationalize]** |
| Onboarding / offboarding checklists (access, asset return) | Onboarding/offboarding procedure | **[Process — Organization to operationalize]** |
| Responsibilities after termination or role change | Termination procedure | **[Process — Organization to operationalize]** |
| Remote-working security requirements | Remote-working procedure | **[Process — Organization to operationalize]** |
| Security event/weakness reporting | Incident-reporting procedure | **[Process — Organization to operationalize]** |

As stated in the Purpose note, the overwhelming majority of these controls are
**Organization processes** operated outside the Maverick codebase. The only
code-adjacent artifacts are `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, and
`MAINTAINERS.md`, which provide partial support for the conduct, acceptable-use,
and roles statements but do not substitute for HR screening, training records,
NDAs, or onboarding/offboarding controls.

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.6.1 (screening); A.6.2 (terms and conditions of employment); A.6.3 (information security awareness, education and training); A.6.4 (disciplinary process); A.6.5 (responsibilities after termination or change of employment); A.6.6 (confidentiality or non-disclosure agreements); A.6.7 (remote working); A.6.8 (information security event reporting) |
| ISO/IEC 42001:2023 | A.3.2 (AI roles and responsibilities); A.4.6 (competence and awareness for AI) |
| SOC 2 | CC1.4 (the entity demonstrates a commitment to attract, develop, and retain competent individuals in alignment with objectives) |

## 7. Exceptions & non-compliance

Exceptions to this policy require a documented risk assessment and Management
approval, recorded with a defined expiry and compensating controls (for
example, restricted access pending completion of screening). Non-compliance —
including granting access before screening, failing to execute NDAs, or
not completing required training — may result in revocation of access,
remediation, and action under the disciplinary process referenced in this
policy.

## 8. Review & maintenance

This policy is reviewed at least annually and on significant change (a change to
employment law, the training program, the conduct or contribution standards, or
the disciplinary process). The Owner is responsible for review; Management
approves material changes. Screening confirmations, signed agreements, training
records, and onboarding/offboarding checklists are retained as audit evidence.
