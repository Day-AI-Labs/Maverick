# Supplier Security Policy

| Field | Value |
| --- | --- |
| Document ID | POL-09 |
| Owner | Head of Security |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Effective date | TBD |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 27001:2022 A.5.19, A.5.20, A.5.21, A.5.22, A.5.23; ISO/IEC 42001:2023 A.10.2, A.10.3, A.7.x; SOC 2 CC9.2 |

## 1. Purpose

This policy establishes the requirements for identifying, assessing,
contracting with, monitoring, and offboarding suppliers, vendors, and
sub-processors that support Maverick — the Organization's governed agentic
enterprise AI platform — and for maintaining the integrity of the software
supply chain that feeds the platform. It exists to ensure that third parties
who process the Organization's or its customers' data, or who supply software,
infrastructure, models, or services into Maverick, do so under appropriate
security and privacy controls, and that supply-chain risk is managed across the
relationship lifecycle. Maverick processes data through external Large Language
Model (LLM) providers and infrastructure vendors; these dependencies are a
material source of third-party risk and are addressed directly here. The policy
provides assurance for SOC 2, ISO/IEC 27001:2022, and ISO/IEC 42001:2023
audits.

## 2. Scope

This policy applies to:

- All suppliers and vendors that provide software, hardware, cloud
  infrastructure, AI/LLM model services, professional services, or support to
  the Organization in connection with Maverick.
- All sub-processors that process customer or personal data on the
  Organization's behalf, including LLM providers and infrastructure/hosting
  providers.
- The Information and Communication Technology (ICT) supply chain that supplies
  code, dependencies, plugins, packs, Model Context Protocol (MCP) tools, and
  external agent contributions into the Maverick monorepo and runtime.
- All personnel who select, onboard, contract with, integrate, or monitor
  suppliers.

It covers both the **process** controls that the Organization operates
(assessments, contracts, inventories, monitoring) and the **technical**
supply-chain integrity controls that exist in the Maverick codebase.

## 3. Policy statements

1. **Risk-based assessment before onboarding.** No supplier or sub-processor
   that will process Organization or customer data, or supply software or
   services into Maverick, shall be onboarded before a security and privacy
   risk assessment proportionate to the data sensitivity and criticality of the
   service has been completed and recorded. **[Process — Organization to
   operationalize]**
2. **Contractual security requirements.** Supplier agreements shall include
   security, confidentiality, data-protection, breach-notification, audit, and
   sub-processing terms. Where personal data is processed, a Data Processing
   Agreement (DPA) shall be executed using the Organization's template prior to
   processing. **[Process — Organization to operationalize]**
3. **Sub-processor inventory.** A current inventory of sub-processors —
   including LLM providers and infrastructure vendors — shall be maintained,
   recording the service provided, data categories processed, and processing
   location, and shall be made available to customers as required by contract.
   **[Process — Organization to operationalize]**
4. **Ongoing monitoring.** Supplier security posture and service performance
   shall be monitored throughout the relationship, with periodic
   re-assessment, and material changes (new sub-processors, breaches, certificate
   lapses) shall trigger review. **[Process — Organization to operationalize]**
5. **Cloud and LLM service security.** Use of cloud services and external model
   providers shall be governed by the same assessment, contractual, and
   monitoring requirements, with attention to data residency, training-data
   use, retention, and tenant isolation.
6. **ICT supply-chain integrity.** Code, dependencies, plugins, packs, MCP
   tools, and external agent contributions entering Maverick shall be subject
   to the platform's integrity controls — allowlisting, hash-pinning, content
   scanning, provenance tagging, and automated dependency monitoring — so that
   untrusted or tampered supply-chain inputs are denied or flagged by default.
7. **Default-deny for executable supply-chain inputs.** Plugins and MCP tools
   are denied by default and admitted only through explicit allowlisting plus
   integrity verification; this default shall not be weakened without a
   documented risk acceptance.
8. **Offboarding.** On supplier termination, access shall be revoked, data
   return or deletion confirmed, and the sub-processor inventory updated.
   **[Process — Organization to operationalize]**

