# HR Security Procedures

| Field | Value |
| --- | --- |
| Document ID | PROC-06 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Review cycle | Annual |
| Frameworks | ISO 27001 A.6.1, A.6.2, A.6.3, A.6.4, A.6.5, A.6.6; ISO 42001 A.3.2, A.4.6; SOC 2 CC1.4 |

## 1. Purpose & scope

This procedure operationalizes the HR Security Policy (POL-10) across the full
employment lifecycle — pre-employment, onboarding, role change, and offboarding
— for everyone with logical or physical access to Maverick systems or customer
data: employees, contractors, interns, and temporary staff. It is the runnable
companion to POL-10: where POL-10 states the requirement, this procedure states
the steps, owners, evidence, and timing.

Roles referenced below:

- **People Ops / HR** — owns the lifecycle workflow and records.
- **Security Lead** — owns access-grant approval, secret rotation, and the
  security-awareness program.
- **Hiring Manager** — defines the least-privilege role and confirms business
  need for each access grant.
- **IT / Platform** — executes provisioning and de-provisioning in the identity
  provider (OIDC/SSO), the Maverick dashboard, and the kernel.

Every step that requires acting on a real person, vendor, or live system is
marked **[Org action]** with the exact action to take. Each lifecycle event must
leave an evidence record (ticket ID, signed form, or screenshot) in the
personnel security file retained per the records-retention schedule.

## 2. Pre-employment (ISO 27001 A.6.1, A.6.2; SOC 2 CC1.4)

Complete ALL of the following before the candidate is granted any access or a
start date is confirmed. Do not provision accounts until section 2 is complete
and recorded.

1. **Background & reference screening** **[Org action]** — Before extending a
   final offer, run screening proportionate to the role's access level and to
   applicable law in the candidate's jurisdiction:
   - Verify identity and right to work.
   - Verify the most recent / most relevant employment and education claims.
   - Obtain at least two professional references and record the outcome.
   - For roles with **admin** dashboard access, production access, or access to
     customer data, additionally run a criminal-records / sanctions check where
     legally permitted, and document candidate consent.
   - Record screening completion (pass / fail / exception) and the approver in
     the personnel file. Re-screening on role change is covered in section 4.
2. **Signed employment terms** **[Org action]** — Issue the employment contract
   / statement of work stating the person's information-security
   responsibilities and the consequences of non-compliance (cross-reference
   POL-10 and CODE_OF_CONDUCT.md). Collect a signed copy.
3. **NDA / confidentiality agreement** **[Org action]** — Have the person sign
   the confidentiality agreement covering Maverick IP, the specialist packs,
   customer data, and the Operating Record. Record the signature date; this
   obligation survives termination (see section 6 and the offboarding
   reminder).
4. **Acceptable-use acknowledgement** **[Org action]** — Have the person read
   and sign the Acceptable Use Policy (TPL-03). Store the signed acknowledgement
   in the personnel file; it is a prerequisite for first login.

**Gate:** identity provisioning (section 3) MUST NOT begin until items 2, 3, and
4 are signed and screening (item 1) has a recorded outcome.

## 3. Onboarding security checklist (ISO 27001 A.6.2, A.6.3; ISO 42001 A.4.6; SOC 2 CC1.4)

Target: complete within the first **3 business days**; security-awareness
training assigned on **day 1** and completed within **14 days** (section 4).

The Hiring Manager nominates the least-privilege role; the Security Lead approves
the access grant before IT provisions it. Default to the lowest role that lets
the person do their job — escalate later on demonstrated need, never the reverse.

