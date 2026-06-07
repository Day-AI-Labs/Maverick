# HR / People agent suite

**Status:** design / roadmap. Companion to
[`finance-agent-suite.md`](finance-agent-suite.md),
[`it-grc-agent-suite.md`](it-grc-agent-suite.md),
[`sales-gtm-agent-suite.md`](sales-gtm-agent-suite.md), and
[`../enterprise/architecture.md`](../enterprise/architecture.md). Indexed in
[`agent-suites-overview.md`](agent-suites-overview.md). ~41 agents across eight towers.

> **What makes HR the most sensitive domain of all.** These agents make decisions
> *about people*, using the company's **most protected data** (comp, health, performance,
> disciplinary, immigration, protected-class), under the **heaviest anti-discrimination
> regime** (Title VII, ADA, ADEA, EEOC, NYC LL144, EU AI Act). It is the convergence of
> three control stories Maverick has *already built*: **privacy** (employee PII is
> special-category — reuse the privacy suite), **AI governance** (employment is EU AI
> Act **Annex III high-risk** and NYC LL144 territory — reuse the AI-Gov tower), and
> **need-to-know access control** (comp/performance/medical segregation — the capability
> model). And uniquely: some HR AI uses are **outright prohibited, not merely gated** —
> `ai_act.py` already flags *"emotion inference in the workplace"* as an **Art 5
> prohibited practice**. The suite must **refuse** those, not wrap them in a gate.

