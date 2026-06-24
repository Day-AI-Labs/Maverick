# Acceptable Use Policy

| Field | Value |
| --- | --- |
| Document ID | TPL-03 |
| Owner | People Ops / HR (with Security Lead) |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual |
| Frameworks | ISO 27001 A.6.2, A.6.3, A.6.6; ISO 42001 A.3.2; SOC 2 CC1.4 |

## How to use this template

This is the Acceptable Use Policy (AUP) that every person with access to Maverick
systems or data signs. It is issued as a pre-employment and onboarding step under
HR Security Procedures (PROC-06, sections 2.4 and 3). Issue it as a standalone
document, have the person read it, and collect the signature block in section 11.
Re-acknowledge annually and on any material change. **[Org action]** Replace the
bracketed fields in section 11 at signing time.

## 1. Purpose & scope

This policy defines the acceptable use of the Organization's systems, the Maverick
platform, and the data it processes. It applies to all employees, contractors,
interns, and temporary staff ("you") and to all devices used to access Maverick —
company-issued or personal. By signing, you agree to use these systems only for
authorized business purposes and in line with this policy, the HR Security Policy
(POL-10), the Responsible AI Policy (POL-12), and the Code of Conduct
(`CODE_OF_CONDUCT.md`).

## 2. Acceptable use of systems & data

- Use Organization systems and Maverick only for authorized business purposes and
  only at the access level granted to you (your dashboard RBAC role and kernel
  capabilities). Do not attempt to access systems, data, tools, or environments
  you have not been granted.
- Do not attempt to bypass, escalate, or share your access. Operate under the
  principle of least privilege; if you need more access, request it through your
  manager and the Security Lead (PROC-06 section 5).
- Keep your account secure: use the Organization's SSO, keep MFA enabled, and
  never share your login. Lock your screen when unattended.

## 3. Secret & credential handling

- Never hard-code, commit, paste, or log secrets, API keys, tokens, or passwords.
  The repository enforces a `detect-secrets` gate; committing a secret will fail
  the build and is treated as a security event.
- The `# pragma: allowlist secret` marker is **only** for verified false
  positives. A real secret that lands anywhere must be reported and **rotated**,
  not allow-listed.
- Store credentials only in the approved secret store / your SSO identity. Do not
  reuse Organization credentials on external services or personal accounts.
- Treat provider API keys, signing keys, and CI secrets as restricted; do not
  copy them to personal devices, chat tools, or notes.

## 4. Customer-data handling

- Access customer data only when a task requires it and only to the minimum
  extent needed (data minimization).
- Do not copy, export, screenshot, email, or upload customer data to any tool,
  device, or location not explicitly approved for it.
- Keep customer data within approved Maverick environments; do not paste customer
  data into unapproved third-party AI tools or services.
- Handle customer data per its classification and applicable contractual and
  regulatory obligations. When in doubt, ask the Security Lead before acting.

## 5. Device & remote-work security

- Keep devices used for work patched and running current OS and security updates.
- Ensure full-disk encryption, a screen lock with short timeout, and endpoint
  protection are enabled on any device that accesses Maverick.
- Work over trusted networks; use the Organization's VPN / approved access path
  for remote work. Avoid untrusted public networks for sensitive work.
- Do not leave devices unlocked or unattended in public. Report lost or stolen
  devices immediately (section 7).
- For personal ("BYOD") devices, you must meet the same controls and accept that
  the Organization may revoke access if they are not met.

## 6. AI-system use (ISO 42001 A.3.2; Responsible AI — POL-12)

Maverick is a governed agentic platform. When using it or operating agents:

- **Do not bypass governance or consent gates.** Approval, consent, and
  human-in-the-loop checkpoints exist by design; do not circumvent, auto-approve,
  or pressure others to bypass them.
- **Do not disable, tamper with, alter, or delete the audit log** or any audit /
  Operating-Record signing. The audit trail must remain complete and verifiable.
- **Do not disable or weaken safety controls** — capability enforcement, budget
  caps, tool ACLs, or the sandbox — to get a task done. Route shell through the
  approved sandbox path; never widen your own tool scope.
- **Operate agents within their granted scope.** Capabilities only attenuate;
  never attempt to grant an agent more than you were granted.
- **Use AI outputs responsibly:** review agent actions affecting customers or
  production, and escalate unexpected, unsafe, or non-compliant behavior under
  POL-12 and PROC-01.

## 7. Reporting obligations

- Report any suspected or confirmed security event — phishing, lost/stolen
  device, exposed secret, suspicious account activity, or unexpected agent
  behavior — promptly via the Security Incident Response procedure (PROC-01).
- Report suspected violations of this policy. Good-faith reporting is protected;
  failing to report a known event is itself a violation.

## 8. Prohibited activities

You must not:

- Share, sell, or expose Organization or customer data, IP, specialist packs, or
  the Operating Record to unauthorized parties.
- Bypass, disable, or tamper with security or governance controls (auth, MFA,
  RBAC, capabilities, budget caps, sandbox, audit log).
- Install unapproved software, or connect unapproved tools/integrations to
  Maverick or customer data.
- Use Organization systems for unlawful activity, harassment, or any purpose
  prohibited by `CODE_OF_CONDUCT.md`.
- Commit secrets to source control or attempt to defeat the secret-scanning gate.
- Use customer data or Organization systems to train, fine-tune, or evaluate
  external models or services without explicit authorization.

## 9. Consequences of non-compliance

Violations are handled under the disciplinary process in `CODE_OF_CONDUCT.md` and
PROC-06 section 7, proportionate to severity and intent, up to and including
access suspension, retraining, or termination, and may carry legal consequences.

## 10. Continuing obligations

Confidentiality and the obligations in this policy that by their nature should
continue (e.g. protection of confidential and customer data) survive the end of
your engagement, consistent with your signed NDA / confidentiality agreement.

## 11. Acknowledgement & signature

I have read, understood, and agree to comply with this Acceptable Use Policy. I
understand that violations may result in disciplinary action and that my
confidentiality obligations continue after my engagement ends.

| Field | Value |
| --- | --- |
| Full name | **[Org action]** [name] |
| Role / team | **[Org action]** [role] |
| Employment type | **[Org action]** [employee / contractor / intern / temp] |
| Date of acknowledgement | **[Org action]** [YYYY-MM-DD] |
| Signature | **[Org action]** [signature / e-signature reference] |
| Acknowledgement type | **[Org action]** [initial / annual refresh / re-acknowledgement on change] |
| Recorded by (People Ops) | **[Org action]** [name] |

> Store the signed acknowledgement in the personnel security file (PROC-06). It is
> a prerequisite for first login and is refreshed annually.