| # | Step | Owner | How (concrete) | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Identity provisioning | IT / Platform | **[Org action]** Create the user in the OIDC/SSO identity provider; never create shared/standing local accounts. Bind the dashboard principal to the SSO identity. | IdP user record + ticket ID |
| 2 | Dashboard RBAC grant (least privilege) | Security Lead approves; IT executes | **[Org action]** Assign exactly ONE dashboard role in `~/.maverick/dashboard-users.json` (managed via the dashboard user-admin UI / `MAVERICK_DASHBOARD_ADMINS` for bootstrap). Roles and what they grant (`packages/maverick-dashboard/maverick_dashboard/rbac.py`): **viewer** = view only; **operator** = run/cancel goals, approve, tools (operate + view); **auditor** = read audit trail + view, NO operational rights (separation of duties for compliance reviewers); **admin** = users, settings, secrets + all. Grant `admin` only to named platform owners. | Roster entry + Security Lead approval |
| 3 | Kernel capability grant (attenuating) | Security Lead approves; IT executes | **[Org action]** Where capability enforcement is on (`[capabilities] enforce = true` / `MAVERICK_ENFORCE_CAPABILITIES=1`), issue the person/agent principal a scoped, Ed25519-signed `Capability` (`packages/maverick-core/maverick/capability.py`): set `allow_tools` (empty = all; prefer an explicit whitelist), `deny_tools`, `max_risk` ceiling (`low`/`medium`/`high`), and `allow_paths` / `allow_hosts` globs. Capabilities only attenuate down to children, so start narrow. | Signed capability grant record |
| 4 | MFA enrollment | IT / Platform + person | **[Org action]** Require MFA enrollment in the IdP at first login; block access until MFA is active. | IdP MFA-enabled flag |
| 5 | Security-awareness training assignment | Security Lead | **[Org action]** Assign the initial training module (section 4) on day 1 with a 14-day due date. | LMS assignment record |
| 6 | Asset issuance | IT / Platform | **[Org action]** Issue and inventory any company device(s); confirm disk encryption, screen-lock, and endpoint protection are on before handover. Record asset tag against the person. | Asset register entry |
| 7 | Policy acknowledgements on file | People Ops / HR | Confirm AUP (TPL-03), NDA, and employment terms from section 2 are signed and stored. | Personnel file index |
| 8 | Add to escalation / on-call (if applicable) | Hiring Manager | **[Org action]** Add to on-call rota and incident-escalation contacts only if the role requires it. | Rota entry |

**Provisioning rule:** no access is enabled until the matching access-grant
approval (steps 2 and 3) is recorded. A grant without a recorded approver is a
finding.

## 4. Security awareness & training (ISO 27001 A.6.3; ISO 42001 A.3.2, A.4.6; SOC 2 CC1.4)

**Cadence:**

- **Initial:** assigned day 1, completed within 14 days of start (gate before
  unsupervised access to customer data).
- **Annual:** refresh for all personnel; due within the anniversary month of
  hire or on a fixed organization-wide window.
- **Event-driven:** ad-hoc module within 5 business days after a relevant
  incident, a major policy change, or a role change into a higher-privilege
  role.

**Required topics (every cycle):**

1. **Phishing & social engineering** — recognizing and reporting suspicious
   messages; no credential entry on links.
2. **Secure handling of customer data** — data classification, minimization, and
   the prohibition on exporting customer data to unapproved tools/devices.
3. **Secret hygiene** — never commit credentials; the repository enforces a
   `detect-secrets` pre-commit/CI gate against `.secrets.baseline`. Train staff
   that new secrets fail the build and that `# pragma: allowlist secret` is only
   for verified false positives; real secrets must be rotated, not allow-listed.
4. **Incident reporting** — how and when to report a security event per the
   Security Incident Response procedure (PROC-01); the duty to report applies to
   suspected as well as confirmed events.
5. **Responsible-AI awareness** — obligations under the Responsible AI Policy
   (POL-12): respect governance and consent gates, never disable or tamper with
   the audit log, and escalate unexpected or unsafe agent behavior.

**Completion tracking** **[Org action]:** Security Lead records completion per
person per cycle in the LMS / training register. People Ops chases overdue
assignments at 7 days past due; access for staff overdue past the grace window
is escalated to the Hiring Manager and may be suspended. The training register is
the audit evidence for ISO 27001 A.6.3 / SOC 2 CC1.4.

## 5. Role change & internal transfer (ISO 27001 A.6.5; least privilege)

When a person changes role, team, or responsibilities:

1. **[Org action]** Hiring Manager raises a role-change request stating the new
   responsibilities and the access required.
2. **[Org action]** Security Lead re-evaluates access against least privilege:
   - Adjust the dashboard RBAC role to the new minimum (e.g. drop `operate` if
     the person no longer runs goals; grant `auditor` rather than `admin` for a
     move into compliance review).
   - Re-issue or re-scope the kernel `Capability` (`allow_tools`, `max_risk`,
     `allow_paths`/`allow_hosts`) to match the new duties.
   - **Remove access that is no longer needed** — additive-only transfers cause
     privilege creep and are a finding.
