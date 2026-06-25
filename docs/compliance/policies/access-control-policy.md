# Access Control Policy

| Field | Value |
| --- | --- |
| Document ID | POL-03 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO 27001:2022 A.5.15, A.5.16, A.5.17, A.5.18, A.8.2, A.8.3, A.8.5; ISO 42001:2023 A.4.x; SOC 2 CC6.1–CC6.3 |

## 1. Purpose

This policy establishes the requirements governing identity, authentication, and authorization for access to the Maverick platform, its administrative interfaces, its data stores, and the tools and capabilities it exposes to agents and operators. Its objective is to ensure that access is granted on the basis of verified identity, least privilege, and business need, and that access is reviewed and revoked in a timely manner. The policy supports the Organization's obligations under ISO/IEC 27001:2022, ISO/IEC 42001:2023, and SOC 2.

## 2. Scope

This policy applies to:

- All human users (administrators, operators, auditors, and viewers) of the Maverick dashboard, CLI, and MCP interfaces.
- All non-human / agent identities and the capabilities, tools, and resources they may invoke.
- All authentication and authorization components of the platform, including OIDC, SAML, reverse-proxy authentication, signed capabilities, and tool access-control lists.
- All deployments of Maverick operated by or on behalf of the Organization, across development, staging, and production environments.

**Critical deployment note:** Several access-control enforcement mechanisms in Maverick are opt-in and ship **off by default** (notably OIDC bearer enforcement and signed capability enforcement). A deployment is **not compliant** with this policy until these controls are explicitly enabled. See the Organization's SOC 2 turn-on guidance under `docs/compliance/soc2/`.

## 3. Policy statements

1. **Identity.** Every human user and every agent identity that accesses Maverick shall be uniquely identifiable. Shared or generic accounts are prohibited for administrative access.
2. **Authentication.** Interactive and programmatic access shall be authenticated. Where federated identity is available, the Organization shall use OIDC or SAML against the corporate identity provider. Bearer-token and capability enforcement shall be enabled in all production deployments.
3. **Authorization & least privilege.** Access shall be granted at the minimum level required to perform an assigned function. Agent tool/path/host access shall be constrained by signed, attenuating capabilities scoped to the narrowest necessary set and bounded by a maximum-risk ceiling and an expiry.
4. **Role-based access.** Human access shall be assigned through the platform's four defined roles — admin, operator, auditor, viewer — and not through ad-hoc privilege grants.
5. **Separation of duties.** The auditor role shall remain read-only and shall not hold operational or administrative privileges, preserving independence of review from operation. **[Process — Organization to operationalize]** the assignment of audit responsibilities to personnel distinct from those holding operator/admin roles.
6. **Privileged access.** Admin-role access shall be restricted to named individuals, granted on business need, and reviewed at least quarterly. **[Process — Organization to operationalize]** the quarterly privileged-access review and its evidence retention.
7. **Authentication information.** Tokens, OIDC/SAML credentials, and capability signing keys shall be protected, never embedded in source, and rotated on compromise or personnel change.
8. **Session management.** Browser sessions shall be established through the platform's OIDC login flow and session cookies; sessions shall expire and shall be invalidated on logout.
9. **De-provisioning.** Access shall be revoked promptly upon role change or separation. **[Process — Organization to operationalize]** the joiner/mover/leaver workflow and its target revocation SLA.
10. **Access review.** Entitlements shall be reviewed periodically for continued business need. **[Process — Organization to operationalize]** the periodic user-access recertification.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Management / Approver | Approves this policy; owns accountability for the access-control program. |
| Security Lead / CISO (Owner) | Maintains the policy; ensures enforcement controls are enabled; oversees reviews. |
| Platform / Operations | Configures OIDC/SAML, enables capability and bearer enforcement, manages role assignments. |
| Maverick admin role | Manages platform configuration and access within the dashboard. |
| Maverick auditor role | Read-only review of platform state and audit records; independent of operations. |
| All users | Comply with least-privilege and authentication requirements. |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Role-based access; separation of duties (4 roles, auditor read-only) | `packages/maverick-dashboard/maverick_dashboard/rbac.py` | Operational |
| Bearer-token auth gate (OIDC, alg-confusion hardened) | `packages/maverick-dashboard/maverick_dashboard/auth.py` | **Opt-in — default OFF; must enable** |
| Browser OIDC login + session cookies | `packages/maverick-dashboard/maverick_dashboard/oidc_login.py` | Opt-in — configure IdP |
| SAML SSO | `packages/maverick-dashboard/maverick_dashboard/saml.py` | Opt-in — configure IdP |
| ID-token verification | `packages/maverick-core/maverick/oidc.py` | **Opt-in — default OFF; must enable** |
| Reverse-proxy authentication | `packages/maverick-core/maverick/proxy_auth.py` | Opt-in — configure proxy |
| Signed attenuating capabilities (tool/path/host scopes, max_risk ceiling, expiry; least privilege by construction) | `packages/maverick-core/maverick/capability.py` | **Opt-in — default OFF; must enable** |
| Per-channel / per-user tool ACLs | `packages/maverick-core/maverick/safety/tool_acl.py` | Operational |
| OAuth for MCP | `packages/maverick-core/maverick/mcp_oauth.py` | Opt-in — configure |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.5.15 access control; A.5.16 identity management; A.5.17 authentication information; A.5.18 access rights; A.8.2 privileged access rights; A.8.3 information access restriction; A.8.5 secure authentication |
| ISO/IEC 42001:2023 | A.4.x (resources / access to AI system components and their controls) |
| SOC 2 | CC6.1 logical access controls; CC6.2 registration & authorization of users; CC6.3 role-based access & least privilege |

## 7. Exceptions & non-compliance

Any deployment that does not enable OIDC bearer enforcement and signed capability enforcement is non-compliant with this policy and shall not process production or regulated data until remediated. Exceptions require documented risk acceptance approved by the Owner and Management, with a defined expiry. **[Process — Organization to operationalize]** the exception register and approval workflow. Violations may result in revocation of access and disciplinary action.

## 8. Review & maintenance

This policy shall be reviewed at least annually and upon any significant change to Maverick's authentication or authorization architecture, to the identity provider, or to the threat environment. The Owner is responsible for initiating review and recording approval.
