# Statement of Applicability (SoA) — ISO/IEC 42001:2023

| Field | Value |
| --- | --- |
| Document ID | AIMS-SOA-01 |
| Owner | AI / Responsible-AI Lead |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Standard | ISO/IEC 42001:2023, Annex A (controls A.2–A.10) |

This SoA records, for each ISO 42001 Annex A control: **Applicability**,
**justification**, **implementation status**, and **evidence**. Determinations
are driven by the [risk register](../risk-register.md) (AI risks R-19…R-25) and
[methodology](../risk-management-methodology.md) (incl. AI impact assessment).

**Status:** Implemented · Partial · Process · Gap. **Applicable:** Y / N.

> Summary: all controls **Applicable**. Strengths concentrate in A.6 (lifecycle),
> A.7 (data), and A.9 (human oversight). Two **Gaps**: model-card metadata export
> and AI-system retirement.

## A.2 Policies related to AI

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.2.2 | AI policy | Y | Process (drafted) | [POL-12](../policies/ai-management-policy.md) |
| A.2.3 | Alignment with other organizational policies | Y | Process | POL-12 cross-references POL-01…POL-11 + [crosswalk](../control-crosswalk.md) |
| A.2.4 | Review of the AI policy | Y | Process | Annual review (POL-12 §8); management review Cl. 9.3 |

## A.3 Internal organization

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.3.2 | AI roles & responsibilities | Y | Process | POL-12 §4; AI Lead role defined |
| A.3.3 | Reporting of concerns | Y | Implemented + Process | `maverick/issue_report.py`; `SECURITY.md`; concern channel is Process |

## A.4 Resources for AI systems

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.4.2 | Resource documentation | Y | Partial | Model/tool/data resources documented in `docs/`; to consolidate |
| A.4.3 | Data resources | Y | Implemented | World model + fleet memory; provenance-tagged (`world_model.py`, `fleet_memory.py`) |
| A.4.4 | Tooling resources | Y | Implemented | Tool registry, ACLs, risk classification (`safety/tool_acl.py`, `tool_risk.py`) |
| A.4.5 | System & computing resources | Y | Implemented | Sandbox backends; budget/quota/concurrency caps |
| A.4.6 | Human resources (competence) | Y | Process | AI competence/awareness (POL-10, POL-12) |

## A.5 Assessing impacts of AI systems

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.5.2 | AI system impact assessment process | Y | Implemented | EU AI Act classifier + AIRA (`ai_act.py`, `domains/itgrc_aira.toml`); [methodology §6](../risk-management-methodology.md) |
| A.5.3 | Documentation of impact assessments | Y | Partial | AIRA outputs recorded; `AIRA-NN` register entries to formalize |
| A.5.4 | Impact on individuals or groups | Y | Implemented | Bias/fairness metrics (`tools/bias_eval.py`); right-to-explanation |
| A.5.5 | Societal impacts | Y | Partial | EU AI Act high-risk classification; societal-impact section in AIRA |

## A.6 AI system life cycle

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.6.1.2 | Objectives for responsible development | Y | Implemented | Verifier/anti-cheating; safety-by-default; POL-12 |
| A.6.1.3 | Processes for responsible design & development | Y | Implemented | Secure-dev (POL-06); threat model; Shield in the loop |
| A.6.2.2 | AI system requirements & specification | Y | Partial | Capability/governance specs; POL-12 |
| A.6.2.3 | Documentation of design & development | Y | Partial | `docs/`; invention disclosures `docs/patents/`; to consolidate per-system |
| A.6.2.4 | Verification & validation | Y | Implemented | Snapshot-replay regression (`hindsight.py`); calibration gating (`calibration.py`); eval-gated CI |
| A.6.2.5 | Deployment | Y | Implemented | Staged rollout 10/50/100% with signed audit (`learning_rollout.py`) |
| A.6.2.6 | Operation & monitoring | Y | Implemented (partial fairness) | OpenTelemetry, health, circuit breakers; bias metrics on-demand (continuous = R-22) |
| A.6.2.7 | Technical documentation | Y | Implemented | Usage cards + operator-declared metadata (intended use, limitations, oversight, evals) exported via `model_cards.py` (`ModelCardMetadata`, `export_model_cards`) |
| A.6.2.8 | Recording of event logs | Y | Implemented | Signed, chained audit log (`audit/`); learning audit; `AI_SYSTEM_RETIRED` events |
| A.6.2 (retirement) | AI system retirement / decommissioning | Y | Implemented | Governed retirement with data disposition + signed `AI_SYSTEM_RETIRED` audit record (`retirement.py`); procedure in [POL-12](../policies/ai-management-policy.md) |

## A.7 Data for AI systems

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.7.2 | Data for development & enhancement | Y | Implemented | Learning inputs via governed fleet memory; `training/ingest.py` |
| A.7.3 | Acquisition of data | Y | Implemented | Schema-validated, size-capped, Shield-scanned ingest (`fleet_memory.py`) |
| A.7.4 | Quality of data | Y | Partial | Validation + secret/PII redaction at ingest; quality metrics (freshness/contamination) to surface |
| A.7.5 | Data provenance | Y | Implemented | Provenance tagging `vendor:agent_id`; audited recall (`fleet_memory.py`) |
| A.7.6 | Data preparation | Y | Implemented | Redaction, normalization, injection-marker guard (`memory_guard.py`) |

## A.8 Information for interested parties of AI systems

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.8.2 | System documentation & information for users | Y | Implemented | User docs; right-to-explanation; model-card metadata export (`export_model_cards`) |
| A.8.3 | External reporting | Y | Implemented | Art.50 first-turn disclosure (`compliance.py`) |
| A.8.4 | Communication of incidents | Y | Process | AI-incident communication procedure (POL-07) |
| A.8.5 | Information for interested parties | Y | Implemented | Disclosure + DSAR + right-to-explanation/rectification |

## A.9 Use of AI systems

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.9.2 | Processes for responsible use | Y | Implemented | Governance engine ALLOW/DENY/REQUIRE_HUMAN; consent gates (`governance.py`, `consent.py`) |
| A.9.3 | Objectives for responsible use | Y | Process | POL-12 objectives; risk ceilings |
| A.9.4 | Intended use of the AI system | Y | Implemented + Process | Tool ACLs, risk ceilings, capability scoping enforce intended use; documented purpose is Process |

## A.10 Third-party & customer relationships

| Control | Title | Appl. | Status | Justification / evidence |
| --- | --- | --- | --- | --- |
| A.10.2 | Allocating responsibilities | Y | Process | Provider/operator/customer responsibilities (POL-09; DPA templates) |
| A.10.3 | Suppliers | Y | Implemented + Process | MCP/plugin hash-pinning + provenance; vendor reviews are Process (POL-09) |
| A.10.4 | Customers | Y | Implemented + Process | Customer data isolation, DSAR, disclosure; contractual terms are Process (SLA/DPA) |

---

## Exclusions

**None.** All ISO 42001:2023 Annex A controls are determined Applicable. The two
former **Gap** items — A.6.2.7 model-card metadata export (R-25) and AI-system
retirement (R-24) — are now **Implemented** (`model_cards.py`, `retirement.py`).
The one remaining partial item is continuous fairness monitoring (R-22), tracked
in the [risk register](../risk-register.md) and the [roadmap](README.md) for
closure before the Stage 2 audit.
