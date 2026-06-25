# AI Management Policy

| Field | Value |
| --- | --- |
| Document ID | POL-12 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Effective date | 2026-06-24 |
| Review cycle | Annual (or on significant change) |
| Frameworks | ISO/IEC 42001:2023 Clause 5.2, A.2.2, A.2.3, A.5.x, A.6.x, A.8.x, A.9.x; EU AI Act Art. 12, 14, 50; SOC 2 PI1.x |

## 1. Purpose

This is the top-level AI Management Policy of the Organization, establishing the AI Management System (AIMS) mandated by ISO/IEC 42001:2023 Clause 5.2. It is the AIMS analogue of the Information Security Policy. It states the Organization's commitment to responsible and trustworthy AI and sets the governing principles for the AI system lifecycle, human oversight, transparency to affected parties, AI risk and impact assessment, fairness, model selection and management, and the governed continuous-learning loop. It directs and supports all subordinate AI controls and procedures across Maverick.

## 2. Scope

This policy applies to all AI systems designed, developed, deployed, operated, or retired by the Organization through Maverick — including the specialist packs, the learning lifecycle, fleet/shared memory, and all model invocations. It covers the full lifecycle (design → data → deploy → monitor → retire), all personnel and automated agents, all tenants, and all environments. It binds the use of third-party foundation models accessed through Maverick's role-based model layer.

## 3. Policy statements

1. **Commitment to responsible AI.** The Organization is committed to developing and operating AI that is lawful, safe, fair, transparent, accountable, and subject to meaningful human control. This commitment is endorsed by Management and communicated across the organization.
2. **Lifecycle governance (A.6.x).** Every AI system shall be governed across its lifecycle — design, data, deployment, monitoring, and retirement — with defined controls and records at each stage.
3. **Human oversight (EU AI Act Art. 14; A.9.x).** AI actions shall be subject to a policy-driven oversight gate. High- and critical-risk actions shall fail closed to human review in enterprise mode; sensitive actions may require two-person approval.
4. **Transparency to affected parties (EU AI Act Art. 50; A.8.x).** Affected parties shall be informed when they are interacting with an AI system, and material limitations shall be disclosed. Affected parties may request an explanation of AI-driven outcomes.
5. **AI risk & impact assessment (A.5.x).** AI systems shall be classified by risk and subjected to an AI impact assessment proportionate to that risk before deployment and on significant change. **[Process — Organization to operationalize]** the documented AI impact-assessment procedure and risk acceptance records.
6. **Bias & fairness.** AI systems shall be evaluated for bias using objective measures (e.g. the four-fifths rule, demographic parity), and material disparities shall be remediated or risk-accepted by Management. **[Process — Organization to operationalize]** the fairness evaluation cadence and acceptance thresholds.
7. **Model selection & management.** Models shall be selected by role through the governed configuration layer; models shall never be hard-coded. Each model in use shall have a usage/model card describing its role.
8. **Governed continuous learning.** Self-improvement shall occur only through the governed learning lifecycle: candidate generation, regression detection via snapshot-replay, calibration gating, staged rollout, and signed audit. No learning change reaches full production without passing these gates.
9. **Record-keeping (EU AI Act Art. 12).** AI decisions, oversight actions, and learning changes shall be recorded in a tamper-evident, cryptographically signed audit chain.
10. **Security of AI.** AI systems shall be defended against prompt injection, data exfiltration, and jailbreak attempts, and exercised against a red-team corpus.
11. **AI system retirement.** Each AI system shall be retired through the governed retirement flow (`maverick/retirement.py`), recording the reason, the deciding party, an explicit data disposition (retain/archive/erase), and a signed `AI_SYSTEM_RETIRED` audit record. The `erase` disposition performs concrete subject-scoped deletion (audit `delete_user` + world `delete_facts_matching`) when an `erase_scope` names the subject(s); supplying that scope from the system→data map is **[Process — Organization to operationalize]**.

## 4. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| AI Governance Lead (AIMS Owner) | Owns this policy and the AIMS; chairs AI risk review; approves model cards and learning rollouts. |
| Management | Endorses the responsible-AI commitment; approves this policy; accepts residual AI risk. |
| Engineering | Implements and maintains the lifecycle, oversight, learning, and security controls in Section 5. |
| Human Reviewers / Approvers | Exercise oversight on REQUIRE_HUMAN and high/critical actions; perform two-person approvals. |
| Data Protection Officer (DPO) | Coordinates with this policy on AI data privacy (see POL-11). |

**[Process — Organization to operationalize]** named individuals/teams and the AI governance forum cadence.

## 5. Technical implementation in Maverick

