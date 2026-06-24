# Risk Management Methodology

| Field | Value |
| --- | --- |
| Document ID | RM-METH-01 |
| Owner | Security Lead / CISO |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual, and on significant change |
| Frameworks | ISO 27001:2022 Cl. 6.1, 8.2, 8.3; ISO 42001:2023 Cl. 6.1, A.5.2–A.5.5; SOC 2 CC3.1–CC3.4 |

This document defines how the Organization identifies, analyzes, evaluates,
treats, and monitors information-security **and** AI risk. It is the companion
to the [Risk Management Policy](policies/risk-management-policy.md) (POL-02) and
produces the [Risk Register](risk-register.md). It satisfies the ISO 27001
Clause 6.1 risk-assessment requirement and the ISO 42001 Clause 6.1 + AI impact
assessment requirement.

## 1. Scope of risk

Two interlocking risk domains:

- **Information-security risk** — threats to the confidentiality, integrity, and
  availability of information assets (the world-model DB, audit log, secrets/API
  keys, customer data, the platform itself).
- **AI risk** — risks arising from the behavior of the AI system: unsafe or
  unintended actions, prompt-injection compromise, model error, bias/unfairness,
  loss of human oversight, drift/regression from the learning loop, and impacts
  on affected third parties (per ISO 42001 and the EU AI Act).

## 2. Risk identification

Risks are identified from, and continuously fed by, existing sources:

| Source | Location |
| --- | --- |
| STRIDE threat model | `docs/security/threat-model.md` |
| External audit / pen-test readiness scope | `docs/security/audit-readiness.md` |
| SOC 2 control gaps | [`soc2-controls.md`](soc2-controls.md) |
| AI risk classification (EU AI Act / NIST AI RMF) | `maverick/ai_act.py`; `maverick/domains/itgrc_aira.toml` |
| Structured assessment engine output | `maverick/assessment.py` |
| Tool/action risk classification | `maverick/safety/tool_risk.py` |
| Incident post-mortems | Incident records (POL-07) |
| Vulnerability scans / dependency alerts | `.github/dependabot.yml`, CI |

Each identified risk is recorded in the [Risk Register](risk-register.md) with a
unique ID (`R-NN`).

## 3. Risk analysis: scoring

Each risk is scored on **Likelihood** and **Impact**, each 1–5:

**Likelihood**

| Score | Label | Meaning |
| --- | --- | --- |
| 1 | Rare | Not expected in normal operation |
| 2 | Unlikely | Could occur but no current indication |
| 3 | Possible | Plausible within a 12-month horizon |
| 4 | Likely | Expected to occur within 12 months |
| 5 | Almost certain | Expected to occur repeatedly |

**Impact**

| Score | Label | Meaning |
| --- | --- | --- |
| 1 | Negligible | No material harm |
| 2 | Minor | Limited, recoverable harm |
| 3 | Moderate | Notable harm; some customer/regulatory exposure |
| 4 | Major | Significant data loss, outage, or compliance breach |
| 5 | Severe | Critical breach, safety harm, or existential business impact |

**Risk score = Likelihood × Impact** (1–25), banded as:

| Band | Score | Action |
| --- | --- | --- |
| **Low** | 1–4 | Accept or monitor |
| **Medium** | 5–9 | Treat within the planning cycle |
| **High** | 10–15 | Treat with priority; management visibility |
| **Critical** | 16–25 | Immediate treatment; management/Board escalation |

Both **inherent** (pre-control) and **residual** (post-control) scores are
recorded so the effect of each control is visible.

## 4. Risk evaluation & appetite

The Organization's **risk appetite**:

- **Critical** and **High** residual risks are not acceptable and require an
  approved treatment plan with an owner and target date.
- **Medium** residual risks require a documented decision (treat or accept).
- **Low** residual risks may be accepted and monitored.

Risk acceptance above Medium requires sign-off by the risk owner and Management.
AI risks classified **high-risk** under the EU AI Act receive heightened scrutiny
regardless of computed score.

## 5. Risk treatment

For each risk above appetite, one or more options is selected:

| Option | Description |
| --- | --- |
| **Mitigate** | Apply/strengthen a control (most common; map to the [crosswalk](control-crosswalk.md)) |
| **Accept** | Formally accept within appetite, with sign-off |
| **Transfer** | Insurance, contractual, or third-party shifting |
| **Avoid** | Remove the activity/asset creating the risk |

Mitigation controls are linked to the relevant Annex A / TSC control in the
[Statement of Applicability](iso-27001/statement-of-applicability.md) and the
[crosswalk](control-crosswalk.md). This linkage is what connects the risk
assessment to the SoA, as ISO 27001 Clause 6.1.3 requires.

## 6. AI system impact assessment (ISO 42001 / EU AI Act)

In addition to the IS risk process, every materially new AI capability or
deployment context triggers an **AI system impact assessment** covering:

- Intended purpose, affected parties, and potential for harm.
- EU AI Act risk classification (prohibited / high-risk / limited / minimal) via
  `maverick/ai_act.py` and `maverick/tools/ai_act_classifier.py`.
- Human-oversight design (which actions require `REQUIRE_HUMAN`; see POL-12).
- Data provenance and quality for any learning input (fleet memory provenance).
- Fairness/bias considerations (`maverick/tools/bias_eval.py`).
- Transparency obligations (Art. 50 disclosure; right-to-explanation).

Results are recorded as `AIRA-NN` entries cross-referenced from the register.

## 7. Monitoring & review

- The register is reviewed at least **quarterly** and on significant change
  (new capability, incident, major architecture change).
- Risk treatment progress is reported to Management at each review.
- The methodology itself is reviewed annually as part of management review
  (ISO 27001 Cl. 9.3 / ISO 42001 Cl. 9.3).
- Continual-improvement actions (ISO 27001 Cl. 10 / ISO 42001 Cl. 10) are tracked
  to closure.

## 8. Roles

| Role | Responsibility |
| --- | --- |
| Risk owner | Owns a specific risk's treatment and residual acceptance |
| Security Lead / CISO | Maintains the methodology and register; facilitates assessments |
| AI/Responsible-AI Lead | Owns AI-specific risk and impact assessments |
| Management | Approves risk appetite, accepts residual risk above Medium, reviews quarterly |
