# ISO/IEC 27001:2022 — ISMS Overview & Roadmap

This is the ISO 27001 workstream entry point. ISO 27001 certifies an
**Information Security Management System (ISMS)**: the management system
(Clauses 4–10) plus the Annex A controls. Maverick's technical controls cover a
large share of Annex A; the remaining work is the management-system
documentation and the organizational (Process) controls.

## 1. ISMS scope (Clause 4.3)

**In scope:** the Maverick agentic platform (kernel, shield, channels,
dashboard, MCP server, evolve, knowledge), its audit and world-model data
stores, the build/release pipeline, and the company processes that operate and
support it.

**Boundaries & interfaces:** LLM provider APIs, cloud hosting/infrastructure
(physical and environmental controls inherited and evidenced via the provider's
own SOC 2 / ISO 27001 reports), and customer-managed deployment environments.

**Information assets:** world-model DB, audit log (the Operating Record),
secrets/API keys, customer data processed by agents, fleet memory, source code,
and the model-selection configuration.

The formal scope statement is approved by Management and recorded in the ISMS
scope register (to be ratified at the first management review).

## 2. Mandatory ISMS documents (Clauses 4–10)

ISO 27001 requires specific documented information. Status:

| Clause | Required document | Where | Status |
| --- | --- | --- | --- |
| 4.3 | ISMS scope | This README §1 | Draft |
| 5.2 | Information Security Policy | [POL-01](../policies/information-security-policy.md) | Draft |
| 5.3 | Roles & responsibilities | POL-01 §4; org chart | Draft / Process |
| 6.1.2 | Risk assessment process | [methodology](../risk-management-methodology.md) | Draft |
| 6.1.3 | Risk treatment process + **SoA** | [SoA](statement-of-applicability.md) | Draft |
| 6.2 | Information security objectives | This README §3 | Draft |
| 6.1.2 | Risk assessment results | [register](../risk-register.md) | Draft |
| 6.1.3 | Risk treatment plan | register (treatment column) | Draft |
| 7.2 | Competence evidence | HR records | **Process** |
| 7.5 | Documented information control | This `docs/compliance/` tree + git | Implemented |
| 8.1 | Operational planning & control | Policies POL-03…POL-12 | Draft |
| 9.1 | Monitoring & measurement | `maverick/observability.py`; evidence collector | Partial |
| 9.2 | Internal audit programme | Internal audit plan | **Process — Gap** |
| 9.3 | Management review | Management review minutes | **Process — Gap** |
| 10.1 | Nonconformity & corrective action | Corrective-action log | **Process — Gap** |
| 10.2 | Continual improvement | Improvement backlog | Partial |

## 3. Information security objectives (Clause 6.2)

Initial measurable objectives (refined at management review):

1. All required opt-in controls `enabled` in production (target: 100%; measure
   via the evidence collector).
2. Zero unresolved High/Critical residual risks beyond their target date.
3. 100% of staff complete annual security awareness training.
4. Critical/High vulnerabilities remediated within policy SLA.
5. Audit-log chain verifies cleanly (`audit_log = ok`) on every check.

## 4. Annex A coverage summary

The full control-by-control determination is in the
[Statement of Applicability](statement-of-applicability.md). Headline coverage
of the 93 Annex A:2022 controls:

| Theme | Controls | Predominant status |
| --- | --- | --- |
| A.5 Organizational (37) | 37 | Mixed — strong on access/audit; supplier & IR are Process |
| A.6 People (8) | 8 | **Process** (HR security — see POL-10) |
| A.7 Physical (14) | 14 | **Process** — inherited from cloud provider |
| A.8 Technological (34) | 34 | **Strong** — Maverick's core strength |

## 5. Gap analysis

**Strong (Implemented):** logical access control, cryptography, audit logging,
secure isolation, data protection/privacy, monitoring, capacity & resilience,
supply-chain integrity, threat protection.

**Must enable (Implemented, opt-in):** capabilities, tenant isolation, quotas,
OIDC, encryption at rest, audit signing.

**Process gaps (organizational):** HR security (A.6), physical security (A.7,
cloud-inherited), supplier management (A.5.19–23), incident-response programme
(A.5.24–28), and the management-system clauses 9.2 / 9.3 / 10.1 (internal audit,
management review, corrective action).

## 6. Certification roadmap

Per `docs/research/commercialization/07-trust-certifications-roadmap.md`,
ISO 27001 is ~6–10 months and largely reuses the SOC 2 backbone.

1. **Readiness (months 0–3):** approve policies; ratify scope; populate and
   review the risk register; enable opt-in controls; close the highest-priority
   Process gaps; stand up internal audit + management review cadences.
2. **Internal audit + management review (month 3–4):** run a full internal audit
   against the SoA; hold the first management review; remediate nonconformities.
3. **Stage 1 audit (certification body):** documentation review (ISMS docs, SoA,
   risk assessment).
4. **Stage 2 audit:** on-site/operational audit of control effectiveness.
5. **Certification + surveillance:** annual surveillance audits; 3-year
   recertification.

Once certified, [ISO 42001](../iso-42001/README.md) stacks on top at ~30–50%
lower marginal cost.
