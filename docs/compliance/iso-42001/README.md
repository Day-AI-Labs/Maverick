# ISO/IEC 42001:2023 — AIMS Overview & Roadmap

This is the ISO 42001 workstream entry point. ISO 42001 certifies an **Artificial
Intelligence Management System (AIMS)**: the management system (Clauses 4–10,
structurally parallel to ISO 27001) plus the AI-specific Annex A controls
(A.2–A.10). It is designed to **stack on a certified ISO 27001 ISMS**, reusing
the same management-system backbone at ~30–50% lower marginal cost.

This is the standard where Maverick is most differentiated: the governed
learning loop, signed learning audit, fleet-memory provenance, and human-oversight
engine are AI-governance controls most platforms do not ship.

## 1. AIMS scope (Clause 4.3)

**In scope:** Maverick as an AI system and platform — the agent kernel and
orchestration, model selection/routing, the Agent Shield, the governed
self-improvement ("evolve") loop, fleet memory, and the human-oversight and
transparency surfaces. The Organization acts as both **AI developer** and **AI
provider/operator** under ISO 42001's role model.

**Interested parties:** end users, deploying customers, individuals affected by
agent decisions, LLM providers, and regulators (EU AI Act).

## 2. AI policy & objectives (Clauses 5.2, 6.2)

- **AI policy:** [POL-12 AI Management Policy](../policies/ai-management-policy.md)
  — the AIMS mandate (responsible/trustworthy AI commitment, lifecycle, human
  oversight, transparency, AI risk, bias, model management, governed learning).
- **Objectives (initial):** (1) every consequential action class has a defined
  human-oversight disposition; (2) Art.50 disclosure active on all user-facing
  surfaces; (3) zero unreviewed learning promotions (all staged + signed);
  (4) fairness metrics run on in-scope decisioning; (5) data provenance recorded
  for all learning inputs.

## 3. Annex A coverage summary

The control-by-control determination is in the
[Statement of Applicability](statement-of-applicability.md).

| Objective | Predominant status |
| --- | --- |
| A.2 AI policies | Process (POL-12 drafted) |
| A.3 Internal organization | Implemented + Process |
| A.4 Resources for AI | Implemented |
| A.5 Assessing AI impacts | Implemented |
| A.6 AI system life cycle | **Strong** — incl. governed retirement |
| A.7 Data for AI systems | **Strong** (provenance, quality, privacy) |
| A.8 Information for interested parties | Implemented |
| A.9 Use of AI systems | **Strong** (human oversight) |
| A.10 Third-party & customer relationships | Implemented + Process |

## 4. Gap analysis

**Differentiated strengths (Implemented):** governed AI lifecycle (dreaming,
hindsight snapshot-replay regression, staged rollout, calibration gating, atomic
rollback), Ed25519 signed learning audit, fleet-memory provenance & scope
gating, human-oversight engine (ALLOW/DENY/REQUIRE_HUMAN), Art.50 transparency,
right-to-explanation, bias/fairness metrics, Agent Shield.

**Build gaps (AI-specific):**
1. ~~Formal model-card metadata export (A.6.2.7 / A.8.2)~~ — **Closed.**
   Operator-declared metadata (intended use, out-of-scope use, limitations, risk
   classification, data provenance, human oversight, ethical considerations, and
   eval results) is merged into the usage cards and exported via
   `model_cards.py` (`ModelCardMetadata`, `export_model_cards`). → R-25 closed.
2. ~~AI-system retirement/decommissioning procedure (A.6.2)~~ — **Closed.**
   `maverick/retirement.py` provides a governed, fail-safe retirement flow with
   an explicit data disposition (retain/archive/erase) and a signed
   `AI_SYSTEM_RETIRED` audit record. → R-24 closed.
3. ~~Continuous fairness monitoring (A.6.2.6)~~ — **Closed.** `fairness_monitor.py`
   adds a rolling-window monitor over decision outcomes that recomputes the
   group-fairness metrics continuously and raises a signed `FAIRNESS_ALERT` on a
   four-fifths breach or a drift below baseline. → R-22 closed.

All three former AI build gaps are now implemented; the remaining ISO 42001 work
is the shared management-system documentation and process controls.

**Process gaps:** shared with ISO 27001 (AI roles/competence, supplier
management, AI-incident communication procedure).

## 5. Certification roadmap

Per `docs/research/commercialization/07-trust-certifications-roadmap.md`:
**4–6 months if ISO 27001 already exists** (6–12 months standalone).

1. **Stack on the ISMS:** reuse the certified management system, risk
   methodology, and shared policies.
2. **Close the AI build gaps** — model-card metadata export, the retirement
   procedure, and continuous fairness monitoring are all **done** (R-22, R-24,
   R-25 closed).
3. **Run AI system impact assessments** (A.5) for in-scope deployment contexts.
4. **Stage 1 + Stage 2 audit** with an accredited certification body.
5. **Surveillance + recertification** as with ISO 27001.

Positioning: ISO 42001 is becoming table-stakes for enterprise AI vendors but is
not yet a hard procurement gate like SOC 2 Type II — pursue it as the
"provably-governed AI" differentiator once the ISMS is certified.
