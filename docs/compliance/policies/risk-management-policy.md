# Risk Management Policy

| Field | Value |
| --- | --- |
| Document ID | POL-02 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Effective date | TBD |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO 27001:2022 Clause 6.1, 8.2, 8.3, A.5.* governance; ISO 42001:2023 Clause 6.1, A.5.2, A.5.3; SOC 2 CC3.1–CC3.4 |

## 1. Purpose

This policy defines how the Organization identifies, assesses, treats, and monitors information
security risk and artificial-intelligence (AI) risk arising from the design, development,
operation, and use of the Maverick platform. It establishes a consistent, repeatable
methodology so that risk decisions are comparable, defensible, and traceable to control
selection in the Statement of Applicability (SoA).

It is a subordinate policy under the Information Security Policy (POL-01) and operationalizes
ISO/IEC 27001:2022 Clause 6.1 (actions to address risks and opportunities), Clauses 8.2/8.3
(risk assessment and treatment), and ISO/IEC 42001:2023 Clause 6.1 together with its
AI-specific risk and impact-assessment controls.

## 2. Scope

This policy applies to all information security and AI risks within the ISMS/AIMS scope defined
in POL-01, including:

- Risks to confidentiality, integrity, and availability of information assets.
- Risks introduced by Maverick acting as an autonomous/agentic system — including risks from
  tool execution, capability escalation, and emergent agent behavior.
- AI-specific risks: harms to individuals or groups, fairness and bias, transparency,
  robustness, and regulatory classification (e.g. EU AI Act risk tiers).

It applies to all personnel, contractors, and third parties involved in risk-bearing
activities, and to all environments in scope.

## 3. Policy statements

3.1 The Organization maintains a documented risk-assessment methodology defining risk criteria,
likelihood and impact scoring, and risk-acceptance thresholds. The methodology is recorded at
`docs/compliance/risk-management-methodology.md` (authored in parallel).

3.2 Risks are recorded, scored, and tracked to closure in a risk register maintained at
`docs/compliance/risk-register.md` (authored in parallel). Each risk entry references its
asset/scope, owner, score, treatment decision, and residual risk.

3.3 Risk is scored on a defined likelihood × impact scale. Risk criteria, scoring bands, and the
risk-acceptance (appetite/tolerance) thresholds are approved by management and documented in the
methodology. Risks above tolerance require treatment; risks within tolerance may be accepted with
recorded justification. **[Process — Organization to operationalize]**

3.4 Each assessed risk is treated using one of four options — mitigate (reduce), accept, transfer
(e.g. insurance/contract), or avoid (eliminate the activity). The selected option and rationale
are recorded in the risk register.

3.5 Risk treatment decisions drive control selection. Mitigation controls are mapped to framework
controls and reflected in the Statement of Applicability; inclusions and exclusions in the SoA
are justified by reference to the risk register. **[Process — Organization to operationalize]**

3.6 AI-specific risk is assessed in addition to, and integrated with, information-security risk.
For AI systems and material capability changes, an AI system impact assessment is performed per
ISO/IEC 42001:2023 Clause 6.1 and controls A.5.2/A.5.3, covering impacts on individuals, society,
fairness, and regulatory classification.

3.7 Maverick capabilities carry a risk classification, and tool execution is bounded by maximum
risk ceilings so that the platform cannot exceed an approved risk tolerance at runtime. Tools are
classified low/medium/high and gated accordingly.

3.8 The EU AI Act risk classification of AI use cases is determined and recorded so that
regulatory obligations are identified early and feed the broader risk assessment.

3.9 Risks are reviewed on a defined cadence and re-assessed on significant change (new capability,
new integration, incident, or regulatory change). Residual risk is monitored continuously.
**[Process — Organization to operationalize]**

3.10 Risk acceptance above the defined appetite requires explicit management approval, which is
recorded in the risk register.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| Management / CEO | Approves risk criteria and risk appetite; accepts residual risks above tolerance. **[Process — Organization to operationalize]** |
| CISO / Security Lead | Owns this policy and the risk process; maintains the methodology, register, and SoA linkage; coordinates assessments. |
| Risk / AI governance owner | Performs AI system impact assessments and EU AI Act classification; maintains AI risk entries. **[Process — Organization to operationalize]** |
| Engineering | Implements and maintains technical risk controls (capability ceilings, tool-risk gating, assessment engine). |
| Risk owners | Own assigned risks, execute treatment, and report status. **[Process — Organization to operationalize]** |

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| Structured risk-assessment engine | `packages/maverick-core/maverick/assessment.py` | Implemented |
| EU AI Act risk classification | `packages/maverick-core/maverick/ai_act.py` | Implemented |
| AI Act classifier tool | `packages/maverick-core/maverick/tools/ai_act_classifier.py` | Implemented |
| AI Risk Assessment persona (IT GRC / AIRA) | `packages/maverick-core/maverick/domains/itgrc_aira.toml` | Implemented |
| Tool risk classification (low/medium/high) | `packages/maverick-core/maverick/safety/tool_risk.py` | Implemented |
| Capability max-risk ceilings | `packages/maverick-core/maverick/capability.py` | Implemented |
| Map risks to control frameworks | `find_controls_tool` in `packages/maverick-core/maverick/tools/control_tools.py` | Implemented |
| Risk methodology, register, SoA, appetite thresholds | `docs/compliance/risk-management-methodology.md`, `docs/compliance/risk-register.md` | Partial |
| Periodic risk review, management risk acceptance | Risk governance process (organizational) | Process |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 27001:2022 | Clause 6.1 (risks & opportunities); Clauses 8.2/8.3 (risk assessment & treatment); A.5.* governance controls |
| ISO/IEC 42001:2023 | Clause 6.1 (AI risk planning); A.5.2 (AI risk assessment); A.5.3 (AI system impact assessment) |
| SOC 2 | CC3.1–CC3.4 (Risk Assessment: objectives, risk identification, fraud, change) |

## 7. Exceptions & non-compliance

Exceptions to this policy — including acceptance of risks above the defined appetite — must be
documented, risk-assessed, time-bound, and approved by management, then recorded in the risk
register. **[Process — Organization to operationalize]**

Failure to follow the risk process (e.g. deploying a material capability change without an impact
assessment) is a policy violation handled per POL-01 Section 7 and, where it constitutes a
security event, the Incident Response Policy.

## 8. Review & maintenance

This policy, the risk methodology, and the risk register are reviewed at least annually and upon
significant change to the Organization, the Maverick platform, the threat or AI-harm landscape,
or applicable regulation (including EU AI Act developments). Review outcomes feed management
review under POL-01. The Owner maintains version history and SoA consistency.
**[Process — Organization to operationalize]**
