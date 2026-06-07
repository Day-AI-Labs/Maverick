# Legal agent suite — the General Counsel's office

**Status:** design / roadmap. Companion to the finance, IT-GRC, sales-GTM, HR,
product-engineering, and strategy/exec suites; indexed in
[`agent-suites-overview.md`](agent-suites-overview.md). Extends the shipped
[`legal.toml`](../../packages/maverick-core/maverick/domains/legal.toml) starter pack into
a full suite. ~31 agents across eight towers.

> **Legal is horizontal — it touches every other suite — and uniquely risky for AI.** A
> Legal agent that invents a case citation is not a bug, it's the failure mode that has
> already gotten lawyers *sanctioned* (the "fake citations" line of cases). So the
> distinctive control here is **citation integrity** — every authority verified against a
> real source (CourtListener is already wired) or marked unverified, never fabricated.
> Two more controls define the suite: **"research and analysis, not legal advice"** (a
> qualified attorney owns every position — the unauthorized-practice-of-law line), and
> **attorney-client privilege / conflicts** — which map onto the *same* `quarantine.py`
> ethical-wall primitive the Strategy suite uses for MNPI. The starter pack already
> encodes the spine; this fleshes out the office.

The cardinal rule, generalized verbatim from `legal.toml` and applied to every agent below:

> *Agents research, draft, review, and flag freely — **citing authorities precisely** — but
> they provide **research and analysis, not legal advice**; a qualified **attorney owns every
> legal position**, and nothing is **filed, served, signed, or sent to a third party**
> without explicit attorney confirmation in the same turn.*

---

## Contents