The cardinal rule for every agent below (the HR analogue of finance's "never move
money"):

> *Agents source, screen, rank, draft, and recommend freely — but a **human makes every
> consequential employment decision** (hire, fire, promote, pay, discipline), with a
> documented, bias-audited rationale. No agent uses protected-class data or its proxies
> in a decision, and the suite **refuses** any use the EU AI Act prohibits.*

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How an HR agent maps onto Maverick](#2-how-an-hr-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — eight towers](#5-the-roster--eight-towers)
   - [Tower 1 — Talent Acquisition & Recruiting](#tower-1--talent-acquisition--recruiting)
   - [Tower 2 — Onboarding & Offboarding (lifecycle)](#tower-2--onboarding--offboarding-lifecycle)
   - [Tower 3 — HR Operations & Shared Services](#tower-3--hr-operations--shared-services)
   - [Tower 4 — Total Rewards (Compensation & Benefits)](#tower-4--total-rewards-compensation--benefits)
   - [Tower 5 — Performance & Talent Management](#tower-5--performance--talent-management)
   - [Tower 6 — Learning & Development](#tower-6--learning--development)
   - [Tower 7 — Employee Relations, Compliance & Investigations](#tower-7--employee-relations-compliance--investigations)
   - [Tower 8 — People Analytics, Workforce Planning & Engagement](#tower-8--people-analytics-workforce-planning--engagement)
6. [The People Supervisor (Layer A)](#6-the-people-supervisor-layer-a)
7. [Compliance-regime packs (Layer B)](#7-compliance-regime-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

Status vocabulary: **Shipped** / **Partial** / **Gap** / **Process-only**. Like GTM,
HR is greenfield *workflow* — but the *control* substrate is unusually strong because
privacy and AI-governance already exist.

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **EU AI Act risk classification** — flags employment as **Annex III high-risk** and workplace **emotion inference as Art 5 prohibited** | `ai_act.py` | **Shipped** | the refusal list (§3.6) + screening/perf gates |
| **Employee/candidate PII + special-category handling** | `safety/pii_detector.py`, `crypto_at_rest.py`, `enterprise.py` (egress) | **Shipped** | every tower (§3.3) |
| **Employee data-subject rights** (access, erasure, ROPA) | `dsar.py`, `audit/erase.py`, `ropa.py` | **Shipped** (reuse the privacy suite) | HRIS (3.2), §3.3 |
| **Consequential-decision human gate** | `governance.py` (`require_human`) + `safety/consent.py` | **Shipped** (primitive) | the consequential-decision gate (§3.1) |
| **Employment / consequential-decision pack** (decision records + mandatory human review + bias-audit export) | named in `architecture.md` (Colorado/NYC LL144/EEOC) | **Gap** (the keystone build) | Screening (1.2), Performance (5.2), Promotion (5.3) |
| **Bias / fairness evaluation** (LL144, Annex III) | AI-Gov bias-eval (it-grc 1.5) | **Gap** (shared build) | Screening (1.2), Pay equity (4.2), Recruiting analytics (1.7) |
| **AI / bot disclosure** (Art 50 / CA SB 1001) | `compliance.py` | **Shipped** | candidate & employee chat (1.3, 3.1) |
| **Need-to-know access control** (comp/perf/medical segregation) | `capability.py` (path scopes + RBAC) | **Shipped** | §3.4 |
| **Multi-channel + intake + scheduling** | `packages/maverick-channels/`, `intake.py`, `scheduler.py` | **Shipped** | Helpdesk (3.1), Candidate engagement (1.3) |
| **Assessment engine** | `assessment.py` (`TEMPLATES`) | **Shipped** | the HR templates (§8) |
| **Tamper-evident record** | the signed Merkle audit chain | **Shipped** | the LL144 / EEOC decision evidence |
| **Knowledge** (handbook, policy) | `knowledge_search` | **Shipped** | Helpdesk (3.1), Policy (3.4) |
| **Comp → gross-to-net → GL** | finance **Payroll** agent (designed) | cross-suite | Payroll liaison (4.5) |
| **Access provisioning (joiner-mover-leaver)** | IT-GRC **IAM** tower (designed) | cross-suite | Onboarding/Offboarding (T2) |

**The headline gaps:** the systems-of-record + workflow — HRIS/HCM, ATS, LMS, benefits,
background-check, comp, and engagement connectors; the recruiting / performance / comp /
ER workflows; people analytics; and the two keystone controls — the **employment-decision
pack** and the **bias-evaluation** engine (shared with AI-Gov).

---

## 2. How an HR agent maps onto Maverick

Each agent is one [`DomainProfile`](../../packages/maverick-core/maverick/domain.py)
pack, governed by Layer A + consent + the signed audit chain. Three HR specifics:

- **The employee/candidate is the data subject.** Reuse the privacy suite's PII,
  egress, encryption, and DSAR/erasure — but the data is *special-category* (health,
  protected class) and the subject is an *employee* (works-council and consent nuances
  differ from customers).
- **Employment decisions are EU AI Act Annex III high-risk** — `ai_act.py` already says
  so. Every screening/ranking/scoring agent inherits that classification and its
  obligations (human oversight, logging, bias evaluation).
- **Refusal, not just gating.** Where finance/GTM gate risky actions, HR must *refuse*
  prohibited ones (Art 5 workplace emotion inference). The refusal list is a hard
  property of the packs, not a tunable.

---

## 3. The control model (cross-cutting)

### 3.1 The consequential-decision gate (cardinal control)
Hiring, firing, promotion, compensation, and discipline are **decided by a human**.
Agents screen, rank, draft, and recommend; the decision is `require_human`, and a
**decision record** captures the human decider, the rationale, and the inputs — the
EEOC / NYC LL144 / Colorado evidence. This is the architecture's named
*employment/consequential-decision pack*; the human-review primitive ships, the pack is
the keystone build.

### 3.2 Bias & fairness (hard floor + audit)
Every consequential-decision tool is **bias-evaluated** before use and monitored for
**adverse impact** (the four-fifths rule) in production; **protected-class data and its
proxies are never inputs** to a decision. NYC LL144 requires an **annual independent
bias audit** of automated employment decision tools — the suite produces the evidence
(the `ll144_bias_audit` template, §8); the independent auditor is a human. Reuses the
AI-Gov bias-eval (a shared gap).

### 3.3 Employee-data privacy & special-category handling
Employee records are the company's most sensitive PII (comp, health/benefits — GDPR
Art 9 special-category — performance, disciplinary, immigration). Reuse the privacy
suite at its strictest: encryption at rest, egress/residency lock, PII redaction, and
the **employee DSAR/erasure** path. Works-council / co-determination constraints (EU)
and employee-monitoring limits apply.

### 3.4 Confidentiality, need-to-know & separation of duties
Comp, performance, medical, and investigation data are **compartmentalized** by
capability path scopes: a manager sees only their reports; the recruiter does not set
comp; the investigator is independent of the line manager; HR Ops does not see
investigation files. Enforced by `Capability.attenuate()` (narrow-only), not by policy
PDF.

### 3.5 Employment-law compliance
FLSA (wage/hour), FMLA (leave), ADA/PWFA (accommodation), Title VII/ADEA (discrimination),
NLRA (labor), WARN (layoffs), IRCA/I-9 (work authorization), FCRA (background checks) —
plus state law and, for EU staff, GDPR + works councils. Jurisdiction packs (§7).

### 3.6 Prohibited uses — refuse, don't gate
`ai_act.py` flags **emotion inference in the workplace** as an **Art 5 prohibited
practice**. The suite **refuses** it (and similar prohibited uses — manipulative
techniques, social scoring, intrusive biometric monitoring), rather than routing them
through a human gate. Engagement/sentiment work (8.3) is **consented and aggregated**,
never individual emotion inference.

### 3.7 Compensation integrity
Comp changes follow maker-checker with **amount-aware authority** (the shared finance
DoA build): a change beyond a band/threshold is `require_human` at the right level.
**Pay equity** is monitored (4.2). HR owns the *people* decision; **finance owns
gross-to-net/payroll** (4.5 is a liaison, never runs payroll); FP&A owns the cost.

### 3.8 Background checks & adverse action (FCRA)
Background screening follows the FCRA pre-adverse / adverse-action process; **ban-the-box
/ fair-chance** timing is honored; the decision is human, documented, and gated.

### 3.9 Dignity & the human-owned moments
Terminations, PIPs, investigations, and accommodation conversations are **human-owned**;
agents prepare materials and ensure consistency and legal compliance, but the human
delivers them. No agent communicates a consequential outcome to an employee on its own.

### 3.10 The record
Every consequential decision, access to a sensitive record, and recommendation is
written to the signed Merkle audit chain — the anti-discrimination and audit-defense
evidence trail.

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder (per action class)
The L0–L4 ladder, but HR **caps consequential actions hard**:

| Level | HR behaviour |
|---|---|
| **L0 Observe** | analyze, benchmark, recommend — no employee-facing action |
| **L1 Draft** *(default; the ceiling for anything consequential)* | draft the offer / review / PIP / job post; a human decides and delivers |
| **L2 Approve** | take a *non-consequential* action after sign-off (publish a job post, send an approved letter) |
| **L3 Auto-under-threshold** | only for **non-consequential, non-sensitive** ops — schedule interviews, deflect a policy FAQ, nudge training, dedup HRIS records |
| **L4 Straight-through** | reserved for purely administrative, no-PII automation (e.g. training-completion reminders) |

**No consequential employment decision is ever above L1** — that's a hard floor, not a
client choice.

### 4.2 Hard floors — never auto / never at all
The profile compiler refuses to lower these:
- **deciding** a hire / fire / promotion / pay / discipline action autonomously (always human);
- using **protected-class data or proxies** as a decision input;
- **prohibited monitoring** (workplace emotion inference) — *refused, not gated* (§3.6);
- disclosing **another employee's** confidential data (comp, medical, performance, investigation);
- **finalizing an investigation conclusion** or adverse action without human + FCRA process;
- **running payroll** (finance owns gross-to-net).

### 4.3 Jurisdictions & workforce type
Which employment-law packs apply (US federal + states with their pay-transparency and
LL144-style rules; EU + **works councils / co-determination**; UK; etc.), and the
workforce type (high-volume hourly vs. salaried knowledge worker) — which changes the
recruiting/perf motion and the automation appetite.

### 4.4 Compensation philosophy & DEI posture
Comp bands/benchmarks, merit-cycle rules, and the discount-equivalent **comp-authority
matrix** (§3.7); the DEI analytics posture — **legally constrained and jurisdiction-
specific** (e.g. US post-*SFFA* limits on race-conscious decisions): analytics stay
aggregate and no protected attribute is ever a decision input.

### 4.5 Enabled towers & maturity
The roster is a menu — a 50-person startup runs Helpdesk + Recruiting + Onboarding +
basic HRIS and skips Labor Relations / Succession; an enterprise runs all eight.

### 4.6 The People Operating Profile
One signed, versioned bundle (intake produces, wizard edits, rule 6) compiling to
capability + governance policy + consent config + jurisdiction packs + the refusal list
+ the comp-authority matrix — the HR analogue of the other suites' Operating Profiles.

---

## 5. The roster — eight towers

~41 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**,
**Status**. Connectors marked `‹build›` are §9. Representative packs are full TOML.

---

### Tower 1 — Talent Acquisition & Recruiting

The highest AI-governance exposure (Annex III + NYC LL144).

#### 1.1 Sourcing & Talent-Research Agent
- **Job:** Source candidates, build talent pipelines, market/competitor talent mapping.
- **Connects to:** ATS (Greenhouse/Lever) `‹build›`, LinkedIn/job boards `‹build›`, `web_search`.
- **Capability:** research + `build_pipeline`, `draft_sourcing_list`. No outreach send (gated; reuse GTM consent floor).
- **Controls:** candidate-data privacy + provenance; no protected-class targeting.
- **Status:** **Gap** (workflow) / **Partial** (research shipped).

#### 1.2 Resume Screening & Ranking Agent
- **Job:** Screen and rank applications against **job-related** criteria; produce a
  shortlist with rationale. *The canonical Annex-III / LL144 agent.*
- **Connects to:** ATS `‹build›`, the bias-eval engine, `knowledge_search` (job spec).
- **Capability:** read applications + `screen_application`, `draft_shortlist`. **Denies**
  any reject/advance *decision* (human-gated) and any protected-class feature.
- **Controls:** **bias-evaluated before use + adverse-impact monitored** (§3.2); decision
  record on every human disposition; **L1 ceiling** (drafts only).
- **Status:** **Gap**, behind the employment-decision pack + bias eval (the keystone builds).

```toml
# packages/maverick-core/maverick/domains/hr_screening.toml
name = "hr_screening"
compartment = "hr_recruiting"
description = "Job-related resume screening and ranking (EU AI Act Annex III high-risk)."

persona = """You are a Recruiting Screening specialist operating under a HIGH-RISK
employment classification. Evaluate candidates ONLY against documented, job-related
criteria from the role's requirements; cite the evidence in the resume for every
rating. You DRAFT a ranked shortlist with rationale for a human recruiter to decide --
you NEVER reject or advance a candidate yourself. You must NOT infer or use protected
characteristics (race, sex, age, disability, religion, national origin) or their
proxies (e.g. name, photo, address, graduation year, gaps in employment). If a
criterion looks like a proxy for a protected class, flag it and exclude it. State
'insufficient evidence' rather than guessing."""

allow_tools = [
    "read_file", "knowledge_search",
    "screen_application", "draft_shortlist", "run_assessment",
]
deny_tools = ["advance_candidate", "reject_candidate", "infer_demographics", "send_email"]
max_risk = "low"
knowledge_sources = ["hr_job_specs", "hr_recruiting_policy"]
authoring = "manual"
```

#### 1.3 Candidate Engagement & Scheduling Agent
- **Job:** Candidate communications, interview scheduling, status updates, candidate
  experience.
- **Connects to:** the **channels layer** + **Google Calendar** (live), ATS `‹build›`.
- **Capability:** `message_candidate` (gated/tiered), `schedule_interview`.
- **Controls:** **AI disclosure** (shipped); consent on outreach; no commitments.
- **Status:** **Partial** (channels + calendar + disclosure shipped).

#### 1.4 Interview & Assessment-Design Agent
- **Job:** Structured interview kits, scorecards, job-related skills assessments;
  interviewer prep.
- **Connects to:** ATS `‹build›`, `knowledge_search`.
- **Capability:** `build_interview_kit`, `draft_scorecard`. No scoring decisions.
- **Controls:** structured + job-related (validity); reduces bias by design.
- **Status:** **Gap**.

#### 1.5 Offer Management Agent
- **Job:** Draft offers within approved comp bands, route approvals, manage acceptance.
- **Connects to:** ATS + comp `‹build›`, Total Rewards (4.1).
- **Capability:** `draft_offer`. **Denies** committing comp (→ comp-authority gate §3.7).
- **Status:** **Gap**.

#### 1.6 Employer Brand & Recruitment-Marketing Agent
- **Job:** Careers content, **job postings**, candidate nurture (overlaps GTM marketing).
- **Connects to:** career site/CMS `‹build›`, channels.
- **Capability:** `draft_job_post`, `draft_nurture`. Publish gated.
- **Controls:** **no discriminatory language** in postings (EEO); inclusive-language check.
- **Status:** **Gap** (reuses GTM patterns).

#### 1.7 Recruiting Ops & Analytics Agent
- **Job:** Funnel metrics, time-to-fill, source quality, ATS hygiene, **adverse-impact
  monitoring** across the funnel.
- **Connects to:** ATS + BI `‹build›`.
- **Capability:** read + `analyze_funnel`, `monitor_adverse_impact`. No decisions.
- **Status:** **Gap**.

---

### Tower 2 — Onboarding & Offboarding (lifecycle)

#### 2.1 Onboarding Agent
- **Job:** Pre-boarding, day-1 plans, new-hire paperwork (tax, policy acknowledgments),
  **triggers IT provisioning** (→ IT-GRC IAM joiner-mover-leaver).
- **Connects to:** HRIS `‹build›`, the IT IAM agent, channels, `intake.py`.
- **Capability:** `build_onboarding_plan`, `request_provisioning` (gated to IAM).
- **Status:** **Partial** (intake/channels shipped; HRIS + IAM are cross-suite builds).

#### 2.2 Work-Authorization (I-9 / E-Verify) Agent
- **Job:** Work-authorization verification, I-9 completeness, immigration/visa tracking.
- **Connects to:** I-9/E-Verify + HRIS `‹build›`.
- **Capability:** read + `check_i9`, `flag_work_auth`. **Denies** the verification decision (human).
- **Controls:** highly sensitive; anti-discrimination (no document abuse); gated.
- **Status:** **Gap**.

#### 2.3 Offboarding & Exit Agent
- **Job:** Offboarding checklist, **access-revocation trigger** (→ IAM), exit interviews,
  final-pay handoff (→ payroll), COBRA/benefits.
- **Connects to:** HRIS `‹build›`, IT IAM, finance payroll, channels.
- **Capability:** `build_offboarding_plan`, `request_deprovisioning` (gated).
- **Controls:** timely access revocation (security); final-pay law compliance.
- **Status:** **Partial** (cross-suite triggers).

#### 2.4 Internal Mobility & Transfer Agent
- **Job:** Transfers, role changes, internal moves, redeployment.
- **Connects to:** HRIS `‹build›`.
- **Capability:** `draft_transfer`. Role/comp change gated (consequential).
- **Status:** **Gap**.

---

### Tower 3 — HR Operations & Shared Services

#### 3.1 HR Helpdesk / Employee-Service Agent
- **Job:** Tier-1 HR Q&A (policy, PTO, benefits, payroll questions), case triage,
  escalation — the highest-volume employee-facing agent.
- **Connects to:** HR case mgmt (ServiceNow HRSD) `‹build›`, the **channels layer**,
  `knowledge_search`, `intake.py`.
- **Capability:** `answer_from_policy`, `triage_case`, `escalate`. Tiered (L3 for FAQs).
- **Controls:** **AI disclosure**; escalate anything sensitive (ER, comp dispute,
  medical) to a human; never expose another employee's data.
- **Status:** **Partial** (channels + intake + disclosure shipped).

```toml
# packages/maverick-core/maverick/domains/hr_helpdesk.toml
name = "hr_helpdesk"
compartment = "hr_operations"
description = "Tier-1 HR helpdesk: policy Q&A, case triage, escalation."

persona = """You are an HR Helpdesk specialist. Answer ONLY from the employee handbook
and the asking employee's own records; cite the policy. Disclose you are an AI assistant
at the start. ESCALATE to a human -- never advise or act -- on anything involving
discipline, complaints/harassment, medical or disability, accommodations, comp disputes,
terminations, or another employee's data. Be warm, concise, and confidential; never
reveal one employee's information to another."""

allow_tools = [
    "read_file", "knowledge_search",
    "answer_from_policy", "triage_case", "escalate", "reply_in_channel",
]
deny_tools = ["change_record", "approve_leave", "disclose_other_employee", "issue_letter"]
max_risk = "medium"
mcp_servers = ["HRIS_Workday", "HRCase_ServiceNow"]   # ‹build›
knowledge_sources = ["hr_handbook", "hr_benefits"]
authoring = "manual"
```

#### 3.2 HRIS & Employee-Records Agent
- **Job:** Employee master data, records management, data quality/governance.
- **Connects to:** HRIS `‹build›`, `pii_detector`.
- **Capability:** read + `validate_record`, `flag_data_quality`. Record changes gated.
- **Controls:** special-category privacy (§3.3); change audit; need-to-know.
- **Status:** **Partial** (privacy primitives shipped).

#### 3.3 Employment-Verification & Letters Agent
- **Job:** Verification of employment, letters (visa/mortgage/immigration), references.
- **Connects to:** HRIS `‹build›`.
- **Capability:** `draft_verification`. **Denies** release without authorization (gated).
- **Controls:** only authorized info; consent for references; no comp disclosure w/o consent.
- **Status:** **Gap**.

#### 3.4 HR Policy & Document Agent
- **Job:** Policy/handbook lifecycle, acknowledgments, e-signatures (overlaps GRC policy).
- **Connects to:** policy repo (`Google_Drive`), e-sign `‹build›`.
- **Capability:** `draft_policy`, `track_acknowledgment`. Publish gated.
- **Status:** **Partial** (reuses GRC policy patterns).

#### 3.5 HR Compliance & Reporting Agent
- **Job:** Mandatory reporting (**EEO-1, OSHA 300, ACA, BLS, VETS-4212**), retention,
  audit support.
- **Connects to:** HRIS + reporting portals `‹build›`.
- **Capability:** read + `draft_compliance_report`. Filing gated (human).
- **Status:** **Gap**.

---

### Tower 4 — Total Rewards (Compensation & Benefits)

#### 4.1 Compensation Analysis & Bands Agent
- **Job:** Comp benchmarking, band design, range placement, merit-cycle modeling.
- **Connects to:** comp tools (Pave/Radford) `‹build›`, HRIS.
- **Capability:** read + `benchmark_comp`, `model_merit_cycle`. **Denies** committing comp.
- **Controls:** comp data strictly need-to-know (§3.4); changes gated (§3.7).
- **Status:** **Gap**.

#### 4.2 Pay-Equity Agent
- **Job:** Pay-equity analysis, disparate-pay detection, remediation modeling, pay-
  transparency compliance.
- **Connects to:** HRIS + comp `‹build›`, the bias-eval engine.
- **Capability:** read + `analyze_pay_equity`, `model_remediation`. No commits.
- **Controls:** often **attorney-client privileged** — restricted compartment; aggregate.
- **Status:** **Gap** (also a `pay_equity` template, §8).

#### 4.3 Benefits Administration Agent
- **Job:** Benefits enrollment, open enrollment, vendor liaison, employee questions.
- **Connects to:** benefits platforms/carriers `‹build›`, HRIS.
- **Capability:** `guide_enrollment`, `answer_benefits`. Elections gated.
- **Controls:** **health data = GDPR Art 9 / HIPAA**; strict privacy; ERISA/ACA.
- **Status:** **Gap**.

#### 4.4 Leave & Absence Agent
- **Job:** FMLA/ADA leave administration, **accommodation intake** (→ ER 7.4), absence
  tracking.
- **Connects to:** HRIS + leave platform `‹build›`.
- **Capability:** `intake_leave`, `track_absence`. Eligibility/accommodation decisions gated.
- **Controls:** medical data privacy; FMLA/ADA compliance; interactive process is human-led.
- **Status:** **Gap**.

#### 4.5 Payroll Liaison Agent
- **Job:** Feed comp/status changes to **finance Payroll**, reconcile, resolve queries.
- **Connects to:** HRIS `‹build›` ↔ the finance **Payroll** agent.
- **Capability:** `sync_payroll_inputs`, `reconcile`. **Denies running payroll** (finance owns).
- **Controls:** **SoD** across HR↔finance; change audit.
- **Status:** **Partial** (ties to the designed finance Payroll agent).

---

### Tower 5 — Performance & Talent Management

Consequential decisions — **L1 ceiling**, bias-aware throughout.

#### 5.1 Goals & OKR Agent
- **Job:** Goal/OKR setting, alignment, progress tracking.
- **Connects to:** perf platform (Lattice/15Five) `‹build›`.
- **Capability:** `draft_goals`, `track_okr`. No ratings.
- **Status:** **Gap**.

#### 5.2 Performance-Review Agent
- **Job:** Orchestrate the review cycle; **draft** review summaries from documented
  inputs (goals, peer feedback); support calibration.
- **Connects to:** perf platform `‹build›`, the bias-eval engine.
- **Capability:** `draft_review_summary`, `support_calibration`. **Denies** assigning a
  rating or a decision (human-gated).
- **Controls:** **bias-aware language** (no protected-class or biased phrasing); L1
  ceiling; decision record on the human rating.
- **Status:** **Gap** (behind the employment-decision pack).

```toml
# packages/maverick-core/maverick/domains/hr_performance.toml
name = "hr_performance"
compartment = "hr_talent"
description = "Performance-review support (consequential — drafts only, human decides)."

persona = """You are a Performance Management specialist. Synthesize ONLY documented,
job-related inputs (goals, results, peer/manager feedback) into a balanced draft review;
cite the input behind every statement. You DRAFT summaries and surface calibration data
for a human manager to decide -- you NEVER assign a rating, a promotion, or a
compensation outcome. Use neutral, behavior-based language; flag and remove any phrasing
that references protected characteristics or relies on biased proxies. Note recency or
favoritism bias in the inputs when you see it."""

allow_tools = [
    "read_file", "knowledge_search",
    "draft_review_summary", "support_calibration", "run_assessment",
]
deny_tools = ["assign_rating", "decide_promotion", "set_compensation"]
max_risk = "low"
knowledge_sources = ["hr_perf_policy", "hr_competencies"]
authoring = "manual"
```

#### 5.3 Calibration & Promotion Agent
- **Job:** Calibration support, promotion-packet assembly, pay-for-performance modeling.
- **Connects to:** perf + comp `‹build›`.
- **Capability:** `assemble_promo_packet`, `support_calibration`. **Denies** the decision.
- **Controls:** consequential gate; adverse-impact check on promotion rates.
- **Status:** **Gap**.

#### 5.4 Succession & Talent-Review Agent
- **Job:** Succession plans, 9-box, high-potential identification, talent reviews.
- **Connects to:** HRIS + perf `‹build›`.
- **Capability:** read + `draft_succession_plan`. No decisions.
- **Controls:** sensitive; bias-aware (no proxy-based potential ratings); confidential.
- **Status:** **Gap**.

#### 5.5 Performance-Improvement & Coaching Agent
- **Job:** Draft PIPs and coaching plans; manager guidance.
- **Connects to:** perf platform `‹build›`, ER (7.1).
- **Capability:** `draft_pip`, `draft_coaching`. **Denies** delivering it (human-owned §3.9).
- **Controls:** dignity; legal review of PIP/termination paths; documentation.
- **Status:** **Gap**.

---

### Tower 6 — Learning & Development

#### 6.1 Learning Content & Curriculum Agent
- **Job:** Course/curriculum design, microlearning, content from SMEs.
- **Connects to:** LMS `‹build›`, `knowledge_search`.
- **Capability:** `design_course`, `draft_content`. Publish gated.
- **Status:** **Gap**.

#### 6.2 Skills & Career-Pathing Agent
- **Job:** Skills taxonomy, gap analysis, career paths, individual development plans.
- **Connects to:** HRIS + skills platform `‹build›`.
- **Capability:** `map_skills`, `draft_idp`. No decisions.
- **Status:** **Gap**.

#### 6.3 Training Delivery & LMS Agent
- **Job:** Assign/track training, LMS admin, completion nudges.
- **Connects to:** LMS `‹build›`, channels.
- **Capability:** `assign_training`, `nudge_completion`. (Low-risk → L3/L4 eligible.)
- **Status:** **Gap**.

#### 6.4 Compliance-Training Agent
- **Job:** Mandatory training (harassment, security, ethics, safety), completion + **attestation** (overlaps GRC).
- **Connects to:** LMS `‹build›`, the GRC compliance agent.
- **Capability:** `track_compliance_training`, `report_completion`.
- **Status:** **Partial** (reuses GRC training/attestation).

---

### Tower 7 — Employee Relations, Compliance & Investigations

The independent, confidential tower — **strictest access segregation**.

#### 7.1 Employee-Relations Agent
- **Job:** ER case intake, manager guidance, documentation, trend spotting.
- **Connects to:** ER case mgmt `‹build›`, `knowledge_search` (policy/law).
- **Capability:** `intake_er_case`, `guide_manager`. **Denies** deciding outcomes.
- **Controls:** confidentiality; consistency; legal escalation.
- **Status:** **Gap**.

#### 7.2 Investigations Agent
- **Job:** Workplace-investigation **support** — interview plans, evidence organization,
  timeline, neutral report drafting.
- **Connects to:** case mgmt `‹build›` (restricted), the legal domain.
- **Capability:** `plan_investigation`, `organize_evidence`, `draft_findings`. **Denies**
  concluding/deciding (human-led, often counsel-led).
- **Controls:** **independence + strict confidentiality + legal privilege**; isolated
  compartment; no cross-access to the subject's manager.
- **Status:** **Gap**.

```toml
# packages/maverick-core/maverick/domains/hr_investigations.toml
name = "hr_investigations"
compartment = "hr_investigations"      # isolated seal — no cross-access
description = "Workplace-investigation support (independent, confidential, human-led)."

persona = """You are a Workplace Investigations specialist supporting a human (often
legal-led) investigation. You PLAN interviews, ORGANIZE evidence, build a neutral
timeline, and DRAFT findings strictly from the evidence on the record -- you NEVER reach
a conclusion, assign culpability, or recommend discipline; the human investigator
decides. Maintain strict confidentiality and chain-of-custody (the signed audit chain);
treat the file as privileged. Remain neutral, separate fact from allegation, and never
disclose the matter outside the authorized investigation team."""

allow_tools = [
    "read_file", "knowledge_search",
    "plan_investigation", "organize_evidence", "draft_findings",
]
deny_tools = ["conclude_investigation", "recommend_discipline", "disclose_externally", "change_record"]
max_risk = "low"
knowledge_sources = ["hr_investigation_protocol", "employment_law"]
authoring = "manual"
```

#### 7.3 Employment-Law Compliance Agent
- **Job:** FLSA/FMLA/ADA/Title VII/WARN/state-law compliance; policy + practice review.
- **Connects to:** the legal domain, the GRC compliance agent, `knowledge_search`.
- **Capability:** read + `check_employment_law`, `flag_risk`. No legal advice (drafts for counsel).
- **Status:** **Partial** (reuses legal + GRC).

#### 7.4 EEO / AAP & Accommodations Agent
- **Job:** EEO compliance, **affirmative-action plans**, ADA/PWFA **accommodation
  interactive process** support.
- **Connects to:** HRIS `‹build›`, the bias-eval engine, legal.
- **Capability:** read + `draft_aap`, `support_accommodation`. Decisions human-led.
- **Controls:** protected-class data is aggregate/compliance-only; medical privacy; the
  interactive process is human-led.
- **Status:** **Gap**.

#### 7.5 Labor-Relations Agent
- **Job:** Union/CBA support, grievances, **works councils / co-determination** (EU), NLRA.
- **Connects to:** `knowledge_search` (CBA), case mgmt `‹build›`.
- **Capability:** `track_grievance`, `summarize_cba`. No bargaining commitments.
- **Controls:** jurisdiction (NLRA / EU co-determination); sensitive; human-led.
- **Status:** **Gap**.

#### 7.6 Ethics & Whistleblower-Triage Agent
- **Job:** Hotline intake, triage, routing (overlaps GRC; SOX §301 for finance matters).
- **Connects to:** the GRC ethics/whistleblower agent, case mgmt `‹build›`.
- **Capability:** `intake_report`, `route_report`. Confidential/anonymous-preserving.
- **Status:** **Partial** (shared with GRC).

---

### Tower 8 — People Analytics, Workforce Planning & Engagement

#### 8.1 People-Analytics Agent
- **Job:** HR metrics, **attrition/retention** analytics, dashboards, predictive flight-risk.
- **Connects to:** HRIS + BI `‹build›`.
- **Capability:** read + `build_people_report`, `model_attrition`. No individual decisions.
- **Controls:** **aggregate + re-identification protection**; flight-risk informs
  retention, never adverse action; privacy.
- **Status:** **Gap**.

#### 8.2 Workforce-Planning Agent
- **Job:** Headcount/workforce plans, org design, scenario modeling.
- **Connects to:** HRIS `‹build›`; ties to the **finance FP&A Workforce-cost** agent.
- **Capability:** read + `build_workforce_plan`, `model_org`. No commits.
- **Controls:** HR owns the people plan, **finance owns the cost** (SoD); WARN if layoffs.
- **Status:** **Partial** (cross-suite with finance FP&A).

#### 8.3 Engagement & Survey Agent
- **Job:** Engagement/pulse surveys, **consented & aggregated** sentiment synthesis,
  action planning.
- **Connects to:** engagement platform (Culture Amp/Glint) `‹build›`.
- **Capability:** `run_survey`, `synthesize_aggregate`. Surveys consented.
- **Controls:** **REFUSES individual emotion inference / monitoring (EU AI Act Art 5)** —
  aggregate-only, with a minimum response threshold to prevent re-identification (§3.6).
- **Status:** **Gap** (with the Art 5 guardrail as a hard property).

#### 8.4 DEI Analytics & Programs Agent
- **Job:** Diversity representation analytics, DEI program support, inclusion metrics.
- **Connects to:** HRIS `‹build›`, BI.
- **Capability:** read + `analyze_representation`, `draft_dei_program`. No decisions.
- **Controls:** protected-class data **aggregate-only**; **no protected attribute is ever
  a decision/selection input** (post-*SFFA* and jurisdiction limits, §4.4); legal review.
- **Status:** **Gap**.

#### 8.5 Internal-Communications Agent
- **Job:** Employee communications, announcements, change comms.
- **Connects to:** the **channels layer**, intranet `‹build›`.
- **Capability:** `draft_comms`. Sensitive comms (layoffs, policy) human-approved.
- **Status:** **Partial** (channels shipped).

---

## 6. The People Supervisor (Layer A)

Above the towers sits the **People Supervisor** — the HR instance of the oversight
control plane. It:

- **routes** people work to the right tower while honoring the strict confidentiality
  compartments (ER/investigations/comp/medical are sealed from HR Ops and from each other);
- **owns the consequential-decision queue** — every hire/fire/promote/pay/discipline
  recommendation lands here for a **human decision + recorded rationale** (the LL144/EEOC
  evidence);
- **enforces need-to-know** — holds the parent capability; each agent is spawned with a
  narrowed path scope so no agent sees data outside its remit;
- **holds the refusal list** (§3.6) and the bias-audit obligations.

Built on the shipped `governance.py` + `safety/consent.py` + `capability.py` (path
scopes) + the audit chain; the **employment-decision pack** and the operator console are
the keystone builds.

---

## 7. Compliance-regime packs (Layer B)

Strictest-wins union. Employment law is dense and jurisdictional, so these packs matter
more here than anywhere.

| Regime pack | Covers | Status |
|---|---|---|
| **EU AI Act — Annex III (employment) + Art 5 (prohibited monitoring)** | high-risk obligations + the refusal list | **Partial** (`ai_act.py` classifies; the obligations/refusal enforcement is the build) |
| **NYC LL144** | annual bias audit of automated employment tools | **Gap** (the `ll144_bias_audit` template + bias eval) |
| **Colorado ADMT / EEOC AI guidance / IL AIVIA** | consequential-decision human review + notice | **Gap** (the employment-decision pack) |
| **Title VII / ADA / ADEA / PWFA (EEO)** | anti-discrimination + accommodation | **Gap** (policy packs + bias controls) |
| **FLSA / FMLA / WARN / NLRA** | wage-hour, leave, layoffs, labor | **Gap** |
| **FCRA** | background checks, adverse action | **Gap** |
| **IRCA / I-9 / E-Verify** | work authorization | **Gap** |
| **GDPR (employee data) + works councils** | special-category employee data, co-determination | **Partial** (privacy suite shipped; works-council nuance to build) |
| **Pay transparency** (CA/CO/NY/WA, **EU Pay Transparency Directive**) | ranges, reporting, equity | **Gap** |
| **ERISA / ACA / COBRA / HIPAA** | benefits + health data | **Partial** (health-data privacy substrate shipped) |
| **OSHA** | workplace safety reporting | **Gap** |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code):

| New `type` | Owner | Framework |
|---|---|---|
| `adverse_impact` | Recruiting analytics (1.7) | four-fifths rule / disparate impact |
| `ll144_bias_audit` | Screening (1.2) | NYC LL144 automated-employment-tool audit |
| `pay_equity` | Pay equity (4.2) | disparate-pay / pay-transparency |
| `ada_accommodation` | EEO/Accommodations (7.4) | ADA/PWFA interactive-process completeness |
| `i9_work_auth` | Work-auth (2.2) | I-9 / IRCA completeness |
| `er_intake` | Employee Relations (7.1) | ER/investigation complaint triage & severity |

Each becomes a `run_assessment` capability + a conversational assessor via the existing
`build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Engagement channels / comms** | the 13-adapter channels layer | **✅ shipped** | Helpdesk (3.1), Candidate (1.3), Comms (8.5) |
| **Email / scheduling / docs** | Gmail, Google Calendar, Google Drive | **✅ exists** | Candidate scheduling (1.3), Policy (3.4) |
| **HRIS / HCM (system of record)** | Workday, SuccessFactors, BambooHR, Rippling, ADP, Gusto | ◻ build (P1) | most towers |
| **ATS (recruiting)** | Greenhouse, Lever, Ashby | ◻ build (P1) | Tower 1 |
| **HR case management** | ServiceNow HRSD, Zendesk | ◻ build (P2) | Helpdesk (3.1), ER (7.1) |
| **Payroll** | ADP, Gusto, Workday Payroll | ◻ build (P2, via finance) | Payroll liaison (4.5) |
| **Comp** | Pave, Radford, Mercer | ◻ build (P2) | Total Rewards (4.1, 4.2) |
| **Benefits** | carriers, Sequoia, bSwift | ◻ build (P3) | Benefits (4.3) |
| **Background check** | Checkr, HireRight | ◻ build (P2) | Onboarding (2.x) |
| **I-9 / E-Verify** | E-Verify, Tracker | ◻ build (P2) | Work-auth (2.2) |
| **Performance / engagement** | Lattice, 15Five, Culture Amp, Glint | ◻ build (P2) | Tower 5, 8.3 |
| **LMS** | Cornerstone, Docebo, Workday Learning | ◻ build (P3) | Tower 6 |
| **People analytics / BI** | Visier, Looker | ◻ build (P3) | Tower 8 |
| **Provisioning (IdP)** | Okta, Entra (via IT-GRC IAM) | ◻ build (P1, cross-suite) | Onboarding/Offboarding (T2) |

**Knowledge sources:** the employee handbook, job specs & competencies, comp bands,
benefits plans, the investigation protocol, CBAs, and the jurisdiction-specific
employment-law library.

---

## 10. Build sequence

The keystone control gates everything consequential — build it first.

1. **The employment-decision pack + bias eval + the refusal list (do this first).** The
   architecture's named pack: consequential-decision records + mandatory human-review
   gate + bias-audit export; the bias-evaluation engine (shared with AI-Gov); and the
   Art-5 refusal list. Plus the HR assessment templates (§8). *Nothing consequential
   ships before this.*
2. **HRIS connector (system of record) + HR Helpdesk (3.1) + Candidate Engagement (1.3)
   + Onboarding (2.1)** — substrate-ready on channels/intake/calendar/disclosure.
3. **Recruiting behind the pack:** Resume Screening (1.2) + Recruiting analytics /
   adverse-impact (1.7) + Offer (1.5), once bias eval + decision records exist.
4. **Total Rewards:** comp bands (4.1), **pay equity** (4.2), benefits/leave (4.3/4.4),
   payroll liaison (4.5, to finance).
5. **Performance & Talent** (behind the consequential gate) + **L&D**.
6. **Employee Relations & Investigations** (Tower 7 — isolated compartments, case mgmt)
   + **People Analytics / Workforce Planning / Engagement** (Tower 8, with the Art-5
   guardrail) + the jurisdiction regime packs.
7. **Wizard + dashboard** (rule 6): jurisdiction toggles, the People Operating Profile /
   refusal-list / comp-authority editor, and the consequential-decision review console.

---

## 11. Honest caveats

- **Most sensitive data, heaviest regime — the controls are not optional.** Employee
  special-category PII and anti-discrimination law mean the privacy and bias controls are
  load-bearing, not nice-to-have.
- **Agents recommend; humans decide every consequential action** — with a documented,
  bias-audited rationale. No agent hires, fires, promotes, pays, or disciplines.
- **Some uses are prohibited, not gated.** Workplace emotion inference (and similar Art 5
  practices) are **refused**, not wrapped in a human gate. That refusal is a hard property
  of the packs.
- **Bias audits are a real, independent obligation.** NYC LL144 requires an annual
  *independent* bias audit; the suite produces the evidence and monitors adverse impact,
  but it does not replace the independent auditor — same liability line as everywhere.
- **Confidentiality is structural.** ER, investigations, comp, and medical data live in
  isolated compartments by capability path scope; an agent that gains cross-access breaks
  the model — the People Supervisor enforces need-to-know.
- **Cross-suite separation of duties.** HR owns the people decision; **finance** owns
  payroll/cost; **IT** owns provisioning. The liaison agents (4.5, 2.1/2.3) hand off; they
  do not perform the other domain's gated action.
- **DEI is legally constrained and jurisdictional.** Post-*SFFA* (US) and varying global
  law mean analytics stay aggregate and no protected attribute is ever a selection input;
  this is counsel territory, and the suite stays on the evidence/monitoring side.
