# Data Processing Agreement (template)

> **Not legal advice.** A skeleton DPA (GDPR Art. 28) to accelerate counsel
> review. Bracketed fields are deployment-specific. Pairs with
> `subprocessors.md` and the technical controls in `../diligence.md`.

**Controller:** `<customer legal entity>`  **Processor:** `<your legal entity>`
**Effective date:** `<…>`

## 1. Subject matter & duration
The Processor processes personal data solely to provide the Maverick agent
platform for the term of the underlying agreement and deletes/returns it on
termination (see §7).

## 2. Nature & purpose of processing
Operating a governed AI agent: accepting tasks, calling LLM provider(s), running
governed tools in a sandbox, and persisting goal/episode/audit state.

## 3. Categories of data & data subjects
- **Data subjects:** `<customer's employees / end-users>`.
- **Personal data:** task content, conversation history, and any PII contained
  in prompts/tool I/O the customer submits. No special-category data unless
  agreed in writing.

## 4. Controller instructions
The Processor acts only on documented instructions. Deployment configuration
(providers, channels, retention, tenancy) constitutes such instructions.

## 5. Confidentiality & security (Art. 32)
The Processor maintains, and can demonstrate: encryption at rest (AES-256-GCM),
a tamper-evident signed audit log (Ed25519 hash chain), tenant isolation,
RBAC/SSO (OIDC), secret scrubbing, and a sandboxed execution boundary. Verify
with `maverick enterprise verify`. `<Add SOC 2 / ISO status when available.>`

## 6. Sub-processors (Art. 28(2),(4))
Per `subprocessors.md`. The Processor notifies the Controller of changes with
`<N>` days' notice and a right to object.

## 7. Data subject rights & deletion (Art. 15–20, 17)
The platform supports export (`maverick dsar export`), erasure
(`maverick erase` / `tenant delete --purge`, which re-signs the audit chain),
and configurable retention (`[retention]`, enforced by `maverick retention
enforce`). The Processor assists the Controller in fulfilling DSARs.

## 8. Breach notification (Art. 33)
The Processor notifies the Controller without undue delay (target `<24–72h>`)
after becoming aware of a personal-data breach. See `../../../SECURITY.md`.

## 9. Audits (Art. 28(3)(h))
The Controller may audit via: the machine-readable control snapshot
(`collect_soc2_evidence()`), reproducible security test suites, and `<third-party
attestations when available>`.

## 10. International transfers
`<SCCs / data-residency: for an egress-locked self-hosted deployment, data does
not leave the Controller's infrastructure — state the region here.>`
