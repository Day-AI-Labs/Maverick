# IT / GRC / Privacy / Security / AI-Governance agent suite

**Status:** design / roadmap. Companion to
[`finance-agent-suite.md`](finance-agent-suite.md) (same shape: agents, what they
connect to, controls, customization), [`../enterprise/architecture.md`](../enterprise/architecture.md)
(the three-layer control plane), and [`agent-factory.md`](agent-factory.md).

> **Read this first — most of this domain is already shipped.** Unlike finance,
> the privacy/compliance/security/AI-governance core is *built*: the EU AI Act
> helpers, GDPR DPIA/ROPA/DSAR/erasure, the SOC 2 evidence collector, the
> compliance control-coverage report, the assessment engine (PIA/AIRA/vendor),
> the governance policy engine, the Agent Shield, signed audit, capabilities,
> egress lock, quarantine seals, and the fleet model all exist today. So this doc
> is **not a wish-list** — it is a map of what to *wrap as agents* (thin personas
> over existing engines), what is *partial*, and the genuine *gaps* (IT ops, IAM
> workflow, incident response, vuln management, CMDB, backup/DR). Every roster
> entry carries an explicit **Status**.

The meta-point that makes this suite different from finance: **Maverick's own
primitives *are* the GRC controls.** The capability model is access control; the
signed audit chain is the record; the Shield is runtime threat detection;
governance is the policy engine; quarantine is incident containment. So these
agents both **operate** those controls and **emit their evidence** — and Tower 1
(AI Governance) literally governs the fleet it is part of.

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How an IT/GRC agent maps onto Maverick](#2-how-an-itgrc-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — ten towers](#5-the-roster--ten-towers)
   - [Tower 1 — AI Governance & Agent Oversight](#tower-1--ai-governance--agent-oversight)
   - [Tower 2 — Privacy / Data Protection](#tower-2--privacy--data-protection)
   - [Tower 3 — GRC core: Risk, Policy & Compliance](#tower-3--grc-core-risk-policy--compliance)
   - [Tower 4 — Internal Audit & Assurance](#tower-4--internal-audit--assurance)
   - [Tower 5 — Third-Party / Vendor Risk](#tower-5--third-party--vendor-risk)
   - [Tower 6 — Security Operations](#tower-6--security-operations)
   - [Tower 7 — AppSec & Supply Chain](#tower-7--appsec--supply-chain)
   - [Tower 8 — Vulnerability & Threat Management](#tower-8--vulnerability--threat-management)
   - [Tower 9 — Identity & Access Management](#tower-9--identity--access-management)
   - [Tower 10 — IT Operations & Resilience](#tower-10--it-operations--resilience)
6. [The GRC Supervisor — oversight control plane (Layer A)](#6-the-grc-supervisor--oversight-control-plane-layer-a)
7. [Compliance-regime packs (Layer B)](#7-compliance-regime-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

The status vocabulary, borrowed from [`soc2-controls.md`](../compliance/soc2-controls.md):
**Shipped** (enforced code exists) · **Partial** (exists but opt-in/scoped/incomplete)
· **Gap** (no code) · **Process-only** (an org/human process the agent *orchestrates
and evidences*, but cannot perform).

| Existing capability | Module / surface | Status | The agent(s) that reuse it |
|---|---|---|---|
| EU AI Act risk classification + Art 5/Annex III checklist | `ai_act.py` · `maverick ai-act` | **Shipped** | AI Act Conformity (1.3) |
| Art 50 AI transparency disclosure | `compliance.py` (`first_turn_disclosure`) | **Shipped** | AI Act Conformity (1.3), Oversight (1.6) |
| AI Risk Assessment (NIST RMF / EU AI Act) | `assessment.py` `_AIRA` + assessor agent | **Shipped** | AIRA (1.2) |
| GDPR Art 35 DPIA scaffold | `dpia.py` · `maverick dpia` | **Shipped** | DPIA/PIA (2.1) |
| Privacy Impact Assessment | `assessment.py` `_PIA` | **Shipped** | DPIA/PIA (2.1) |
| GDPR Art 30 ROPA | `ropa.py` · `maverick ropa` | **Shipped** | ROPA (2.2) |
| DSAR access/portability + erasure | `dsar.py`, `audit/erase.py` · `maverick dsar`/`erase`/`export-user` | **Shipped** | Data-subject rights (2.3) |
| Retention / minimization | `audit/retention.py`, `privacy.py` · `maverick retention` | **Shipped** | Retention (2.8) |
| SOC 2 evidence collector + TSC mapping | `soc2.py` · `maverick soc2` · `soc2-controls.md` | **Shipped** | Compliance (3.1), Evidence (3.2) |
| Control-coverage report (GDPR/EU AI Act/US) | `compliance.py` · `maverick compliance` | **Shipped** | Compliance (3.1) |
| Vendor risk assessment | `assessment.py` `_VENDOR_RISK` | **Shipped** | Vendor risk (5.1) |
| Governance policy engine (allow/deny/require_human) | `governance.py` | **Shipped** | Supervisor (§6), Control testing (3.5) |
| Agent Shield (injection/jailbreak/exfil/canary/unicode) | `safety/{jailbreak_heuristics,remote_scan,canaries,unicode_filter}.py` | **Shipped** | Threat detection (6.1) |
| Secret + PII detection/redaction | `safety/{secret_detector,pii_detector}.py` | **Shipped** | Secret scanning (7.1), Data classification (2.4) |
| Signed Merkle audit chain + verify | `audit/signing.py` · `maverick audit verify` | **Shipped** | every agent (the record) |
| SIEM export (CEF) | `audit/export.py` · `maverick audit export` | **Partial** (export format; no live forwarder) | SIEM triage (6.2) |
| Attenuating, signed capabilities + RBAC | `capability.py` | **Shipped** (opt-in) | Access review (9.2), PAM (9.3) |
| OIDC / SSO verifier | `oidc.py`, `proxy_auth.py`, `mcp_oauth.py` | **Shipped** (opt-in) | Authentication (9.4) |
| Enterprise egress lock (data residency) | `enterprise.py` | **Shipped** (opt-in) | Transfers (2.7), Compliance (3.1) |
| Encryption at rest (AES-256-GCM) | `crypto_at_rest.py` | **Shipped** (opt-in) | Privacy (T2), Security (T6) |
| Compartment quarantine (Rung-2 seals) | `quarantine.py` | **Shipped** | Incident response (6.3) |
| Kill switch | `killswitch.py` · `~/.maverick/HALT` | **Shipped** | Oversight (1.6), IR (6.3) |
| Circuit breakers / health / observability | `circuit_breaker.py`, `health.py`, `observability.py`, `monitor.py` | **Shipped** | SRE (10.3) |
| Durable checkpoint / job queue | `checkpoint.py`, `job_queue.py` | **Shipped** | Change rollback (10.2), DR (10.4 partial) |
| License compliance scan | `license_scan.py` | **Shipped** | SCA/license (7.2) |
| Dependency/plugin/MCP supply-chain pinning | `mcp_registry.py` (`pin_sha256`), `plugin_manifest.py` | **Partial** | Supply-chain trust (7.4) |
| Code review | `reviewer.py` + `/code-review` skill + GitHub Copilot review | **Partial** | Secure code review (7.3) |
| Per-employee fleet model (Layer C) | `fleet.py` | **Shipped** | Oversight (1.6), IAM (T9) |
| Budget / quotas / rate limit | `budget.py`, `quotas.py`, `net_concurrency.py`, `safety/rate_limiter.py` | **Shipped** | Supervisor (§6), SRE (10.3) |

**The headline gaps** (no code today): AI inventory/registry, model cards, bias
eval, AI-incident workflow, breach-notification workflow, risk register/ERM, policy
lifecycle, regulatory-change tracking, internal-audit workflow, subprocessor
registry, SIEM correlation, security-IR workflow, threat intel, CVE/SBOM vuln
scanning, patch management, IAM joiner-mover-leaver, CMDB, change-management
workflow, backup/DR, ITSM. Many are **Process-only** — the agent orchestrates and
evidences a human/org process rather than performing it (flagged per entry).

---

## 2. How an IT/GRC agent maps onto Maverick

Identical to the finance suite: each agent is one
[`DomainProfile`](../../packages/maverick-core/maverick/domain.py) pack
(`compartment` seal + `persona` + attenuating `allow_tools`/`deny_tools` +
`max_risk` + `allow_hosts` + `mcp_servers` + `knowledge_sources`), governed at
runtime by Layer A (`governance.py` → allow/deny/require_human), consent/HITL, and
the signed audit chain.

Two domain-specific notes:

- **Many of these agents are thin personas over an existing engine** — the AIRA
  agent is `build_assessment_agent` with the `_AIRA` template; the DPIA agent wraps
  `dpia.py`. The pattern is already proven by the conversational compliance
  assessor. *New code is the exception, not the rule, in Towers 1–3 and 5.*
- **Independence is structural.** Assurance agents (Tower 4) and the assessors get
  **read-only** capability over the domains they assess and **cannot remediate what
  they find** — the same SoD invariant the finance suite uses, enforced by
  `Capability.attenuate()` (narrow-only).

---

## 3. The control model (cross-cutting)

Each wraps *every* agent below; all map to a shipped primitive.

| Control | Primitive (shipped unless noted) |
|---|---|
| **Least privilege / access control** | attenuating `Capability` — tool/path/host scopes, `max_risk`, signed, child-narrows-only. |
| **Policy decision point** | `governance.evaluate()` → ALLOW / DENY / REQUIRE_HUMAN, recorded to audit. |
| **Human oversight (Art 14)** | `safety/consent.py` modes (`ask`/`dashboard`) + the approvals queue. |
| **Tamper-evident record** | Ed25519 Merkle audit chain, offline-verifiable — the evidence backbone for *every* framework. |
| **Runtime threat detection** | the Agent Shield (injection/jailbreak/exfil/canary/unicode). |
| **Blast-radius containment** | `quarantine.py` Rung-2 seals + `killswitch.py` — incident response primitives. |
| **Data residency / DLP** | `enterprise.py` egress lock + `egress_accounting.py` + secret/PII redaction. |
| **Confidentiality at rest** | `crypto_at_rest.py` (AES-256-GCM) + tenancy (`workspace.py`/`paths.py`). |
| **Evidence by construction** | capability grants, governance verdicts, and the signed chain *are* the audit evidence (`soc2.py` collects it). |
| **Independence of assurance** | read-only capabilities for audit/assessor agents (cannot fix what they test). |
| **Identity** | `oidc.py` verified subject → `user:{sub}` principal → capability/tenant. |
| **Separation gap to build** | a **mid-session capability-revocation sweep + revocation list** (expiry itself *is* enforced at `permits()` — an expired grant is denied at use-time) and an **access-conflict (SoD) linter** — see 9.2/9.3. |

---

## 4. Per-client customization — the dials

Same model as the finance suite (one set of agents tuned by config, not forks),
specialized for GRC. Six axes:

### 4.1 The automation ladder (per action class)

The L0–L4 ladder from the finance suite applies, but GRC skews **low** — most of
these agents *assess and report*, they don't act on production:

| Level | GRC behaviour | Maps to |
|---|---|---|
| **L0 Observe** *(default for assessors)* | analyze, score, report; no write to any system | read-only `Capability` |
| **L1 Draft** | draft the artifact (DPIA, policy, ticket, finding) for a human to file | stage tools; `require_human` on file |
| **L2 Approve** | take a remediating action after explicit sign-off (revoke access, quarantine, patch) | `require_human_actions`; consent `ask`/`dashboard` |
| **L3 Auto-under-threshold** | auto-remediate low-risk, well-bounded events (e.g. auto-quarantine on a high-confidence Shield block) | `require_human` above a confidence/severity floor *(build)* |
| **L4 Straight-through** | autonomous within policy; human reviews after the fact | reserved; hard-floored (4.2) |

Example: a SecOps agent can be **L3** to auto-quarantine a compartment on a
high-confidence exfil canary trip, **L2** to revoke a user's access, and **L0** for
everything advisory.

### 4.2 Hard floors — never auto, no matter the tier

The profile compiler refuses to lower these below L2 (human):

- **disabling or weakening a security control** (turning off the Shield, audit
  signing, egress lock, encryption);
- **granting or escalating privileged access**, or widening a capability;
- **closing/accepting a risk or audit finding**, or marking a control effective;
- **notifying a regulator or data subject** of a breach (legal act);
- **suppressing/deleting an alert or audit record**;
- anything the **kill switch** or a **latched quarantine seal** is holding.

### 4.3 Enabled frameworks (the regime union)

Which compliance packs are live: **SOC 2, ISO 27001, HIPAA, PCI-DSS, GDPR, EU AI
Act, NIST CSF/AI-RMF, FedRAMP, CCPA**. Strictest-wins union — exactly the
architecture's pluggable-regime model (§7). A US SaaS enables SOC 2 + GDPR + EU AI
Act; a healthcare client adds HIPAA; a fed client adds FedRAMP/NIST 800-53.

### 4.4 Enabled towers/agents & maturity

The roster is a menu (§3.4 of the finance suite). A 30-person startup runs
AI-Gov + Privacy + SOC 2 compliance + vendor risk and skips IAM/CMDB/vuln
towers; an enterprise runs all ten. A **maturity dial** (startup / growth /
enterprise) sets default cadences (access-review frequency, vuln SLA, evidence
refresh) and how strict the SoD linter is.

### 4.5 Deployment posture & residency

`enterprise.py` egress lock on/off, self-hosted vs cloud LLM, per-region data
residency, encryption-at-rest, retention windows, SIEM endpoint — all existing
knobs, scoped per tenant.

### 4.6 The GRC Operating Profile (one bundle)

Like the Finance Operating Profile: one signed, versioned object (intake produces,
the wizard edits, rule 6) that compiles to capabilities + governance policy +
consent config + enabled regimes + cadences. It is itself audited, so *"what is
this tenant's security posture, and who approved it?"* is an audit-trail question —
and `soc2.py`/`compliance.py` already report most of it live.

---

## 5. The roster — ten towers

~45 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**, and
**Status** (+ the module it builds on). Connectors marked `‹build›` don't exist
yet (§9). A representative pack per tower is full TOML; the rest are spec rows.

---

### Tower 1 — AI Governance & Agent Oversight

Governs the AI estate — *including this fleet*. The highest-leverage tower because
the platform already emits most of the evidence.

#### 1.1 AI Inventory & Registry Agent
- **Job:** Maintain the inventory of AI systems, models, and **agents** in use —
  owner, purpose, data touched, risk tier, lifecycle state. The "what AI do we even
  run" register every framework now demands.
- **Connects to:** `fleet.py` (the live agent roster), the domain packs, model
  hubs (`Hugging_Face`), `knowledge_search`.
- **Capability:** read fleet/packs/configs, `draft_ai_inventory`. No writes.
- **Controls:** read-only; the registry is itself audited.
- **Status:** **Gap** (no inventory module) — but `fleet.py` + `domain.py` are the
  data source; this is a reader, not new infrastructure.

#### 1.2 AI Risk Assessment (AIRA) Agent
- **Job:** Run the NIST AI RMF / EU AI Act risk assessment on an AI system: purpose,
  prohibited/high-risk screen, oversight, bias, robustness, data governance, logging.
- **Connects to:** the assessment engine; subject docs (`knowledge_search`).
- **Capability:** the `_AIRA` assessment tools only (drafts findings; never approves).
- **Status:** **Shipped** — `assessment.py` `_AIRA` + `build_assessment_agent`; this
  is a persona wrapper, nothing more.

#### 1.3 EU AI Act Conformity Agent
- **Job:** Classify the system's risk tier (Art 5 prohibited / Annex III high-risk /
  Art 50 limited), report Art 12/14/50 posture, and assemble the high-risk
  **technical-documentation + conformity** scaffold.
- **Connects to:** `ai_act.py`, `compliance.py` (Art 50 status), deployment config.
- **Capability:** read posture + `assess_ai_act`, `draft_conformity_docs`.
- **Status:** **Partial** — classification + Art 50 **shipped** (`ai_act.py`,
  `maverick ai-act`); the conformity/technical-documentation pack is the gap.

```toml
# packages/maverick-core/maverick/domains/aigov_oversight.toml
name = "aigov_oversight"
compartment = "ai_governance"
description = "AI governance: inventory, risk tiering, EU AI Act + NIST RMF posture."

persona = """You are the AI Governance specialist. Classify every AI system by its
EU AI Act tier and NIST RMF profile, cite the exact article/Annex, and read the
live deployment posture before you opine. You DRAFT inventories, risk assessments,
and conformity documentation for a human owner (DPO / AI risk officer) to approve
-- you never attest conformity, never disable a safeguard, and never approve your
own assessment. Mark anything you cannot verify from evidence as 'unverified'."""

allow_tools = [
    "read_file", "knowledge_search", "web_search",
    "assess_ai_act", "run_assessment", "draft_ai_inventory", "draft_conformity_docs",
]
deny_tools = ["shell", "write_file"]
max_risk = "low"
knowledge_sources = ["ai_governance", "privacy_compliance"]
authoring = "manual"
```

#### 1.4 Model & Agent Card / Transparency Agent
- **Job:** Generate **model/agent cards** — intended use, limitations, training-data
  provenance, eval results, out-of-scope uses; mark AI-generated content (Art 50).
- **Connects to:** model registry (`Hugging_Face`), eval results, the AI inventory.
- **Capability:** read + `draft_model_card`. No writes.
- **Status:** **Gap** (no model-card generator).

#### 1.5 Bias & Fairness Evaluation Agent
- **Job:** Evaluate consequential-decision systems for **bias across protected
  groups** (NYC LL144, Colorado ADMT, EEOC), produce the bias-audit export.
- **Connects to:** the eval harness, representative datasets, model endpoints.
- **Capability:** read + `run_bias_eval`. No writes.
- **Status:** **Gap** — an eval harness exists, but no fairness/bias evaluation.

#### 1.6 Agent Oversight / Supervisor Agent
- **Job:** The live operator over the fleet — monitor running agents, enforce org
  policy, **approve / deny / pause / kill**, latch/clear quarantine seals. The
  human-facing surface for every `REQUIRE_HUMAN` verdict. *(This is the §6
  control plane, personified.)*
- **Connects to:** `governance.py`, `fleet.py`, `quarantine.py`, `killswitch.py`,
  the consent dashboard, the audit chain.
- **Capability:** read all fleet activity + `pause_agent`, `kill_agent`,
  `quarantine_compartment`, `decide_approval`. **Denies** widening any grant.
- **Status:** **Partial** — the primitives are **shipped** (governance, consent,
  killswitch, quarantine, fleet); the operator **console** is the Layer-A roadmap gap.

#### 1.7 AI Incident Response Agent
- **Job:** Triage AI incidents (harmful output, jailbreak success, drift, a Shield
  block), classify severity, drive containment (quarantine/kill), and run the
  post-incident review.
- **Connects to:** Shield events + audit log (read), `quarantine.py`/`killswitch.py`.
- **Capability:** read events + `open_incident`, `quarantine_compartment` (L2+).
- **Controls:** containment actions `require_human` (hard floor); independence from
  the agent that caused the incident.
- **Status:** **Gap** (workflow) on **shipped** containment primitives.

---

### Tower 2 — Privacy / Data Protection

The most complete tower today — mostly persona wrappers over shipped engines.

#### 2.1 DPIA / PIA Agent
- **Job:** Produce the GDPR Art 35 DPIA and ISO 29134 PIA — describe processing,
  assess necessity/proportionality, build the risk register, propose measures.
- **Connects to:** `dpia.py`, `ropa.py` (shared description), the PIA template.
- **Capability:** `generate_dpia` + the `_PIA` assessment tools (drafts; the
  residual-risk sign-off is the controller's).
- **Status:** **Shipped** — `dpia.py` (`maverick dpia`) + `_PIA`.

#### 2.2 ROPA / Records Agent
- **Job:** Maintain the Art 30 Records of Processing Activities.
- **Connects to:** `ropa.py`, deployment config.
- **Capability:** `generate_ropa`. No writes.
- **Status:** **Shipped** — `ropa.py` (`maverick ropa`).

#### 2.3 Data-Subject Rights (DSAR) Agent
- **Job:** Fulfill access/portability (Art 15/20) and erasure (Art 17) requests;
  assemble the subject bundle and (on approval) erase + re-anchor the audit chain.
- **Connects to:** `dsar.py`, `audit/erase.py`, the world model.
- **Capability:** `export_subject_data` (read) + `erase_subject` **gated**
  (`require_human` — irreversible).
- **Status:** **Shipped** — `dsar.py`, `audit/erase.py` (`maverick dsar`/`erase`/`export-user`).

```toml
# packages/maverick-core/maverick/domains/privacy_dpo.toml  (extends privacy_compliance)
name = "privacy_dpo"
compartment = "privacy_compliance"
description = "Data-protection officer: DPIA/ROPA/DSAR, transfers, retention, breach."

persona = """You are the Data Protection specialist (DPO desk). Cite the exact
GDPR/CCPA article for every finding, distinguish controller vs processor roles, and
read the live compliance posture before you conclude. You DRAFT DPIAs, ROPAs, and
DSAR bundles and PROPOSE erasures for a human DPO to approve -- you never erase
data, notify a regulator, or sign off residual risk yourself. Treat all subject
data as confidential and never echo identifiers."""

allow_tools = [
    "read_file", "knowledge_search",
    "generate_dpia", "generate_ropa", "export_subject_data", "run_assessment",
    "draft_breach_notice",
]
deny_tools = ["erase_subject", "shell", "write_file"]  # erasure is human-gated
max_risk = "low"
knowledge_sources = ["privacy_compliance"]
authoring = "manual"
```

#### 2.4 Data Mapping & Classification Agent
- **Job:** Discover and **classify** personal/sensitive data across stores, map data
  flows, tag by category/purpose, feed the ROPA and DPIA.
- **Connects to:** the data stores (read), `safety/pii_detector.py`, `ropa.py`.
- **Capability:** read + `classify_data`, `draft_data_map`.
- **Status:** **Partial** — `pii_detector` classifies and `ropa` enumerates stores;
  a data-flow map + classification tagging is the gap.

#### 2.5 Consent Management Agent
- **Job:** Manage **data-subject** consent by purpose/category, withdrawal, and the
  consent ledger (distinct from the *action*-consent gate).
- **Connects to:** consent records store `‹build›`, `compliance.py` (Art 50 disclosure).
- **Capability:** read + `record_consent`, `withdraw_consent`.
- **Status:** **Partial** — action-consent + Art 50 disclosure **shipped**
  (`consent.py`, `compliance.py`); a purpose-level subject-consent ledger is the gap.

#### 2.6 Breach Response & Notification Agent
- **Job:** Assess a personal-data breach, run the **72-hour** notification clock
  (Art 33/34), draft regulator + data-subject notices, track the timeline.
- **Connects to:** the audit/incident log (read), regulator templates (knowledge).
- **Capability:** read + `assess_breach`, `draft_breach_notice`. **Denies** sending
  (notification is a hard-floor human act).
- **Status:** **Gap** (workflow).

#### 2.7 Cross-Border Transfer Agent
- **Job:** Map international transfers, check adequacy/SCCs, run the **Transfer
  Impact Assessment**.
- **Connects to:** `enterprise.py` (egress/residency), `ropa.py` (transfers), `_PIA`.
- **Capability:** read posture + `draft_tia`.
- **Status:** **Partial** — egress lock pins residency (**shipped**); the TIA workflow is the gap.

#### 2.8 Retention & Minimization Agent
- **Job:** Define and enforce retention schedules; minimize/anonymize.
- **Connects to:** `audit/retention.py`, `privacy.py`.
- **Capability:** `enforce_retention` (gated), `anonymize`.
- **Status:** **Shipped** — `audit/retention.py`, `privacy.py` (`maverick retention`).

---

### Tower 3 — GRC core: Risk, Policy & Compliance

#### 3.1 Multi-Framework Compliance Agent
- **Job:** Manage posture across **SOC 2 / ISO 27001 / HIPAA / PCI / NIST**; map
  controls, run gap analysis, track remediation, produce the coverage report.
- **Connects to:** `compliance.py`, `soc2.py`, the control library (knowledge).
- **Capability:** read posture + `compliance_report`, `collect_soc2_evidence`,
  `run_assessment`. No control mutation.
- **Status:** **Partial** — SOC 2 + GDPR + EU AI Act **shipped**
  (`soc2.py`, `compliance.py`); ISO 27001 / HIPAA / PCI packs are the gap (§7).

```toml
# packages/maverick-core/maverick/domains/grc_compliance.toml
name = "grc_compliance"
compartment = "grc_assurance"
description = "Multi-framework compliance posture, control mapping, and evidence."

persona = """You are the Compliance & Controls specialist. Map every control to its
framework criterion (SOC 2 TSC, ISO 27001 Annex A, HIPAA safeguard, PCI requirement)
and cite it; read the live posture (soc2 evidence, compliance report) before you
opine; mark a control 'unverified' unless you have seen the evidence. You DRAFT gap
analyses and evidence packages and RAISE deficiencies for a human control owner --
you never mark a control effective, accept a risk, or disable a control yourself."""

allow_tools = [
    "read_file", "knowledge_search",
    "compliance_report", "collect_soc2_evidence", "run_assessment", "audit_verify",
]
deny_tools = ["shell", "write_file"]
max_risk = "low"
knowledge_sources = ["grc_controls", "privacy_compliance"]
authoring = "manual"
```

#### 3.2 Evidence Collection / Audit-Readiness Agent
- **Job:** Continuously collect control evidence and assemble the auditor package
  (the SOC 2/ISO field-work bundle).
- **Connects to:** `soc2.py`, `audit/export.py`, all control surfaces (read).
- **Capability:** read + `collect_evidence`, `assemble_audit_package`. **Denies**
  external send (sharing with auditors is human-gated).
- **Status:** **Partial** — `collect_soc2_evidence` + CEF export **shipped**;
  continuous + multi-framework collection is the gap.

#### 3.3 Risk Management / ERM Agent
- **Job:** Maintain the **enterprise risk register** + KRIs, score risks, track
  treatment/remediation, draft risk-committee reporting.
- **Connects to:** the risk register `‹build›`, the assessment results, audit findings.
- **Capability:** read + `update_risk_register` (draft), `build_risk_report`.
- **Status:** **Gap** — assessments are point-in-time; no register/continuous scoring.

#### 3.4 Policy Management Agent
- **Job:** Policy **lifecycle** — author, review, version, attestation, exceptions;
  map policies to controls.
- **Connects to:** the policy repository (`Google_Drive`/knowledge).
- **Capability:** read + `draft_policy`, `track_attestation`. **Denies** publishing.
- **Status:** **Gap**.

#### 3.5 Control Testing & Continuous Monitoring Agent
- **Job:** Test control **operating effectiveness** (sampled, evidence-cited) and
  continuously monitor that live controls stay enabled (drift detection).
- **Connects to:** `governance.py` (`evaluate`/policy), `soc2.py` probes, audit log.
- **Capability:** read + `test_control`, `monitor_control_drift`, `log_deficiency`.
- **Status:** **Partial** — point-in-time probes **shipped** (soc2, governance);
  continuous monitoring + drift detection is the gap.

#### 3.6 Regulatory Change Management Agent
- **Job:** Track regulatory changes (new laws, framework revisions), map to affected
  controls, assess impact.
- **Connects to:** `web_search`, regulatory feeds, `CourtListener`, the control library.
- **Capability:** read + `draft_reg_change_impact`.
- **Status:** **Gap**.

---

### Tower 4 — Internal Audit & Assurance

The independent (third-line) tower — **read-only over everything, remediates nothing.**

#### 4.1 Internal Audit Agent
- **Job:** Risk-based audit planning, fieldwork, workpapers, findings, follow-up.
- **Connects to:** all GRC/IT/security surfaces (read), the audit chain.
- **Capability:** read-only + `draft_workpaper`, `log_finding`.
- **Status:** **Gap** (workflow) — mirrors finance Tower 5.

#### 4.2 Controls Assurance & SoD Agent
- **Job:** Independently verify controls and **monitor access/SoD conflicts across
  the fleet** (no compartment holding incompatible duties; capability-grant review).
- **Connects to:** `capability.py` grants, the packs, audit log.
- **Capability:** read-only + `sod_conflict_scan`, `verify_control`.
- **Status:** **Partial** — the capability model makes conflicts detectable
  (**shipped**); the **SoD/access-conflict linter** is the gap (shared with 9.2).

#### 4.3 External Audit / Certification Liaison (PBC) Agent
- **Job:** Manage the SOC 2 / ISO **prepared-by-client** list, package evidence,
  track open items, draft responses; offer auditors `maverick audit verify` as the
  tamper-evidence anchor.
- **Connects to:** `soc2.py`, `audit/`, document repo.
- **Capability:** read + `assemble_evidence_package`. **Denies** external send (human).
- **Status:** **Partial** on the shipped evidence collector.

---

### Tower 5 — Third-Party / Vendor Risk

#### 5.1 Vendor Risk Assessment Agent
- **Job:** Run the TPRM assessment (SOC 2, DPA, encryption, access, breach history,
  subprocessors, residency, incident SLA, deletion, BC).
- **Connects to:** the `_VENDOR_RISK` template; vendor docs (`knowledge_search`).
- **Capability:** the vendor-risk assessment tools (drafts; never approves a vendor).
- **Status:** **Shipped** — `assessment.py` `_VENDOR_RISK` + assessor.

#### 5.2 Subprocessor Inventory & DPA Agent
- **Job:** Maintain the **subprocessor registry** + change-notification workflow;
  track DPAs and their terms.
- **Connects to:** vendor/subprocessor store `‹build›`, `ropa.py` (recipients), contracts.
- **Capability:** read + `update_subprocessor_registry` (draft), `track_dpa`.
- **Status:** **Gap** — ROPA lists recipients only; no dedicated registry/notifications.

#### 5.3 Continuous Vendor Monitoring Agent
- **Job:** Monitor vendors for breaches, SOC 2 expiry, posture changes; re-trigger
  assessment on a material change.
- **Connects to:** breach feeds, vendor trust pages `‹build›`, the assessment engine.
- **Capability:** read + `flag_vendor_change`, `run_assessment`.
- **Status:** **Gap**.

---

### Tower 6 — Security Operations

#### 6.1 Runtime Threat Detection (Agent Shield)
- **Job:** Detect prompt injection, jailbreaks, exfiltration, RAG poisoning at
  runtime; trip canaries; filter unicode attacks. The chokepoint on every action.
- **Connects to:** the agent tool path (in-process), the audit log.
- **Capability:** the Shield runs as a kernel chokepoint, not a tool (fail-open per
  CLAUDE.md rule 1).
- **Status:** **Shipped** — `safety/{jailbreak_heuristics,remote_scan,canaries,unicode_filter,secret_detector,pii_detector}.py`.

#### 6.2 SIEM / Detection & Alert-Triage Agent
- **Job:** Forward security events to the SIEM, correlate, triage alerts, suppress
  noise (with a human floor), enrich.
- **Connects to:** `audit/export.py` (CEF), SIEM (Splunk/Sentinel) `‹build›`.
- **Capability:** read events + `triage_alert`, `enrich_alert`. **Denies**
  suppress/close (hard floor).
- **Status:** **Partial** — CEF export **shipped**; the live forwarder + correlation
  is the gap.

#### 6.3 Security Incident Response Agent
- **Job:** Run the IR lifecycle — detect → triage → **contain** (quarantine/kill) →
  eradicate → recover → PIR; maintain severity matrix and chain-of-custody.
- **Connects to:** `quarantine.py`, `killswitch.py`, the audit chain, SIEM.
- **Capability:** read + `open_incident`, `quarantine_compartment`, `trigger_halt`
  — all containment actions `require_human` (L2 hard floor).
- **Status:** **Partial** — containment primitives **shipped** (quarantine,
  killswitch, circuit breakers); the IR workflow/severity/PIR is the gap.

```toml
# packages/maverick-core/maverick/domains/secops_ir.toml
name = "secops_ir"
compartment = "security_operations"
description = "Security incident response: triage, containment, forensics, PIR."

persona = """You are the Security Incident Response specialist. Triage every event
against the severity matrix, preserve chain-of-custody (the signed audit chain is
your evidence), and drive the IR lifecycle. You PROPOSE containment -- quarantining
a compartment, revoking a grant, hitting the kill switch -- for a human responder to
approve; you execute nothing destructive on your own. State confidence and the
evidence for every call; never suppress or delete an alert or audit record."""

allow_tools = [
    "read_file", "knowledge_search", "audit_log_read",
    "open_incident", "triage_alert", "quarantine_compartment", "trigger_halt",
]
deny_tools = ["suppress_alert", "delete_audit", "widen_capability", "write_file"]
max_risk = "medium"
knowledge_sources = ["security_runbooks", "threat_intel"]
authoring = "manual"
```

#### 6.4 Threat Intelligence Agent
- **Job:** Ingest threat intel / IOCs / advisories, correlate to the environment,
  brief the SOC.
- **Connects to:** threat-intel feeds `‹build›`, `web_search`.
- **Capability:** read + `summarize_threat_intel`. No writes.
- **Status:** **Gap**.

---

### Tower 7 — AppSec & Supply Chain

#### 7.1 Secret Scanning Agent
- **Job:** Detect secrets/keys in code, logs, config, and outputs; redact before
  egress.
- **Connects to:** `safety/secret_detector.py`, GitHub secret scanning
  (`mcp__github__run_secret_scanning`).
- **Capability:** read + `scan_secrets`. Redaction is automatic at the chokepoint.
- **Status:** **Shipped** — `secret_detector.py` + the GitHub connector.

#### 7.2 SCA / Dependency & License Agent
- **Job:** Scan dependencies for **CVEs** and **license** risk; produce/check the
  **SBOM**.
- **Connects to:** `license_scan.py`, advisory DBs (OSV/GHSA) `‹build›`.
- **Capability:** read + `scan_licenses`, `scan_cves`, `generate_sbom`.
- **Status:** **Partial** — license scanning **shipped** (`license_scan.py`);
  CVE/SBOM is the gap.

#### 7.3 SAST / Secure Code Review Agent
- **Job:** Static analysis + secure-code review of diffs; flag injection, authz,
  crypto-misuse.
- **Connects to:** `reviewer.py`, the `/code-review` skill, GitHub Copilot review.
- **Capability:** read code + `review_diff`, `log_finding`. No writes to prod.
- **Status:** **Partial** — code review **shipped** (`reviewer.py` + skill);
  security-specific SAST rules are the gap.

#### 7.4 Supply-Chain / MCP & Plugin Trust Agent
- **Job:** Vet MCP servers and plugins before install — pinning, manifest review,
  provenance.
- **Connects to:** `mcp_registry.py` (`pin_sha256`), `plugin_manifest.py`.
- **Capability:** read + `vet_mcp_server`, `vet_plugin`. **Denies** install (gated).
- **Status:** **Partial** — pin/manifest validation **shipped**; a review workflow is the gap.

---

### Tower 8 — Vulnerability & Threat Management

Mostly greenfield — these are the clearest gaps.

#### 8.1 Vulnerability Management Agent
- **Job:** Aggregate scanner findings, prioritize (CVSS/EPSS + reachability), track
  remediation against SLA.
- **Connects to:** scanners (Tenable/Qualys/Wiz) + cloud config `‹build›`.
- **Capability:** read + `prioritize_vulns`, `track_remediation`. No patching.
- **Status:** **Gap**.

#### 8.2 Patch Management Agent
- **Job:** Track patch cadence/compliance, draft maintenance windows, verify
  remediation.
- **Connects to:** endpoint/patch systems `‹build›`, the asset inventory (10.1).
- **Capability:** read + `draft_patch_plan`. Patching itself `require_human`.
- **Status:** **Gap**.

#### 8.3 Attack-Surface & Pen-Test Coordination Agent
- **Job:** Map external attack surface, schedule pen tests, track findings to
  remediation; run red-team scenarios against the agents' own controls.
- **Connects to:** `safety/remote_scan.py`, `chaos.py`, ASM tools `‹build›`.
- **Capability:** read + `map_attack_surface`, `track_pentest`.
- **Status:** **Partial** — `remote_scan.py` + `chaos.py` exist; ASM/pen-test
  workflow is the gap.

---

### Tower 9 — Identity & Access Management

Strong for the **agent** identity layer (capabilities, OIDC); the **human/workforce**
IAM workflow is the gap.

#### 9.1 Joiner-Mover-Leaver (Provisioning) Agent
- **Job:** Orchestrate access provisioning/deprovisioning on lifecycle events;
  least-privilege at grant.
- **Connects to:** IdP (Okta/Entra) + HRIS `‹build›`, `capability.py` (agent side).
- **Capability:** read + `draft_access_change`. Grant/revoke `require_human` (hard floor).
- **Status:** **Gap** (workforce workflow) / **Process-only** — provisioning is an
  org action the agent orchestrates and evidences.

#### 9.2 Access Review / Recertification Agent
- **Job:** Periodic access **recertification** and least-privilege review across
  humans *and* agents — "who has what, and should they."
- **Connects to:** IdP `‹build›`, `capability.py` grants, the audit log.
- **Capability:** read + `build_access_review`, `flag_excess_privilege`,
  `sod_conflict_scan`. **Denies** revoke (human).
- **Status:** **Partial** — the capability model + audit make this computable for
  agents (**shipped**); the recertification workflow + IdP reach are gaps.

#### 9.3 Privileged Access (PAM) Agent
- **Job:** Just-in-time privileged access, session control, expiry enforcement.
- **Connects to:** `capability.py` (`max_risk`, `expires_at`), consent gating.
- **Capability:** read + `grant_jit_access` (time-boxed, gated).
- **Controls:** **runtime capability revocation/expiry enforcement** must be built —
  expiry *is* enforced at `permits()` (expired grants are denied at use-time); the gap is a
  **mid-session revocation sweep + a revocation list** for un-expired grants.
- **Status:** **Partial** (expiry enforced; JIT issuance + mid-session revocation are the gap).

#### 9.4 Authentication / SSO Posture Agent
- **Job:** Verify SSO/MFA coverage and configuration; report auth posture.
- **Connects to:** `oidc.py`, `proxy_auth.py`, `mcp_oauth.py`, IdP `‹build›`.
- **Capability:** read + `assess_auth_posture`.
- **Status:** **Partial** — OIDC/SSO verifier **shipped**; coverage reporting is the gap.

---

### Tower 10 — IT Operations & Resilience

The weakest area (per the inventory) — most agents here orchestrate/evidence
**Process-only** workflows on a thin shipped base.

#### 10.1 Asset & Configuration (CMDB) Agent
- **Job:** Maintain the asset/config inventory, baselines, and drift detection.
- **Connects to:** cloud/endpoint inventory `‹build›`, the AI inventory (1.1).
- **Capability:** read + `draft_cmdb`, `detect_config_drift`.
- **Status:** **Gap**.

#### 10.2 Change Management Agent
- **Job:** Change request → impact assessment → **approval** → audit → rollback.
- **Connects to:** ITSM/VCS `‹build›`, `governance.py` (approval), `checkpoint.py` (rollback).
- **Capability:** read + `draft_change_request`. Approval `require_human` (the
  governance gate); rollback via durable checkpoint.
- **Status:** **Partial** — approval gate + rollback primitives **shipped**; the
  change workflow is the gap.

#### 10.3 Observability / SRE Agent
- **Job:** Monitor health/SLOs, watch circuit breakers, surface anomalies, drive
  reliability.
- **Connects to:** `observability.py`, `health.py`, `circuit_breaker.py`, `monitor.py`.
- **Capability:** read telemetry + `summarize_health`, `flag_slo_breach`.
- **Status:** **Partial/Shipped** — the telemetry stack **ships**; the SRE persona is a wrapper.

#### 10.4 Backup & Disaster-Recovery Agent
- **Job:** Backup policy, point-in-time recovery, DR drills, BCP/BIA.
- **Connects to:** backup/storage systems `‹build›`, `checkpoint.py`/`job_queue.py`.
- **Capability:** read + `draft_backup_policy`, `run_dr_drill` (gated).
- **Status:** **Gap** — `checkpoint.py` is crash-resume, **not** backup/PITR/failover.

#### 10.5 Service Desk / ITSM Agent
- **Job:** Ticketing, request fulfillment, knowledge base, SLA tracking — the
  employee-facing front door for IT/security/privacy requests.
- **Connects to:** ITSM (ServiceNow/Jira) `‹build›`, the channel/intake layer.
- **Capability:** read + `triage_ticket`, `draft_resolution`. Fulfillment gated.
- **Status:** **Gap** — but the channels + `intake.py` give a head start.

---

## 6. The GRC Supervisor — oversight control plane (Layer A)

Above the towers sits the **GRC Supervisor** — the same Layer-A control plane the
architecture defines, here personified as Agent Oversight (1.6). It is the
hive-mind over the whole estate:

- **Routes** governance/privacy/security work to the right tower agent, respecting
  compartment seals.
- **Owns the approvals queue** — every `REQUIRE_HUMAN` verdict (erase data,
  grant access, quarantine, notify a regulator, disable a control) lands here with
  evidence attached.
- **Enforces least privilege across the fleet** — holds the parent capability;
  every agent is spawned attenuated, so independence (assurance ≠ operations) and
  SoD are guaranteed by construction.
- **Drives containment** — pause/kill/quarantine on a confirmed incident.

This is **the strongest already-built story in the suite**: `governance.py`,
`safety/consent.py`, `quarantine.py`, `killswitch.py`, `capability.py`, and
`fleet.py` are all shipped; the **operator console** (approve/deny/pause/kill UI) is
the named Layer-A gap in the enterprise architecture.

---

## 7. Compliance-regime packs (Layer B)

The architecture's pluggable, strictest-wins regime model — each compiles to a
governance `Policy` + an evidence mapping (generalize `compliance_report()` /
`collect_soc2_evidence()`).

| Regime pack | Status | Notes |
|---|---|---|
| **SOC 2 (TSC)** | **Shipped** | `soc2.py` collector + `soc2-controls.md` mapping. |
| **GDPR** | **Shipped** | `compliance.py` report + DPIA/ROPA/DSAR/erase/retention. |
| **EU AI Act** | **Shipped** | `ai_act.py` tiering + Art 50 disclosure + AIRA. |
| **NIST AI RMF** | **Partial** | AIRA template + audit/capabilities map to GOVERN/MAP/MEASURE/MANAGE; an RMF evidence report is the gap. |
| **US state (Colorado / NYC LL144 / CCPA)** | **Partial** | disclosure + consent gate shipped; bias-audit export (1.5) is the gap. |
| **ISO 27001 (Annex A)** | **Gap** | control mapping + Statement of Applicability to build. |
| **HIPAA** | **Gap** | Security/Privacy Rule safeguard mapping; capability path/host scopes + egress are the substrate. |
| **PCI-DSS** | **Gap** | no-PAN storage + secret redaction are the substrate; the requirement mapping is to build. |
| **NIST CSF / 800-53** | **Gap** | for fed/enterprise. |
| **FedRAMP** | **Gap** | heavy; build last, on the 800-53 pack. |

---

## 8. Assessment templates to add

The `assessment.py` engine takes new types by **appending to `TEMPLATES`** — no new
code. Shipped: `pia`, `aira`, `vendor_risk`. Add:

| New `type` | Owner | Framework |
|---|---|---|
| `soc2_readiness` | Compliance (3.1) | SOC 2 TSC self-assessment |
| `iso27001` | Compliance (3.1) | ISO 27001 Annex A controls |
| `hipaa` | Compliance (3.1) | HIPAA Security/Privacy Rule |
| `pci_dss` | Compliance (3.1) | PCI-DSS v4 requirements |
| `access_review` | Access Review (9.2) | least-privilege / SoD self-assessment |
| `incident_severity` | SecOps IR (6.3) | severity classification triage |
| `bia` | DR (10.4) | Business Impact Analysis |
| `ai_model_card` | Model Card (1.4) | transparency / intended-use review |
| `data_classification` | Data Mapping (2.4) | sensitivity tagging |
| `threat_model` | AppSec (7.x) | STRIDE-style threat enumeration |

Each becomes a `run_assessment` capability on the owning agent and a conversational
assessor via the existing `build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Source control + code security** | GitHub (secret scanning, Copilot review, code scanning) | **✅ exists** | Secret scan (7.1), SAST (7.3) |
| **Model hub** | Hugging Face | **✅ exists** | AI inventory (1.1), Model cards (1.4) |
| **Docs / evidence / tickets-lite** | Google Workspace, Gmail | **✅ exists** | Policy (3.4), DSAR intake (2.3) |
| **Cloud platform docs/config** | Microsoft Learn (Entra/Azure) | **✅ exists (docs)** | IAM (T9), CMDB (10.1) |
| **Legal / regulatory** | CourtListener | **✅ exists** | Reg change (3.6) |
| **SIEM** | Splunk, Microsoft Sentinel, Elastic | ◻ build (P1 — CEF export already emits) | SecOps (6.2) |
| **Identity provider (IdP)** | Okta, Microsoft Entra | ◻ build (P1) | IAM (T9) |
| **ITSM** | ServiceNow, Jira | ◻ build (P2) | Change (10.2), ITSM (10.5) |
| **GRC platform** | Vanta, Drata, AuditBoard, ServiceNow GRC | ◻ build (P2) | Compliance (3.x), Evidence (3.2) |
| **Vuln / CSPM** | Tenable, Qualys, Wiz, Snyk | ◻ build (P2) | Vuln (8.1), SCA (7.2) |
| **EDR / endpoint** | CrowdStrike, Defender | ◻ build (P3) | SecOps (6.x), Patch (8.2) |
| **Cloud security (config/CSPM)** | AWS, Azure, GCP | ◻ build (P2) | CMDB (10.1), Vuln (8.1) |
| **Secrets vault / KMS** | HashiCorp Vault, cloud KMS | ◻ build (P3) | PAM (9.3), Secret scan (7.1) |
| **Threat intel** | MISP, commercial feeds | ◻ build (P3) | Threat intel (6.4) |

**Knowledge sources:** the control library / RCM, the policy repository, security
runbooks, the threat model (`docs/security/threat-model.md`), the SoA, prior audit
reports, and the data-flow map.

---

## 10. Build sequence

Wrap what's shipped first (fast wins), then close gaps controls-first.

1. **Persona wrappers over shipped engines (immediate).** Domain packs for the
   AIRA (1.2), DPIA/DPO (2.1–2.3, 2.8), Compliance (3.1–3.2), and Vendor-risk
   (5.1) agents — they're thin layers over `assessment.py`/`dpia.py`/`ropa.py`/
   `dsar.py`/`soc2.py`/`compliance.py`. Plus the new assessment templates (§8).
2. **The GRC Supervisor / operator console (§6).** Elevate the shipped governance +
   consent + quarantine + killswitch + fleet into the Layer-A approvals/oversight
   surface — the highest-leverage build and the keystone for every other tower.
3. **Mid-session capability-revocation sweep + the SoD/access-conflict linter** (expiry already enforced)
   (9.2/9.3/4.2) — close the two real primitive gaps the inventory found.
4. **SIEM forwarder + IR workflow** (6.2/6.3) on the CEF export + quarantine base;
   **breach + AI-incident workflows** (2.6/1.7).
5. **GRC depth:** risk register/ERM (3.3), policy lifecycle (3.4), continuous
   control monitoring (3.5); the ISO/HIPAA/PCI regime packs (§7).
6. **IT/Sec connectors + greenfield towers:** IdP→IAM (T9), vuln/CSPM→Tower 8,
   ITSM→change/service-desk (10.2/10.5), backup/DR (10.4), CMDB (10.1).
7. **Wizard + dashboard** (rule 6): regime toggles, connector setup, the GRC
   Operating Profile / automation-tier editor, and the live oversight console.

---

## 11. Honest caveats

- **Much of this domain is process, not code.** Real provisioning, access reviews,
  incident response, change control, and backups are **organizational** workflows
  the agents *orchestrate and evidence* — they don't replace the people or the
  systems of record. Flagged **Process-only** per entry; the inventory's #1 warning.
- **"Provides the controls and evidence" ≠ "certified."** No agent signs a SOC 2
  attestation, issues an ISO certificate, classifies its own AI Act tier as final,
  or notifies a regulator — those are human/auditor/legal acts the suite supports
  and audit-trails (same liability line as the shipped `compliance.py` disclaimer).
- **Don't rebuild what ships.** Towers 1–3 and 5 are largely persona wrappers; the
  temptation to re-implement DPIA/ROPA/AIRA/SOC 2 logic must be resisted — extend
  `assessment.py`/`compliance.py`/`soc2.py` instead.
- **Independence is load-bearing.** Assurance and assessor agents must stay
  read-only over what they assess; if an audit agent gains a remediation tool the
  whole second/third-line model collapses — the SoD linter (4.2) must gate it.
- **The fleet governs itself — keep the floor un-lowerable.** Because Tower 1
  governs the very agents it runs among, the §4.2 hard floors (never auto-disable a
  control, never self-approve, never widen a grant) are what stop a compromised or
  mis-configured oversight agent from dismantling the controls. They live in the
  profile compiler, not in per-tenant config.
- **Two enforcement gaps are real, not cosmetic:** runtime **capability
  revocation** (mid-session sweep + revocation list; expiry itself is already enforced) and the **access-conflict linter**.
  Until they land, PAM/JIT (9.3) and SoD claims (4.2) are partial.