## 4. Roles & responsibilities

- **Management** — approves this policy, owns supplier-risk acceptance, and
  approves onboarding of high-risk suppliers and sub-processors.
- **Head of Security (Owner)** — maintains this policy and the supplier
  assessment process; reviews assessment outcomes; oversees supply-chain
  integrity controls.
- **Legal / Data Protection** — owns DPA, SLA, and contractual templates and
  ensures security and data-protection clauses are executed.
- **Procurement / Business owner** — initiates assessments, maintains the
  supplier and sub-processor inventory, and triggers re-assessment.
- **Head of Engineering** — operates the technical supply-chain integrity
  controls (plugin/MCP allowlisting, hash-pinning, scanning, dependency
  monitoring) and reviews their findings.
- **All personnel** — engage suppliers only through the approved process and do
  not introduce unassessed third-party services or supply-chain inputs.

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| MCP command hash-pinning and tool-description scanning at registration | `packages/maverick-core/maverick/mcp_oauth.py`; MCP tool registration path | Implemented |
| Plugin default-deny via allowlist (`MAVERICK_PLUGINS_ALLOW`) + skill-body scan + hash-pin at install | `packages/maverick-core/maverick/plugin_manifest.py` | Implemented |
| Provenance tagging (`vendor:agent_id`) of external agent contributions | `packages/maverick-core/maverick/fleet_memory.py` | Implemented |
| Automated dependency monitoring / update alerting | `.github/dependabot.yml` | Implemented |
| DPA template for sub-processor agreements | `docs/enterprise/legal/dpa-template.md` | Implemented (template) |
| SLA template for supplier service levels | `docs/enterprise/legal/sla-template.md` | Implemented (template) |
| Sub-processor inventory (customer-facing) | `docs/enterprise/legal/subprocessors.md` | Implemented (template/register) |
| Supplier security assessment before onboarding | Vendor security review procedure | **[Process — Organization to operationalize]** |
| Signed DPAs executed before processing | Contracting procedure | **[Process — Organization to operationalize]** |
| Maintained, current sub-processor inventory | Inventory maintenance procedure | **[Process — Organization to operationalize]** |
| Periodic supplier re-assessment and monitoring | Ongoing monitoring procedure | **[Process — Organization to operationalize]** |
| Supplier offboarding (access revocation, data return) | Offboarding procedure | **[Process — Organization to operationalize]** |

Most controls in this policy are **Organization processes**. The
codebase provides software supply-chain *integrity* controls (the first four
rows above) and the contractual *templates* (the next three); the assessment,
contracting, inventory, monitoring, and offboarding controls are operated by
the Organization outside the code and are marked accordingly.

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | A.5.19 (information security in supplier relationships); A.5.20 (addressing security within supplier agreements); A.5.21 (managing information security in the ICT supply chain); A.5.22 (monitoring, review and change management of supplier services); A.5.23 (information security for use of cloud services) |
| ISO/IEC 42001:2023 | A.10.2 / A.10.3 (allocation of responsibilities and information for third parties and customers across the AI lifecycle); A.7.x (data provenance and management of data obtained from suppliers) |
| SOC 2 | CC9.2 (assessment and management of risks associated with vendors and business partners) |

## 7. Exceptions & non-compliance

Exceptions to this policy require a documented risk assessment and Management
approval, recorded with a defined expiry and compensating controls. Weakening
the plugin/MCP default-deny posture or onboarding a sub-processor without an
assessment are treated as exceptions requiring explicit risk acceptance.
Non-compliance — including engaging unassessed suppliers or processing data
without an executed DPA — may result in supplier offboarding, remediation, and
disciplinary action under the Human Resources Security Policy (POL-10).

## 8. Review & maintenance

This policy is reviewed at least annually and on significant change (new
material sub-processor, change in LLM provider, a supplier security incident,
or a change to the supply-chain integrity controls). The Owner is responsible
for review; Management approves material changes. Review outcomes and the
current supplier and sub-processor inventories are retained as audit evidence.