1. [What's already shipped — the reuse map](#1-whats-already-shipped--the-reuse-map)
2. [How a legal agent maps onto Maverick](#2-how-a-legal-agent-maps-onto-maverick)
3. [The control model (cross-cutting)](#3-the-control-model-cross-cutting)
4. [Per-client customization — the dials](#4-per-client-customization--the-dials)
5. [The roster — eight towers](#5-the-roster--eight-towers)
   - [Tower 1 — Legal Research & Knowledge](#tower-1--legal-research--knowledge)
   - [Tower 2 — Commercial Contracts (CLM)](#tower-2--commercial-contracts-clm)
   - [Tower 3 — Corporate, Governance & Securities](#tower-3--corporate-governance--securities)
   - [Tower 4 — Litigation, Disputes & E-Discovery](#tower-4--litigation-disputes--e-discovery)
   - [Tower 5 — Intellectual Property](#tower-5--intellectual-property)
   - [Tower 6 — Regulatory, Antitrust & Trade](#tower-6--regulatory-antitrust--trade)
   - [Tower 7 — Employment & Privacy Law](#tower-7--employment--privacy-law)
   - [Tower 8 — Legal Operations](#tower-8--legal-operations)
6. [The General Counsel Supervisor (Layer A)](#6-the-general-counsel-supervisor-layer-a)
7. [Compliance & governance packs (Layer B)](#7-compliance--governance-packs-layer-b)
8. [Assessment templates to add](#8-assessment-templates-to-add)
9. [Integrations catalog](#9-integrations-catalog)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. What's already shipped — the reuse map

| Existing capability | Module / surface | Status | Reused by |
|---|---|---|---|
| **The legal research persona** (cite precisely, not legal advice, human-confirm) | `domains/legal.toml` | **Shipped** | Tower 1; the spine of every pack |
| **Case-law / citation source** | CourtListener (live MCP) | **Shipped** | Research (1.1), Citation verification (1.2) |
| **Deep research** | `/deep-research`, `web_search`, `tools/semantic_scholar` | **Shipped** | T1, T6 |
| **Document handling** | `tools/{pdf_reader,ocr,pandoc_tool,confluence_tool,notion}`, `gdrive_tool` | **Shipped** | Contracts (T2), E-discovery (4.2) |
| **Privilege / conflict ethical walls** | `quarantine.py` (Rung-2 seals) + `capability.py` (compartment scopes) | **Shipped** | privilege & conflicts (§3.3/§3.4) — the keystone |
| **"Not legal advice" + human-confirm gate** | `legal.toml` persona + `governance.py` + `safety/consent.py` | **Shipped** | the legal-act gate (§3.5) |
| **Assessment engine** | `assessment.py` | **Shipped** | the legal templates (§8) |
| **Intake / channels** | `intake.py`, the channels layer | **Shipped** | Legal intake & triage (8.3) |
| **AI disclosure + audit chain** | `compliance.py`, the signed Merkle chain | **Shipped** | external comms; the record |
| **Regulatory / compliance, vendor DPAs** | the **GRC** suite | cross-suite | Regulatory (6.1), Privacy law (7.2) |
| **Employment law** | the **HR** suite (Tower 7 there) | cross-suite | Employment law (7.1) |
| **Privacy law (DPIA/ROPA/DSAR/DPA)** | the **privacy** suite | cross-suite | Privacy law (7.2) |
| **SEC, contracts, SOX, equity** | the **finance** suite | cross-suite | Securities (3.3), Equity (3.4) |
| **M&A deal docs, board, antitrust/HSR** | the **strategy/exec** suite | cross-suite | Corporate (T3), Antitrust (6.2) |
| **Order forms, marketing claims (FTC)** | the **GTM** suite | cross-suite | Contracts (2.x) |

**The genuine gaps:** the legal *workflow + systems of record* — CLM (contract drafting/
review/repository), e-discovery & legal-hold, matter management, outside-counsel/e-billing,
IP management, entity management — plus the **citation-verification pipeline** (CourtListener
is wired; "verify *every* cite or mark it unverified" is the enforcement to build) and the
**conflicts-check** system.

---

## 2. How a legal agent maps onto Maverick

Each agent is a [`DomainProfile`](../../packages/maverick-core/maverick/domain.py) pack
that **inherits the `legal.toml` spine** (cite precisely, not legal advice, human-confirm)
and adds a practice-area persona + tools. Two specifics:

- **Privilege and conflicts are sealed compartments**, exactly like Strategy's MNPI walls:
  a matter (especially litigation/M&A) runs in a `quarantine`-sealable compartment so
  privileged work-product cannot leak (waiving privilege) and conflicted matters are
  walled from each other.
- **Citation integrity is enforced at the tool layer**, not trusted to the model — a draft
  with an unverifiable authority is flagged, never shipped (§3.2).

---

## 3. The control model (cross-cutting)

### 3.1 Research and analysis, not legal advice (UPL)
Agents draft memos, contracts, briefs, and analyses; a **qualified attorney reviews and
owns** every legal position. The agent never holds itself out as giving legal advice or as
a lawyer. This is the `legal.toml` persona, enforced everywhere.

### 3.2 Citation integrity (the distinctive control)
**Every legal authority is verified against a real source** (CourtListener / the research
DBs) before it appears in a draft; an authority that cannot be verified is **flagged as
unverified and excluded**, never fabricated. This is the #1 legal-AI failure mode — the
suite treats a hallucinated citation as a hard error, not a stylistic slip. *Pipeline to
build on the shipped CourtListener connector.*

### 3.3 Attorney-client privilege & work-product
Privileged materials live in **sealed compartments** (`quarantine` + capability scope);
they are never disclosed outside the privilege (which would waive it), and the privilege
status of every document is tracked. Same Rung-2 seal Strategy uses for MNPI.

### 3.4 Conflicts of interest & ethical walls
A **conflicts check** precedes taking on a matter; conflicted matters are **walled** from
each other (separate compartments, no cross-access). Recusal is enforced structurally, not
promised.

### 3.5 No filing / serving / signing / sending without an attorney
Filing with a court/agency, serving a party, signing/executing a document, and sending to a
third party are `require_human` (attorney) — maker-checker for legal acts. A hard floor
(§4.2).

### 3.6 Legal hold & spoliation prevention
When a legal hold is in effect, the relevant materials **cannot be deleted or altered** —
a hard floor that overrides retention/erasure (note the tension with privacy's right-to-
erasure: a legal hold wins). Holds are issued, tracked, and released by humans.

### 3.7 Confidentiality & jurisdiction
Client/matter confidentiality (reuse PII/egress/encryption); every analysis names the
**governing jurisdiction and law** (law varies by jurisdiction — an un-scoped answer is
flagged).

### 3.8 The record
Every draft, citation check, privilege determination, conflicts check, and legal act is on
the signed Merkle audit chain — the malpractice-defense and ethics evidence trail.

---

## 4. Per-client customization — the dials

### 4.1 The automation ladder
Legal skews **L0/L1** (research, draft, flag) — output informs an attorney's decision.
**L2+** is reserved for non-substantive ops (intake routing, repository filing). **No legal
position, filing, or external send is ever above L1.**

### 4.2 Hard floors — never auto
- **filing / serving / signing / sending** to a court, agency, or third party;
- **waiving attorney-client privilege** (any disclosure outside the wall);
- presenting a **legal position as final/authoritative** without attorney review;
- **a fabricated or unverified citation** in any output;
- taking a matter with an **unresolved conflict**;
- **deleting or altering material under a legal hold** (spoliation).

### 4.3 Jurisdictions & practice areas
Which jurisdictions' law applies (US federal + states, EU, UK, multi-national), and which
**towers/practice areas** are enabled (a startup runs Contracts + Legal Ops + Research; an
enterprise GC runs all eight).

### 4.4 In-house vs. firm, playbooks & risk tolerance
In-house (business-counsel posture) vs. law-firm (client-matter posture); the **contract
playbook** (standard positions + fallbacks) the review agents enforce; and the risk
tolerance / escalation thresholds.

### 4.5 Matter & conflict-wall topology + the Legal Operating Profile
Which matters are walled (litigation, M&A, investigations), who is inside each wall, the
conflicts list — bundled into one signed, versioned Legal Operating Profile (intake
produces, wizard edits, rule 6) compiling to capability + the wall topology + the legal-act
gates + the playbook.

---

## 5. The roster — eight towers

~31 agents. For each: **Job**, **Connects to**, **Capability**, **Controls**, **Status**.
Heavy cross-references to GRC/HR/privacy/finance/strategy (don't duplicate). Representative
packs are TOML.

---

### Tower 1 — Legal Research & Knowledge

The shipped core (the `legal.toml` pack), expanded.

#### 1.1 Legal Research Agent
- **Job:** Research case law, statutes, and regulations; write research memos with precise,
  quoted authority.
- **Connects to:** CourtListener (live), `web_search`, `tools/semantic_scholar`, `knowledge_search`.
- **Capability:** research + `draft_memo` (read-only; no legal acts).
- **Controls:** citation integrity (§3.2); not legal advice (§3.1); jurisdiction-scoped.
- **Status:** **Shipped** (this *is* `legal.toml`).

```toml
# packages/maverick-core/maverick/domains/legal_research.toml  (extends legal.toml)
name = "legal_research"
compartment = "legal"
description = "Legal research and memo drafting with verified authority."

persona = """You are a Legal Research specialist. Cite authorities precisely (case name,
court, year) and quote the controlling text. VERIFY every citation against a real source
(CourtListener / the research database) before you use it; if you cannot verify an
authority, mark it [UNVERIFIED] and do not rely on it -- never invent a case, statute, or
quote. Name the governing jurisdiction. You provide research and analysis, NOT legal
advice, for a qualified attorney to review and own; you never file, serve, sign, or send
anything without explicit attorney confirmation in the same turn."""

allow_tools = ["read_file", "web_search", "knowledge_search", "verify_citation", "draft_memo"]
deny_tools = ["shell", "write_file", "file_document", "send_external"]
max_risk = "low"
mcp_servers = ["CourtListener"]
knowledge_sources = ["legal"]
authoring = "manual"
```

#### 1.2 Citation-Verification Agent
- **Job:** Verify every citation in a draft against a real source; flag or strip
  unverifiable authority; check quotes and pin-cites.
- **Connects to:** CourtListener (live), legal-research DBs (Westlaw/Lexis) `‹build›`.
- **Capability:** `verify_citation`, `flag_unverified`. Read-only.
- **Controls:** **the citation-integrity enforcement point** (§3.2) — the suite's signature control.
- **Status:** **Partial** (CourtListener shipped; the verify-everything pipeline is the build).

#### 1.3 Legal Knowledge-Management Agent
- **Job:** Maintain the internal precedent / clause / memo library; surface prior work.
- **Connects to:** `knowledge_search`, `tools/{confluence_tool,notion}`, the matter system.
- **Capability:** read + `index_precedent`, `retrieve_precedent`.
- **Status:** **Partial**.

---

### Tower 2 — Commercial Contracts (CLM)

The largest in-house workload — and the biggest legal-AI opportunity.

#### 2.1 Contract-Drafting Agent
- **Job:** Draft contracts from approved templates + the playbook (NDAs, MSAs, SOWs, DPAs).
- **Connects to:** CLM (Ironclad/Icertis) `‹build›`, template library (`knowledge_search`).
- **Capability:** `draft_contract`. **Denies** execution/signature.
- **Status:** **Gap/Partial** (templates via knowledge; CLM connector to build).

#### 2.2 Contract-Review & Redline Agent
- **Job:** Review third-party paper against the **playbook**, redline deviations, flag risk
  (liability, indemnity, IP, data, termination), summarize for the business.
- **Connects to:** CLM `‹build›`, the playbook (`knowledge_search`), privacy suite (DPA terms).
- **Capability:** read + `review_contract`, `redline`, `flag_risk`. **Denies** signing.
- **Controls:** playbook-grounded (cite the standard); attorney owns non-standard calls.
- **Status:** **Gap** (the flagship legal-AI agent).

```toml
# packages/maverick-core/maverick/domains/legal_contracts.toml
name = "legal_contracts"
compartment = "legal_contracts"
description = "Commercial contract review and redlining against the playbook."

persona = """You are a Commercial Contracts specialist. Review third-party paper against
THIS company's playbook; for every deviation, cite the playbook position, explain the risk
in business terms, and propose the fallback language. Redline precisely. You DRAFT and
redline for a human attorney to review, negotiate, and approve -- you never sign, execute,
or commit to terms. Flag (do not silently accept) any non-standard liability, indemnity,
IP-assignment, data-protection, or termination term, and route DPA/privacy terms to the
privacy desk. State 'outside playbook -- attorney review required' rather than guessing."""

allow_tools = [
    "read_file", "knowledge_search", "pdf_reader",
    "review_contract", "redline", "flag_risk",
]
deny_tools = ["sign_contract", "execute_document", "send_external", "shell"]
max_risk = "low"
mcp_servers = ["CLM_Ironclad"]   # ‹build›
knowledge_sources = ["legal_playbook", "legal_templates"]
authoring = "manual"
```

#### 2.3 Contract-Negotiation-Support Agent
- **Job:** Fallback positions, negotiation tracking, counterparty-position analysis.
- **Connects to:** CLM `‹build›`, the playbook.
- **Capability:** `propose_fallback`, `track_negotiation`. No commitments.
- **Status:** **Gap**.

#### 2.4 Obligations & Renewals Agent
- **Job:** Extract obligations/key terms, track renewals/milestones/auto-renews. *(Cross-ref
  finance for revenue/spend impact.)*
- **Connects to:** CLM `‹build›`, finance suite.
- **Capability:** read + `extract_obligations`, `track_renewals`.
- **Status:** **Gap**.

#### 2.5 Contract Repository & Intake Agent
- **Job:** Contract repository, intake/triage of requests, metadata/tagging, search.
- **Connects to:** CLM `‹build›`, `intake.py`, channels.
- **Capability:** `intake_contract_request`, `tag_contract`, `search_repository`.
- **Status:** **Gap**.

---

### Tower 3 — Corporate, Governance & Securities

(Largely **cross-referenced** to strategy/exec + finance.)

#### 3.1 Entity-Management Agent
- **Job:** Entity formation/maintenance, subsidiary management, registered agents, annual filings.
- **Connects to:** entity-mgmt (Diligent Entities) `‹build›`.
- **Capability:** read + `track_entity`, `draft_corporate_filing`. Filing gated.
- **Status:** **Gap**.

#### 3.2 Board & Governance Agent
- **Job:** Board materials, minutes, resolutions, governance. *(Cross-ref strategy/exec 6.1
  — sealed board compartment.)*
- **Connects to:** the strategy/exec board agent, `gdrive_tool`.
- **Capability:** read (walled) + `draft_resolution`, `draft_minutes`. No board decisions.
- **Controls:** sealed board compartment; privilege.
- **Status:** **Partial** (cross-ref).

#### 3.3 Securities & SEC Agent
- **Job:** Securities-law compliance, disclosure review, filing legal review. *(Cross-ref
  finance SEC-reporting tower.)*
- **Connects to:** the finance SEC tower, CourtListener (rules).
- **Capability:** read + `review_disclosure`, `flag_securities_risk`. Filing gated.
- **Status:** **Partial**.

#### 3.4 Equity & Cap-Table Legal Agent
- **Job:** Equity issuance legal, option grants, 409A legal, securities exemptions. *(Cross-
  ref finance equity/SBC.)*
- **Connects to:** cap-table system `‹build›`, the finance equity agent.
- **Capability:** read + `review_equity_doc`. No issuance.
- **Status:** **Partial**.

---

### Tower 4 — Litigation, Disputes & E-Discovery

The privilege/work-product tower — **sealed matter compartments**.

#### 4.1 Litigation-Management Agent
- **Job:** Case management, **docketing/deadlines**, strategy support, outside-counsel coordination.
- **Connects to:** matter system `‹build›`, `tools/calendar_tool`, CourtListener.
- **Capability:** read (walled) + `track_docket`, `draft_case_summary`. No filings.
- **Controls:** **deadline integrity** (missed deadlines = malpractice); sealed matter.
- **Status:** **Gap**.

#### 4.2 E-Discovery Agent
- **Job:** Document review, responsiveness/relevance coding, **privilege review & logging**,
  production prep.
- **Connects to:** e-discovery (Relativity/Everlaw) `‹build›`, `tools/{pdf_reader,ocr}`.
- **Capability:** read (walled) + `review_documents`, `log_privilege`. **Denies** production (human).
- **Controls:** **privilege protection** (§3.3) — mis-coding waives privilege; sealed compartment.
- **Status:** **Gap**.

#### 4.3 Legal-Hold Agent
- **Job:** Issue/track legal holds, custodian management, hold reminders, release.
- **Connects to:** the data stores, `audit/` (hold flags), HRIS (custodians).
- **Capability:** `issue_hold`, `track_custodians`. **Denies** deletion of held data (hard floor §3.6).
- **Controls:** **spoliation prevention** — a hold overrides retention/erasure.
- **Status:** **Gap** (the hold-vs-erasure interplay is a real build with the privacy suite).

#### 4.4 Brief & Motion-Drafting Agent
- **Job:** Draft briefs, motions, pleadings; build the table of authorities.
- **Connects to:** CourtListener (live), the matter (walled).
- **Capability:** `draft_brief`, `build_authorities`. **Denies** filing (attorney).
- **Controls:** **citation integrity** (§3.2) — the courtroom is where fabricated cites get sanctioned.
- **Status:** **Gap**.

#### 4.5 Settlement & Dispute Agent
- **Job:** Settlement analysis, demand/response letters, ADR support, exposure modeling.
- **Connects to:** the matter (walled), finance (exposure).
- **Capability:** `analyze_settlement`, `draft_demand`. **Denies** sending/committing.
- **Status:** **Gap**.

---

### Tower 5 — Intellectual Property

#### 5.1 Patent Agent
- **Job:** Patent/prior-art search, application support, portfolio management, maintenance.
- **Connects to:** USPTO/patent DBs `‹build›`, `tools/semantic_scholar`.
- **Capability:** search + `analyze_prior_art`, `draft_patent_support`. Filing gated.
- **Status:** **Gap**.

#### 5.2 Trademark Agent
- **Job:** Trademark clearance/search, filing prep, watch/monitoring, oppositions.
- **Connects to:** trademark DBs `‹build›`, `web_search`.
- **Capability:** `clear_trademark`, `draft_tm_filing`. Filing gated.
- **Status:** **Gap**.

#### 5.3 Copyright & Trade-Secret Agent
- **Job:** Copyright registration, trade-secret protection programs, DMCA, NDAs (cross-ref 2.1).
- **Connects to:** `knowledge_search`, the contracts tower.
- **Capability:** `draft_copyright`, `assess_trade_secret`.
- **Status:** **Gap**.

#### 5.4 IP Licensing & Infringement Agent
- **Job:** Licensing-deal support, infringement analysis, enforcement/cease-and-desist.
- **Connects to:** the contracts tower, CourtListener.
- **Capability:** `analyze_infringement`, `draft_license`. Enforcement sends gated.
- **Status:** **Gap**.

---

### Tower 6 — Regulatory, Antitrust & Trade

#### 6.1 Regulatory-Counsel Agent
- **Job:** Regulatory advice, applicability analysis, regulatory-change legal impact.
  *(Cross-ref GRC regulatory-change.)*
- **Connects to:** CourtListener, `web_search`, the GRC suite.
- **Capability:** research + `analyze_applicability`, `draft_reg_memo`.
- **Status:** **Partial** (GRC overlap).

#### 6.2 Antitrust & Competition Agent
- **Job:** Antitrust analysis, **HSR / merger review**, competition compliance. *(Cross-ref
  strategy/exec M&A.)*
- **Connects to:** the strategy M&A tower, CourtListener.
- **Capability:** `analyze_antitrust`, `draft_hsr_support`. No filings.
- **Status:** **Gap**.

#### 6.3 Trade & Sanctions Agent
- **Job:** Export controls (EAR/ITAR), **sanctions/OFAC**, trade compliance. *(Cross-ref
  finance AML + GRC + GTM screening.)*
- **Connects to:** sanctions screening `‹build›`, the GRC/finance suites.
- **Capability:** `screen_trade`, `analyze_export_control`. Decisions gated.
- **Status:** **Partial** (screening overlaps finance/GRC).

---

### Tower 7 — Employment & Privacy Law

(Both **cross-referenced** — the legal lens on functions HR/privacy own operationally.)

#### 7.1 Employment-Law Agent
- **Job:** Employment-law advice, policy legal review, dispute/claim analysis. *(Cross-ref
  HR Tower 7.)*
- **Connects to:** the HR employment-law agent, CourtListener.
- **Capability:** research + `review_employment_policy`, `analyze_claim`. Advice attorney-owned.
- **Status:** **Partial**.

#### 7.2 Privacy & Data-Protection-Law Agent
- **Job:** Privacy counsel, **DPAs**, breach legal analysis, GDPR/CCPA legal positions.
  *(Cross-ref the privacy suite — DPIA/ROPA/DSAR are operational there.)*
- **Connects to:** the privacy suite, CourtListener.
- **Capability:** `review_dpa`, `analyze_breach_legal`. Notification decisions human/attorney.
- **Status:** **Partial**.

---

### Tower 8 — Legal Operations

#### 8.1 Matter-Management Agent
- **Job:** Matter intake/triage, lifecycle, status reporting, prioritization.
- **Connects to:** matter system `‹build›`, `intake.py`.
- **Capability:** `manage_matter`, `report_status`.
- **Status:** **Gap**.

#### 8.2 Outside-Counsel & Spend Agent
- **Job:** Outside-counsel guidelines, **e-billing review**, spend analytics, panel management.
- **Connects to:** e-billing (Legal Tracker/Brightflag) `‹build›`, finance (spend).
- **Capability:** read + `review_invoice`, `analyze_legal_spend`. Approvals gated.
- **Controls:** SoD with finance AP (legal reviews, finance pays).
- **Status:** **Gap**.

#### 8.3 Legal-Intake & Triage Agent
- **Job:** Legal-request intake, routing to the right tower, self-service answers, SLA tracking.
- **Connects to:** `intake.py`, the channels layer, `knowledge_search`.
- **Capability:** `intake_request`, `route_matter`, `answer_faq`. Escalate substantive questions.
- **Controls:** AI disclosure; not legal advice (escalate, don't opine).
- **Status:** **Partial** (intake + channels shipped — a fast win).

#### 8.4 Legal-Tech & KM-Ops Agent
- **Job:** Legal tech stack, workflow automation, legal metrics/reporting.
- **Connects to:** the legal-ops tools, BI.
- **Capability:** `automate_workflow`, `report_legal_metrics`.
- **Status:** **Gap**.

#### 8.5 Conflicts-Check Agent
- **Job:** Run conflicts checks before matter intake; set up ethical walls.
- **Connects to:** the matter/entity system `‹build›`, `quarantine.py`/`capability.py`.
- **Capability:** `check_conflicts`, `propose_wall`. **Denies** clearing a conflict (human).
- **Controls:** the **ethical-wall setup point** (§3.4) — reuses the seal primitive.
- **Status:** **Partial** (the wall primitive ships; the conflicts DB/check is the build).

---

## 6. The General Counsel Supervisor (Layer A)

Above the towers sits the **GC Supervisor** — the legal instance of the oversight control
plane. It:

- **enforces privilege & conflict walls** — holds the parent capability and the matter-wall
  topology; spawns litigation/M&A/investigation agents into sealed compartments, and runs
  the conflicts check (8.5) before opening a matter;
- **owns the legal-act queue** — every filing, service, signature, external send, and
  privilege/legal-hold decision lands here for **attorney** approval;
- **enforces citation integrity** — no draft leaves a tower with an unverified authority;
- **records** every legal act, citation check, and privilege call to the signed chain.

Built on the shipped `quarantine.py` + `capability.py` + `governance.py` + `safety/consent.py`
+ CourtListener + the audit chain; the operator (attorney-review) console is the shared
Layer-A gap.

---

## 7. Compliance & governance packs (Layer B)

| Pack | Covers | Status |
|---|---|---|
| **Professional responsibility / UPL** | not legal advice, attorney ownership, competence/candor | **Shipped** (the `legal.toml` persona + the legal-act gate) |
| **Citation integrity** | verified authority, no fabrication | **Partial** (CourtListener shipped; the verify pipeline) |
| **Privilege & work-product** | privilege walls, no waiver | **Shipped** (`quarantine` seals) |
| **Conflicts / ethical walls** | conflicts check, matter isolation | **Partial** (seal primitive shipped; conflicts DB) |
| **Litigation hold / e-discovery (FRCP)** | hold, preservation, spoliation, production | **Gap** (the hold-vs-erasure build) |
| **Jurisdiction / governing law** | scope every answer to a jurisdiction | **Partial** (persona; per-client jurisdiction packs) |
| **Securities / corporate** | filings, disclosure, governance | cross-suite (**finance** + **strategy**) |
| **Employment / privacy / regulatory / antitrust / trade** | the substantive bodies of law | cross-suite (**HR / privacy / GRC / strategy**) |

---

## 8. Assessment templates to add

Append to the `assessment.py` engine (no new code):

| New `type` | Owner | Framework |
|---|---|---|
| `contract_risk_review` | Contracts (2.2) | playbook deviation / risk-term checklist |
| `conflicts_check` | Conflicts (8.5) | conflict-of-interest screen |
| `ip_clearance` | IP (5.x) | trademark/patent clearance |
| `litigation_hold_readiness` | Legal hold (4.3) | preservation / spoliation-risk check |
| `regulatory_applicability` | Regulatory (6.1) | does regulation X apply to activity Y |
| `privilege_review` | E-discovery (4.2) | privilege-determination checklist |

Each becomes a `run_assessment` capability + a conversational assessor via
`build_assessment_agent`.

---

## 9. Integrations catalog

Per CLAUDE.md rules 5 & 6, every connector ships a config knob + wizard toggle.

| System class | Vendors | Status | Used by |
|---|---|---|---|
| **Case law (citation source)** | CourtListener | **✅ live** | Research (1.1), Citation (1.2), Briefs (4.4) |
| **Research / docs** | web_search, Semantic Scholar, PDF, OCR, pandoc, Confluence, Notion, Drive | **✅ shipped** | T1, T2, T4 |
| **Intake / comms** | the channels layer, `intake.py` | **✅ shipped** | 8.3 |
| **Legal research DBs** | Westlaw, LexisNexis | ◻ build (P2) | 1.1, 1.2, 6.x |
| **CLM** | Ironclad, Icertis, DocuSign CLM | ◻ build (P1) | Contracts (T2) |
| **E-signature** | DocuSign, Adobe Sign | ◻ build (P2) | execution (attorney-gated) |
| **E-discovery** | Relativity, Everlaw | ◻ build (P2) | 4.2 |
| **Matter / practice management** | Litera, Clio, legal-tech | ◻ build (P2) | T4, T8 |
| **E-billing / outside counsel** | Legal Tracker, Brightflag | ◻ build (P3) | 8.2 |
| **IP management** | USPTO, patent/TM DBs, Anaqua | ◻ build (P3) | T5 |
| **Entity management** | Diligent Entities | ◻ build (P3) | 3.1 |

**Knowledge sources:** the contract **playbook** + template library, prior memos/precedent,
corporate records, the matter files (per-matter, sealed), and the jurisdiction-specific law
library.

---

## 10. Build sequence

Lead with the shipped research core + the citation/privilege controls, then the workflows.

1. **Citation-integrity pipeline + privilege/conflict walls (do this first).** The
   verify-every-cite enforcement on CourtListener (1.2), the conflicts check + ethical-wall
   setup on `quarantine`/`capability` (8.5), and the legal-act gate. Plus the legal
   assessment templates (§8). *No legal draft ships with an unverified cite; no matter opens
   with an unresolved conflict.*
2. **Extend the research pack + fast wins:** Legal Research (1.1, shipped) + KM (1.3) +
   Legal Intake (8.3) on intake/channels.
3. **Contracts (Tower 2)** on a CLM connector — Review & Redline (2.2) is the flagship.
4. **Litigation (Tower 4)** inside sealed matter compartments — Legal Hold (4.3, with the
   privacy suite) and Brief drafting (4.4, citation-gated).
5. **Cross-ref towers** (Corporate/Securities → finance+strategy; Employment/Privacy → HR+
   privacy; Regulatory/Antitrust/Trade → GRC+strategy) wired as references, not forks.
6. **IP (Tower 5)** + **Legal Ops depth** (matter/spend/legal-tech, Tower 8).
7. **Wizard + dashboard** (rule 6): jurisdiction/practice-area toggles, the Legal Operating
   Profile / playbook / conflict-wall editor, and the attorney-review console.

---

## 11. Honest caveats

- **Not legal advice — full stop.** Every output is research and drafting for a qualified
  attorney to review and own; the suite never practices law, and "competent supervision" is
  the human's, not the agent's. The `legal.toml` persona is the line.
- **A fabricated citation is a hard error, not a stylistic slip.** This is the failure mode
  that gets lawyers sanctioned; citation verification (§3.2) is the suite's signature
  control and gates every draft.
- **Privilege is fragile and waiver is forever.** Privileged work-product lives behind the
  ethical wall (the `quarantine` seal); any disclosure outside it can waive privilege for
  everyone — the wall is structural, not a promise.
- **Legal holds beat erasure.** When a hold is in effect, preservation overrides the
  privacy suite's retention/right-to-erasure — the two suites must reconcile, with the hold
  winning (spoliation is the worse outcome).
- **This suite is horizontal — it mostly cross-references.** Securities → finance;
  employment → HR; privacy ops → privacy; regulatory → GRC; M&A/board → strategy. The deep,
  legal-owned towers are Contracts, Litigation, and IP; the rest is the legal lens on work
  another suite performs.
- **Jurisdiction and counsel.** Law varies by jurisdiction and the hard calls are an
  attorney's; the suite scopes every answer to a jurisdiction and routes judgment to
  qualified counsel.