3. **[Org action]** Re-screen if moving into a role whose screening bar in
   section 2 is higher than the original (e.g. into admin / production / customer
   data access).
4. Record the before/after access state and approver in the personnel file.

## 6. Offboarding security checklist (ISO 27001 A.6.4, A.6.5, A.6.6; SOC 2 CC1.4)

**Timing:**

- **Standard / voluntary departure:** all access revoked within **24 hours** of
  the effective end time.
- **Involuntary termination or any security concern:** revoke access
  **immediately** (target within 1 hour of notification), before or concurrent
  with notifying the person where lawful.

People Ops triggers offboarding the moment a departure is confirmed; the Security
Lead owns completion and sign-off.

| # | Step | Owner | How (concrete) | Target |
| --- | --- | --- | --- | --- |
| 1 | Revoke OIDC/SSO | IT / Platform | **[Org action]** Disable the user in the IdP; terminate active SSO sessions. This is the master kill-switch for SSO-bound dashboard access. | 24h / immediate |
| 2 | Revoke dashboard RBAC | IT / Platform | **[Org action]** Remove the principal from `~/.maverick/dashboard-users.json` (and from `MAVERICK_DASHBOARD_ADMINS` / `[dashboard] admins` if pinned). Confirm they are not a config-pinned bootstrap admin. | 24h / immediate |
| 3 | Revoke kernel capabilities | IT / Platform | **[Org action]** Revoke / expire the person's signed `Capability` grants; remove their principal from any role/domain capability config. | 24h / immediate |
| 4 | Revoke tokens & API keys | IT / Platform | **[Org action]** Revoke any personal access tokens, dashboard tokens, and API keys the person held or could have cached. | 24h / immediate |
| 5 | Rotate shared secrets held | Security Lead | **[Org action]** Rotate every shared/service secret, provider API key, or credential the person had access to (provider keys, signing keys, CI secrets). Update `.secrets.baseline` only via the normal flow; never store the new secret in the repo. | 24h / immediate |
| 6 | Return assets | IT / Platform + People Ops | **[Org action]** Recover company devices; wipe or re-image; reconcile against the asset register. Recover any physical access tokens/badges. | At exit |
| 7 | Remove from on-call / escalation | Hiring Manager | **[Org action]** Remove from on-call rota, incident-escalation lists, and shared alias / distribution groups. | 24h / immediate |
| 8 | Exit confidentiality reminder | People Ops / HR | **[Org action]** Deliver a written exit reminder that NDA / confidentiality obligations (section 2.3) survive termination; have the person acknowledge where possible. | At exit |
| 9 | Completion sign-off | Security Lead | Confirm steps 1–8 are evidenced; record date/time of full access revocation. | Within SLA |

**Verification:** the Security Lead spot-checks that no residual access remains
(IdP shows disabled, roster shows no entry, no live tokens). The completed
checklist with timestamps is the audit evidence for ISO 27001 A.6.4 and A.6.5.

## 7. Disciplinary process & reporting security events (ISO 27001 A.6.4; SOC 2 CC1.4)

- **Disciplinary process:** violations of this procedure, POL-10, the AUP
  (TPL-03), or the Responsible AI Policy (POL-12) are handled under the
  organization's disciplinary process as defined in `CODE_OF_CONDUCT.md`. Actions
  are proportionate to severity and intent and may include access suspension,
  retraining, or termination. People Ops and the Security Lead jointly determine
  the response for security-related violations.
- **Reporting security events:** all personnel must report suspected or confirmed
  security events promptly per the Security Incident Response procedure (PROC-01).
  Good-faith reporting is protected and is reinforced in the annual awareness
  training (section 4).

## 8. Records & review

- Evidence for each lifecycle event (screening outcomes, signed agreements,
  onboarding/offboarding checklists, training register, access-grant approvals)
  is retained in the personnel security file per the records-retention schedule.
- This procedure is reviewed at least annually by People Ops with the Security
  Lead, and after any material change to the identity provider, the dashboard
  RBAC model, or the capability model. Changes are versioned in the table above.