| Control | Implementation (file/module) | Status |
| --- | --- | --- |
| EU AI Act risk classification | `packages/maverick-core/maverick/ai_act.py` | Implemented |
| Art. 50 first-turn AI disclosure | `packages/maverick-core/maverick/compliance.py` | Implemented |
| ALLOW/DENY/REQUIRE_HUMAN policy engine (human-oversight gate) | `packages/maverick-core/maverick/governance.py` | Implemented |
| Consent / HITL gating (high/critical fail-closed to ask in enterprise mode) | `packages/maverick-core/maverick/safety/consent.py` | Implemented |
| Two-person approval | `packages/maverick-core/maverick/approval_delegation.py` | Implemented |
| Role-based model selection (no hard-coded models; kernel rule 2) | `packages/maverick-core/maverick/llm.py`, `packages/maverick-core/maverick/config.py` (`get_role_model`) | Implemented |
| Per-model usage cards + operator-declared metadata export | `packages/maverick-core/maverick/model_cards.py` (`ModelCardMetadata`, `export_model_cards`) | Implemented |
| Learning: candidate generation (dreaming) | `packages/maverick-core/maverick/dreaming.py` | Implemented |
| Learning: snapshot-replay regression detection | `packages/maverick-core/maverick/hindsight.py` | Implemented |
| Learning: staged 10%/50%/100% rollout with signed audit | `packages/maverick-core/maverick/learning_rollout.py` | Implemented |
| Learning: calibration-gated promotion | `packages/maverick-core/maverick/calibration.py` | Implemented |
| Ed25519 signed learning audit (Art. 12 record-keeping) | `packages/maverick-core/maverick/audit/signing.py` | Implemented |
| Governed shared memory with provenance | `packages/maverick-core/maverick/fleet_memory.py` | Implemented |
| Bias / fairness evaluation (four-fifths, demographic parity) — on-demand | `packages/maverick-core/maverick/tools/bias_eval.py` | Implemented |
| Continuous fairness monitoring (rolling window; four-fifths breach + drift; signed `FAIRNESS_ALERT`) | `packages/maverick-core/maverick/fairness_monitor.py` | Implemented |
| Right-to-explanation | `packages/maverick-core/maverick/tools/right_to_explanation.py` | Implemented |
| Prompt-injection / exfil / jailbreak detection + red-team corpus | `maverick-shield` package | Implemented |
| Model-card metadata export (intended use / limitations / oversight / eval results) | `packages/maverick-core/maverick/model_cards.py` | Implemented |
| Governed AI-system retirement with signed `AI_SYSTEM_RETIRED` audit record | `packages/maverick-core/maverick/retirement.py`; `packages/maverick-core/maverick/audit/events.py` | Implemented |

## 6. Framework control mapping

| Framework | Controls satisfied |
| --- | --- |
| ISO/IEC 42001:2023 | Clause 5.2, A.2.2, A.2.3 (AI policy — this document); A.5.x (impact assessment — `ai_act.py` risk classification + impact-assessment process); A.6.x (lifecycle — governed design→data→deploy→monitor→retire, incl. governed retirement with signed audit record); A.8.x (information for interested parties / transparency — Art. 50 disclosure, right-to-explanation, model cards); A.9.x (responsible use & human oversight — governance engine, consent/HITL, two-person approval) |
| EU AI Act | Art. 12 (record-keeping — signed audit chain); Art. 14 (human oversight — REQUIRE_HUMAN gate, fail-closed high/critical); Art. 50 (transparency — first-turn AI disclosure) |
| SOC 2 | PI1.x (processing integrity — governed, gated, and audited learning lifecycle; regression detection; calibration gating) where relevant |

## 7. Exceptions & non-compliance

Exceptions to this policy require a documented AI risk assessment and written approval from the AI Governance Lead and Management, with a defined expiry and compensating controls. Bypassing the human-oversight gate, the learning-lifecycle gates, or the signed audit is prohibited absent such an approved exception.

The two formerly-tracked AI build gaps are now **closed**:

1. **Model-card metadata export** — `model_cards.py` exports operator-declared
   metadata (intended use, out-of-scope use, limitations, risk classification,
   data provenance, human oversight, ethical considerations, eval results)
   merged into the usage cards (`ModelCardMetadata`, `export_model_cards`). The
   metadata content is operator-declared, so its accuracy remains an
   organizational responsibility. (R-25 closed.)
2. **AI-system retirement procedure** — `maverick/retirement.py` provides a
   governed, fail-safe retirement flow with an explicit data disposition
   (retain/archive/erase) and a signed `AI_SYSTEM_RETIRED` audit record. The
   `erase` disposition is wired to concrete subject-scoped deletion (audit
   `delete_user` + world `delete_facts_matching`), gated on an explicit
   `erase_scope` so retirement can never over-delete; supplying that scope from
   the system→data map remains **[Process — Organization to operationalize]**. (R-24 closed.)

A continuous fairness monitor (`maverick/fairness_monitor.py`) raises a signed
`FAIRNESS_ALERT` on a four-fifths breach or drift, closing the former
continuous-monitoring gap (R-22).

Non-compliance may result in remediation, suspension of the affected AI
capability, and disciplinary action.

## 8. Review & maintenance

This policy is reviewed at least annually and upon any significant change to AI systems, models in use, the learning lifecycle, or applicable AI regulation (including EU AI Act developments). The AI Governance Lead maintains the policy and tracks the Section 7 gaps to closure; Management approves material changes. Each review shall confirm that the file/module references in Section 5 remain accurate and that the gap list reflects current state.
