# Council expansion review — net-new skills & agents (2026)

> **Status:** proposal / brainstorm output. Convened June 2026 by a six-seat
> adversarial council against the shipped roster (1,022 agent packs + the skills
> layer). This document is **what the council came up with** — a gap analysis and
> a backlog of net-new agents and skills, each grep-verified absent and written to
> the real `DomainProfile` / `SKILL.md` schemas. Nothing here is built yet; it is
> the menu to green-light from. Companion to
> [`agent-skills-catalog.md`](agent-skills-catalog.md) and
> [`agent-suites-overview.md`](agent-suites-overview.md).

## The headline finding

The council's strongest, unanimous observation: **the roster is the part that is
done; the skills library is the part that is empty.** There are **1,022 agent
TOML packs** under `packages/maverick-core/maverick/domains/` and **exactly one
`SKILL.md` in the whole repository** (the `summarize-url` toy under
`docs/specs/catalog-example/`). The machinery to load, rank, distill, validate,
sign, and install skills (`maverick/skills.py`) is fully built — and is being fed
almost nothing.

So the highest-leverage, lowest-risk, most additive move is **not** agent #1,023.
It is to author a **cross-cutting skills library** that hundreds of the existing
packs inherit for free via the `relevant_skills` trigger mechanism, plus a small
set of platform seats that keep that library alive — and then only the handful of
genuinely net-new specialist seats and verticals that survived an adversarial
dedup pass.

A second finding, reported independently by five of six seats: **the on-disk
roster is materially deeper than the design docs claim.** The IT/GRC suite already
ships DORA, NIS2, SEC 8-K, OT/ICS, CSPM, SSPM; HR ships 17 jurisdiction packs and
worker-classification; legal ships ~15 privacy-law packs. Every proposal below was
therefore checked against the actual `domains/` directory, not the docs, and the
"obvious" seats were deliberately rejected as duplicates.

## How the council ran

Six adversarial seats reviewed the roster in parallel, each given the real pack +
`SKILL.md` schemas, the existing family counts (to force net-new), and the kernel
control rules. Each returned proposed agents, proposed skills, and — required of
every seat — **anti-recommendations** naming where the roster is already saturated.

| Seat | Lens | Returned |
|---|---|---|
| 1 | Finance / Tax / Treasury / Banking / Insurance-finance (ex-CFO/CPA/CIA) | 12 agents · 9 skills |
| 2 | IT / GRC / Security / Privacy / AI-Governance (ex-CISO/DPO) | 12 agents · 8 skills |
| 3 | Revenue / GTM / RevOps / Marketing / CX (ex-CRO/CMO) | 11 agents · 8 skills |
| 4 | HR / People & Legal (ex-CHRO/GC) | 11 agents · 8 skills |
| 5 | Product / Eng / Data-ML / Ops / Supply-chain (ex-CTO/COO) | 13 agents · 8 skills |
| 6 | Cross-cutting platform & skills auditor (the honesty seat) | 20 cross-cutting skills · 7 platform seats · 6 verticals · dedup pushback |

**Totals: 66 net-new specialist/platform agents · 6 new industry verticals
(~25 flagship seats) · 61 skills (20 cross-cutting + 41 suite-specific).**

Every proposal preserves the platform's control invariants (see the appendix):
agents draft, humans approve/post/pay/file/certify; assurance seats are read-only
and independent of what they review; hard floors (`require_human`) on money,
filings, regulator/subject notification, privileged-access grants, and
safety-critical actuation are never lowered; confidentiality via compartment
seals; never hard-code models; budget caps mandatory; additive only.

---

## Part 1 — The cross-cutting skills library (20) · the headline contribution

Reusable procedural methods authored to the `skills.py` contract (kebab `name`,
`triggers`, `tools_needed`; body `# What this skill does` / `# Steps` / `# Notes`).
Each is *mechanically followable*, cites exact tool calls, and — the whole point —
is inherited by **many** existing packs at zero marginal pack-authoring cost. None
calls a model directly; none performs a `require_human` action (they draft / stage
/ check).

### A. Universal baseline — rides along with ~all 1,022 packs

| `name` | `triggers` | `tools_needed` | What it does |
|---|---|---|---|
| `cite-sources-or-mark-unverified` | cite sources · is this verified · back this claim | `knowledge_search`, `web_search` | Attaches a source to every factual claim; tags anything unsourced `[unverified]` instead of guessing — the platform's core honesty rule, mechanized. |
| `draft-for-human-review` | prepare for approval · stage this · draft for sign-off | `read_file` | Produces a review-ready artifact with an explicit Decision-required / Approver / What-changed / Open-questions header so a human approves in one pass. |
| `write-to-audit-trail` | log this decision · record to audit · evidence this | `audit_append` | Writes a structured, signed audit entry (action, inputs, source refs, confidence) so the work is provable and revocable. |
| `redact-pii-before-egress` | redact before sending · scrub PII · safe to share? | `read_file`, `pii_scan` | Runs the PII/secret detector over any externally-bound payload and masks special-category data before it leaves the compartment. |
| `extract-from-document` | pull data from this PDF · extract the table · OCR this | `read_file`, `extract_document` | Deterministic field/table extraction with per-field confidence and a "could not read" flag rather than hallucinated values. |
| `meeting-to-action-items` | turn notes into actions · action items from this · follow-ups | `read_file` | Converts a transcript/notes into owner-dated action items + decisions + open questions in a fixed schema. |

### B. Platform / governance discipline — the seats that touch money, filings, access, safety

| `name` | `triggers` | `tools_needed` | What it does |
|---|---|---|---|
| `require-human-gate-checklist` | does this need approval · is this a hard floor · can I do this myself | `read_file` | Checks an action against the hard-floor list (money/filing/regulator-notify/privileged-access/safety) and routes to `require_human` if it trips — encodes the L0–L4 automation-ladder decision. |
| `segregation-of-duties-self-check` | SoD check · am I conflicted · can I both make and approve | `read_file` | An agent verifies its own action doesn't violate maker/checker/custody separation and refuses if it would. |
| `redact-secrets-in-output` | scan for secrets · no credentials in logs · safe to commit | `read_file`, `secret_scan` | Entropy + pattern scan to strip API keys/tokens/PANs from code, logs, or config before commit/share. |
| `structured-questionnaire-run` | run the assessment · work through this questionnaire · score this control | `start_assessment`, `answer_question`, `finalize_assessment` | Drives the shipped assessment flow end-to-end, evidence-citing each answer and returning "unknown" honestly where evidence is absent. |
| `evidence-cited-finding` | write a finding · rate this risk · audit finding | `knowledge_search`, `read_file` | Emits a finding as {condition, criteria, cause, effect, evidence-ref, risk-rating} — never an assertion without an attached artifact. |
| `rfc-2119-requirement-extraction` | extract requirements · pull the shall statements · MUST/SHOULD list | `read_file` | Parses a contract/spec/regulation into a normalized MUST/SHOULD/MAY obligation register with source clause refs. |

### C. Analytical / consulting methods — FP&A, strategy, ops, PMO, product

| `name` | `triggers` | `tools_needed` | What it does |
|---|---|---|---|
| `root-cause-5-whys` | root cause · 5 whys · why did this happen | `read_file`, `knowledge_search` | Structured causal drill-down terminating in a systemic cause + corrective action, not a symptom. |
| `executive-one-pager` | exec summary · one-pager · brief the leadership | `read_file` | Compresses any analysis into a BLUF one-pager (ask, context, options, recommendation, risks, next step). |
| `decision-memo-saspe` | decision memo · recommend an option · should we do X | `read_file`, `knowledge_search` | Situation-Assumptions-Solutions-Pros/cons-Evaluation memo with an explicit recommendation and stated assumptions. |
| `swot-and-portering` | SWOT · five forces · competitive position | `knowledge_search`, `web_search` | SWOT + Porter's Five Forces with every cell sourced. |
| `monte-carlo-sensitivity` | sensitivity analysis · monte carlo · what's the range | `pandas_query`, `spreadsheet` | Sandboxed parameter sweep / Monte-Carlo returning the distribution + tornado sensitivity, all outputs labeled estimates. |
| `stakeholder-raci-map` | RACI · who's responsible · stakeholder map | `read_file` | Builds a RACI/stakeholder matrix so accountability is unambiguous before work starts. |
| `okr-drafting` | draft OKRs · set objectives · key results for | `read_file` | Turns a goal into well-formed objectives + measurable, time-bound key results with baseline and target. |
| `competitor-teardown` | competitor teardown · tear down their product · competitive analysis | `web_search`, `knowledge_search` | Repeatable competitor/product teardown (positioning, pricing, feature gaps, claims), every claim sourced and dated. |

> The council deliberately kept this list cross-cutting. Suite-local procedures
> ("3-way-match", "ASC 606 5-step") belong in the per-suite skills below, not the
> universal library.

---

## Part 2 — Net-new specialist agents by suite (66)

Each row: proposed pack `name` (`<family>_<slug>`), one-line JD, `compartment`,
`max_risk`, the load-bearing control it respects, and why it is net-new. All
`authoring="manual"`.

### Finance / Tax / Treasury / Banking / Insurance-finance (12)

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `finance_bus_combination` | PPA, opening balance sheet, goodwill/NCI under ASC 805/IFRS 3 for an M&A close. | `finance_controllership` · med | PPA JE posting `require_human`; relies on the valuation specialist. No business-combination/PPA seat exists (`goodwill`=0). |
| `finance_impairment` | Recurring goodwill (ASC 350), long-lived-asset (ASC 360), indefinite-intangible impairment cycle. | `finance_controllership` · med | Produces a finding + draft memo, never the write-down JE. Top restatement risk with no owner. |
| `finance_going_concern` | Quarterly going-concern / runway assessment (ASC 205-40), substantial-doubt eval, disclosure draft. | `finance_controllership` · med | Read-only; the conclusion is human-certified. `going concern`=0 — highest-stakes recurring judgment, unowned. |
| `finance_unclaimed_property` | Corporate escheatment — dormancy, due-diligence letters, multistate (incl. B2B credit balances), DE VDA. | `finance_controllership` · low | Remittance/filing `require_human`. Escheat existed only bank-side; corporate AP/AR/payroll exposure unowned. |
| `finance_global_info_reporting` | 1042/1042-S, FATCA/CRS classification, FBAR/FinCEN-114, 1099/W-8/W-9 at scale. | `finance_tax` · med | Filing & remittance always `require_human`. `FATCA`/`FBAR`=0; the obligation-tracker doesn't prepare the returns. |
| `bank_alm_irrbb` | Interest-rate-risk / ALM — repricing gap, EVE & NII sensitivity, deposit-beta/decay, IRRBB reporting. | `bank_treasury_ops` · low | Read-only; moves no funds. `ALM`/`IRRBB`=0 — the #1 supervised-bank risk discipline post-2023. |
| `bank_liquidity_reg` | Regulatory liquidity — LCR/NSFR, Reg YY internal-liquidity-stress, contingency-funding-plan support. | `bank_treasury_ops` · low | Read-only; never files. `LCR`/`NSFR`=0; existing reg-reporting is HMDA/CRA data, not Basel liquidity. |
| `bank_cecl_allowance` | CECL allowance for credit losses (ACL) on a bank loan/lease book — PD/LGD or DCF/WARM, Q-factors, roll-forward. | `bank_controllership` · med | ACL booking / reserve release `require_human`; assumptions go to model-risk. The existing CECL pack is corporate-AR, not a loan book. |
| `ins_stat_reporting` | Insurance statutory (STAT/SAP) reporting — Annual/Quarterly blanks, Schedule P, IMR/AVR, RBC inputs, GAAP→STAT. | `ins_controllership` · med | Filing & Appointed-Actuary opinion are human acts. The entire `ins` suite is claims/UW ops — zero financial-reporting seat. |
| `ins_actuarial_reserving` | Loss & LAE reserve indication — triangle development, BF/chain-ladder, IBNR, premium-deficiency. | `ins_actuarial` · med | Read-only/analytical; booked reserve + opinion are human. No triangle/IBNR seat exists; independence from `ins_stat_reporting` closes the loop. |
| `ins_reins_recoverable` | Reinsurance recoverables & allowance — ceded roll-forward, aging, dispute/credit allowance, Schedule F. | `ins_controllership` · low | Drafts the allowance as a finding, cannot post it. Nothing owns the recoverable asset, its aging, and its allowance. |
| `finance_derivative_collateral` | OTC-derivative collateral/margin ops — ISDA/CSA, daily VM/IM calls, MTA/threshold, dispute breaks. | `finance_treasury` · med | Collateral transfer `require_human` + amount-gated; sealed from trade execution. FX/hedging proposes hedges; post-trade collateral ops are unowned. |

### IT / GRC / Security / AI-Governance (12)

The two genuinely uncovered surfaces: **post-quantum / crypto-agility** (zero
coverage anywhere) and **the agentic-AI control plane as its own governed estate**.
The saturated AI-governance cluster (model-card, bias-eval, AI-inventory,
prompt-red-team, eval-harness, MLOps — all on disk) was deliberately **not**
re-proposed.

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `itgrc_pqc_readiness` | Crypto-asset inventory + NIST FIPS 203/204/205 migration roadmap; Harvest-Now-Decrypt-Later flags. | `itgrc_secops` · low | Read-only; never rotates a key. No PQC pack exists — the single largest 2026 gap. |
| `itgrc_crypto_agility` | Crypto-agility posture — hard-coded algos, pinned chains, hybrid-KEM readiness, the CBOM. | `itgrc_secops` · low | CBOM is evidence, not a change. The architectural readiness that makes PQC migration tractable. |
| `itgrc_nhi_governance` | Non-human-identity sprawl — service accounts, API keys, OAuth grants, agent capabilities; orphan/over-privilege detection. | `itgrc_iam` · low | Revoke/rotate `require_human`; independent of IdP/PAM. NHIs now outnumber humans ~40:1 with no owner. |
| `itgrc_agent_identity` | Agent-to-agent / agent-to-tool auth — workload identity, capability-token scoping, delegation chains. | `itgrc_iam` · low | Cannot widen a grant or mint a token. SPIFFE/token-exchange is a brand-new surface; SSO pack is human-only. |
| `itgrc_mcp_runtime_gov` | Runtime governance of the live MCP/tool ecosystem — tool-poisoning, rug-pull/version-drift, scope creep. | `itgrc_appsec` · med | Quarantine `require_human`. Supply-chain pack vets pre-install; this is post-trust runtime drift. |
| `itgrc_model_provenance` | AI model-artifact supply chain — signing/attestation, weights provenance, fine-tune chain-of-custody, backdoor detection. | `itgrc_aigov` · low | A human signs off deployment; independent of model owners. The SBOM analogue for model weights. |
| `data_corpus_integrity` | RAG/training-corpus integrity — poisoned docs, injected instructions, embedding anomalies, unauthorized mutations. | `data_corpus_integrity` · med | Flags for human curation; never deletes. The Shield catches runtime injection; nothing audits the corpus at rest. |
| `itgrc_ai_act_gpai` | EU AI Act GPAI / systemic-risk provider duties — Art 53/55, GPAI Code of Practice, training-data summary, copyright policy. | `itgrc_aigov` · low | A human attests. Distinct from the shipped deployer/high-risk conformity pack — a separate just-in-force regime. |
| `itgrc_data_residency` | Data-residency / sovereign-cloud posture — physical data-landing map, egress-lock verification, EU/Gov gaps. | `itgrc_privacy` · low | Never relocates data. The legal transfer pack is GDPR-Ch.V; operational residency mapping is unowned. |
| `itgrc_secure_by_design` | CISA Secure-by-Design pledge evidence — default MFA, memory-safety roadmap, CVD, SBOM publication, attestation. | `itgrc_grc` · low | A human signs the attestation (a legal representation). Distinct from code-level SAST/SCA. |
| `itgrc_ai_agent_audit` | Read-only **assurance over the autonomous-agent fleet** — tests hard floors hold, audits agent decision logs, reviews capability attenuation. | `itgrc_aigov` · low | Read-only and **independent of `itgrc_agent_oversight`** (the operator) — third-line over the fleet. Closes the SoD loop on the platform itself. |
| `itgrc_dora_tlpt` | DORA threat-led pen-testing (TLPT/TIBER-EU) coordination + ICT-third-party register/concentration-risk reporting. | `itgrc_secops` · low | Scope authorization & live test `require_human`. The legal pack tracks obligations; the operational teeth are unowned. |

### Revenue / GTM / RevOps / Marketing / CX (11)

The lane's verdict: *the gaps are operational ownership, not topics.* 2026 motions
are name-dropped in personas; nobody owns the measurable workflow.

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `gtm_trust_center` | Drafts inbound security-questionnaire / RFI-security responses (SIG, CAIQ, VSA); keeps the public trust-center library current. | `gtm_sales` · med | No public claim; attestations human-signed. The biggest GTM/CS time-sink, confirmed unowned (vendor-sec pack is inbound-only). |
| `gtm_consent_ledger_ops` | Operational suppression/consent-ledger reconcile across CRM/MAP/channels; certifies a list clean pre-send. | `gtm_revops` · med | **Is** the hard-floor enforcement; never sends; unverifiable provenance halts the campaign. Policy exists; no hands-on operator does. |
| `gtm_answer_engine` | Audits answer-engine / GEO citation share (ChatGPT/Perplexity/AI Overviews); drafts AEO fixes. | `gtm_marketing` · low | No publish; brand review before anything ships. SEO packs optimize classic SERP; nobody measures answer-engine inclusion. |
| `gtm_plg_signals` | Scores PQL/PQA from product-usage telemetry; routes activation/expansion signals to the rep. | `gtm_revops` · low | No outbound send; consent floor on any triggered outreach. The missing product-signal→sales-action middle for usage-based motions. |
| `gtm_pricing_experiment` | Designs pricing & packaging experiments (tier/paywall/usage-meter), models elasticity, drafts rollout + guardrails. | `gtm_revops` · med | Never commits price; live changes route through deal-desk/human. Nobody runs the experiment loop. |
| `gtm_nrr_engineering` | Builds the NRR/GRR bridge (expansion/contraction/churn waterfall), attributes movement, drafts the retention plan. | `gtm_revops` · low | Read-only on system of record; numbers human-committed before they feed finance. The #1 board metric, undecomposed. |
| `gtm_intent_orchestration` | Fuses third-party intent + first-party signals into prioritized account waves and play recommendations. | `gtm_sdr` · low | No send; lead-source provenance checked. Enrichment enriches a known record; this is the "who's in-market now" layer. |
| `gtm_ecosystem_ops` | Partner-sourced/influenced pipeline ops & PRM hygiene — attribution, co-sell health, ecosystem QBR data. | `gtm_partners` · low | No commitment; deal-reg conflicts/discounts route to humans. Partner suite lacks an ecosystem-RevOps owner. |
| `gtm_zero_party_data` | Designs progressive-profiling / zero-party-data capture for cookieless targeting and consented enrichment. | `gtm_marketing` · med | Consent/suppression hard floor + AI disclosure; no covert collection. A creation discipline the cookieless era requires. |
| `gtm_ai_sdr_oversight` | Second-line QA over AI-SDR output — disclosure compliance, personalization quality, hallucinated claims, consent adherence. | `gtm_revops` · med | Gates the AI-SDR's drafts; flags, never sends. A brand-new control seat as AI-SDRs draft at volume. |
| `gtm_localized_sdr` | In-language outbound/inbound SDR adapted to locale (language, etiquette, local consent regime). | `gtm_sdr` · low | Per-jurisdiction consent (CASL/PECR/local) strictest-wins + AI disclosure. SDR seats are English-default. |

### HR / People & Legal (11)

Targeted at **event-driven, high-liability moments** no pack owns, and the 2026
AI-in-hiring / pay-transparency regulatory wave.

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `hr_rif_warn` | RIF planning — WARN/mini-WARN 60-day math, selection-criteria documentation, post-hoc disparate-impact on the human-built list. | `hr_investigations` (sealed) · high | Selection is human + counsel; **refuses protected-class data as a selection input**. No WARN/RIF pack exists — the highest-litigation HR event. |
| `hr_aedt_audit` | Evidence package for NYC LL144 / Colorado SB24-205 / EU-Annex-III **bias audits of automated employment tools** + candidate notices. | `hr_recruiting` · high | Produces evidence **for** an independent auditor — is not the auditor (LL144 independence); aggregate-only. The audit machinery itself is unowned. |
| `hr_pay_transparency_report` | Statutory pay-data reports — EU Pay Transparency Directive gap + joint-assessment trigger, UK GPG, CA SB1162. | `hr_rewards` · med | Filing human-gated; the >5%-gap joint assessment escalates to human + counsel. Internal pay-equity exists; mandatory external filings don't. |
| `hr_accommodation_interactive` | ADA/PWFA reasonable-accommodation interactive-process case file — request log, dialogue tracking, options, undue-hardship docs. | `hr_investigations` (sealed) · high | Medical data sealed from the manager; grant/deny human-led. The PWFA-era highest-volume disability surface, unowned. |
| `hr_skills_inference` | Org-wide skills-graph engine — infer skills from history, map to taxonomy, power internal-mobility/gig matching. | `hr_talent` · med | Surfaces matches; never auto-allocates; refuses emotion/behavioral inference. The skills-based-org engine (vs. one-person IDP). |
| `hr_workforce_monitoring_governance` | Governs RTO/productivity/workforce-analytics telemetry — defines collectable data, enforces aggregation floors. | `hr_operations` · high | **Refusal pack** — refuses Art-5 workplace emotion inference and individual behavioral/biometric monitoring outright. Makes the cardinal refusal an active control. |
| `legal_ai_addendum` | AI-specific contract layer — AI riders/addenda, model-IP & training-data clauses, output-indemnity, AI-DPA terms. | `legal_contracts` · low | Drafts/redlines; signs nothing; cites verified-or-`[UNVERIFIED]`. AI-counsel advises on law; nobody crafts the AI-deal paper. |
| `legal_sep_licensing` | Standard-essential-patent / FRAND support — portfolio analysis, rate benchmarking, essentiality, negotiation positions. | `legal_ip` · low | Commits to no rate; CourtListener-verified cites. A distinct specialty from general IP licensing/prosecution. |
| `legal_esg_litigation` | Greenwashing / ESG-disclosure litigation & risk — claims review vs FTC Green Guides / EU Green Claims, securities-suit risk. | `legal_litigation` (sealed) · low | Attorney owns every position; no public statement cleared by the agent. A fast-rising 2026 dispute category, unowned. |
| `legal_privacy_litigation` | Privacy class-action defense — VPPA/BIPA/pixel-tracking/CIPA analysis, exposure, standing/arbitration review. | `legal_litigation` (sealed) · low | Files/serves nothing; CourtListener-verified cites (sanctions-dense area). The plaintiff-bar wave is a defense specialty with no pack. |
| `legal_ediscovery_modern_data` | E-discovery for chat/ephemeral data — Slack/Teams/SMS preservation, modern-data custodian mapping, spoliation analysis. | `legal_litigation` (sealed) · low | Produces nothing; legal-hold-beats-erasure enforced. Traditional e-discovery covers email/docs; ephemeral preservation is the 2026 fight. |

### Product / Eng / Data-ML / Ops / Supply-chain (13)

Targeted at the **2026 operating disciplines** the build/author roster is thin on:
reliability economics, the data-as-product / lakehouse / feature-store layer,
production LLMOps, and the trade/ESG regulatory wave.

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `pe_sre_incident_commander` | Live incident command — severity, the bridge, MTTR, mitigation/rollback sequencing, comms timeline. | `pe_devops` · high | Production rollback/deploy human-gated; drafts the mitigation PR. Observability tunes alerts; nobody runs the incident. |
| `pe_slo_reliability` | SLI/SLO definition, error-budget policy + burn-rate alerting, release-freeze recommendation. | `pe_devops` · low | The freeze/release decision is human. Owns the error-budget economics nothing touches. |
| `pe_finops_cloud_cost` | Cloud + Kubernetes cost engineering — unit-cost, rightsizing, RI/SP commitments, anomaly, showback/chargeback. | `pe_devops` · low | Infra/commitment change ships via IaC PR + human approval. The existing cost pack is warehouse-spend-only. |
| `pe_data_product_owner` | Data-mesh data-product engineering — contract-backed, discoverable data products (SLAs, ports, semantic layer). | `pe_engineering` · high | Sandbox + verifier; prod promotion human-gated. The contracts pack stewards read-only; this builds the product. |
| `pe_lakehouse_streaming` | Lakehouse + real-time — Iceberg/Delta table management, CDC/streaming (Kafka/Flink), exactly-once + schema evolution. | `pe_engineering` · high | Sandbox + merge-gate; prod topology changes human-gated. The pipeline pack is generic batch ETL. |
| `pe_feature_store` | Feature platform — definitions, online/offline parity, point-in-time correctness, train/serve-skew prevention. | `pe_engineering` · high | Sandbox + merge-gate. Sits between ml-dev and mlops with no owner; skew is the #1 silent ML bug. |
| `pe_llmops_observability` | **Production** LLM/RAG observability — online eval + LLM-judge, guardrail monitoring, hallucination/drift, cost/token, prompt-regression gates. | `pe_engineering` · med | Changes ship through verifier + review; never alters its own runtime/safety. Build-time LLM-app pack exists; runtime is unowned — and dogfood-critical. |
| `data_semantic_layer` | Owns the governed metric/semantic layer — certified metric definitions, headless-BI consistency, change impact. | `data_semantic_layer` · med | Read-only; certification is human. The metric-keeper watches values; this owns the definitions. |
| `data_vector_rag_ops` | Vector-DB + RAG-pipeline ops — index/embedding lifecycle, chunking/retrieval-quality, freshness/reindex, recall@k, drift. | `data_vector_ops` · med | Reindex/write to prod gated. The platform leans on RAG everywhere with no ops owner. |
| `ops_control_tower` | End-to-end supply-chain visibility — multi-tier disruption sensing, exception orchestration, ETA/risk early-warning, what-if. | `ops_planning` · low | **Physical-action gate** — recommends; expedite/reroute/PO human-authorized. Planning packs are silos; the cross-functional layer is unowned. |
| `ops_demand_sensing` | Short-horizon demand sensing — blends POS/orders/external signals to adjust near-term forecast; DDMRP signals. | `ops_planning` · low | Drafts adjustments; replenishment stays tiered/gated. The statistical pack is mid/long-range; short-horizon sensing is separate. |
| `ops_supply_resilience_reshoring` | Resilience strategy — dual/multi-sourcing design, supplier financial-health screen, tariff/reshoring scenarios, concentration risk. | `ops_procurement` · low | Never disqualifies a supplier or changes sourcing; sanctions/forced-labor hits to a human. The supplier-risk pack scores a given supplier; this is forward strategy. |
| `ops_carbon_dpp_compliance` | Product-level carbon + EU passports — CBAM embedded-emissions, CSRD/ESRS product data, EU Digital Product Passport (ESPR). | `ops_ehs` · low | Published/filed figures go through finance ESG + a human files. The sustainability pack is site-level Scope 1/2/3; product-level regulatory dossiers are unowned. |

### Platform / meta — operating Lightwork's own machinery (7) · new `plat_` family

Seats that operate the platform's **own** skills / evolve / knowledge / fleet
machinery — described in `self-extending-agent-factory.md` but with no pack. The
saturated meta-cluster (oversight, ai-inventory, red-team, bias-eval, eval-harness,
mlops — all on disk) is **not** re-proposed.

| `name` | JD | compartment · risk | Control / why net-new |
|---|---|---|---|
| `plat_skill_distiller` | Mines successful trajectories and distills `SKILL.md` candidates via `skills.distill()` + `validate_skill_file`. | `platform_evolve` · low | Candidate staged + Shield-scanned; `publish_skill` `require_human`. The factory's skill-synthesis arm — the answer to the empty library. |
| `plat_skill_curator` | Skills-library health — dedup overlaps, retire decayed skills (`skill_stats.decay_weights`), lint, prevent bloat. | `platform_evolve` · low | Read-only over stats; a human approves removal. Without it the library rots the way the roster nearly did. |
| `plat_skill_marketplace_reviewer` | Vets community/3rd-party `SKILL.md` before promotion — signature/sha256, permission manifest, Shield body scan, publisher trust. | `platform_supply_chain` · med | Install/publish gated; unsigned+unverified flagged for a human. `skill-index.md` defines `verified`/`trusted` flags with no reviewer behind them. |
| `plat_agent_pack_author` | The Agent-Engineer drafting seat — synthesizes new `DomainProfile` packs (`authoring="generated"`) scoped to an Operating Profile, born attenuated + quarantined. | `platform_evolve` · med | `self_edit` denied; no write to `maverick/` runtime; `promote_agent` `require_human`. The self-extending factory's drafting seat, made real with the bright line enforced. |
| `plat_learning_lifecycle_op` | Operates the EVOLVE loop — dreaming/hindsight/proof, snapshot+rollback, the signed learning audit per promotion/retire. | `platform_evolve` · med | Promotion/rollback transitions `require_human`; every learning event signed. Unique to the closed learning lifecycle; distinct from live oversight. |
| `plat_fleet_memory_librarian` | Curates fleet memory + the Operating Record — dedup/age shared memories, enforce compartment boundaries on cross-agent recall, provenance. | `platform_knowledge` · low | Tenancy/compartment-respecting reads; no cross-tenant leakage. The fleet-memory differentiator has no librarian. |
| `plat_capability_sod_linter` | Statically lints the **whole synthesized fleet's** capability grants for SoD conflicts/over-grant before promotion. | `platform_assurance` · low | Read-only; emits findings to a human; cannot alter a grant. The overview's named unbuilt primitive; distinct from `itgrc_sod_it` (human IT access). |

---

## Part 3 — Suite-specific skills (41)

Procedural methods scoped to one suite (vs. the cross-cutting library in Part 1).
Each is a `SKILL.md` reused by the suite's packs above and the existing roster.

**Finance / Banking / Insurance (9):** `ppa-opening-balance-sheet` ·
`goodwill-impairment-test` · `going-concern-assessment` · `escheatment-dormancy-run`
· `loss-reserve-triangle` · `cecl-acl-loan-roll` · `irrbb-eve-nii-shock` ·
`lcr-hqla-classification` · `non-gaap-reg-g-bridge`

**IT / GRC / Security (8):** `pqc-readiness-inventory` · `cbom-generate` ·
`nhi-credential-rotation-runbook` · `prompt-injection-tabletop` ·
`mcp-tool-poisoning-scan` · `dora-ict-incident-classify` · `model-artifact-verify`
· `residency-egress-validate`

**Revenue / GTM (8):** `security-questionnaire-autofill` ·
`answer-engine-optimization-audit` · `nrr-bridge-build` ·
`win-loss-interview-synthesis` · `suppression-list-reconcile` · `pql-scoring-model`
· `pricing-experiment-design` · `cookieless-audience-blueprint`

**HR / Legal (8):** `adverse-impact-four-fifths` · `pay-equity-regression` ·
`pay-gap-statutory-report` · `accommodation-interactive-log` ·
`contract-obligation-extraction` · `citation-shepardize-verify` ·
`frand-rate-benchmark` · `ephemeral-data-preservation-map`

**Product / Eng / Data / Ops (8):** `slo-error-budget-policy` ·
`incident-postmortem-5whys` · `data-contract-author` · `llm-eval-harness-build` ·
`feature-pit-correctness-check` · `cbam-embedded-emissions-calc` ·
`supplier-financial-health-screen` · `dual-sourcing-tariff-scenario`

> Full frontmatter (`triggers`, `tools_needed`, body) for each is recorded in the
> seat findings and authored at build time.

---

## Part 4 — New industry verticals (6)

Whole domains a 2026 enterprise buyer expects that are absent from the 26 suites.
Each is a new family + ~3–5 flagship seats reusing the shipped engines (governance
gate, compartments, signed audit, assessment, channels) — new packs, not new
platform.

| Vertical (`prefix`) | Why expected | Flagship seats | Reuses |
|---|---|---|---|
| **Energy & Utilities** (`util_`) | Huge regulated sector absent; distinct from manufacturing. | `util_outage_coord` · `util_reg_filing_prep` (FERC/PUC) · `util_meter_billing` · `util_renewable_rec` · `util_grid_compliance` (NERC CIP) | Ops physical-action gate + safety-refusal (never controls grid equipment); GRC assessment. |
| **Real Estate & Property Mgmt** (`re_`) | Top-10 vertical; finance has ASC-842 but not property *operations*. | `re_lease_abstraction` · `re_property_ops` · `re_rent_roll` · `re_appraisal_support` · `re_capital_projects` | Legal CLM, finance lease pack, ops facilities, `extract-from-document`. |
| **Pharma / Life-Sciences R&D** (`pharma_`) | Distinct from healthcare-*provider*; GxP/FDA buyer. | `pharma_clinical_doc` · `pharma_regulatory_submission` (filing human) · `pharma_pharmacovigilance` · `pharma_gxp_qa` · `pharma_lab_notebook` | GRC + evidence, clinical-PII privacy. **Hard floor: never files with FDA, never adjudicates safety.** |
| **Telecom / Media-Entertainment** (`tmt_`) | Two adjacent sizable sectors; rights/royalties + network ops. | `tmt_rights_clearance` · `tmt_royalty_calc` (payout human) · `tmt_content_metadata` · `tmt_network_noc` (read-only) · `tmt_subscriber_billing` | Legal IP, finance AR/revenue, ops. |
| **Hospitality / Travel** (`hosp_`) | Operations-heavy service vertical, no coverage. | `hosp_reservations` · `hosp_revenue_mgmt` (price commit human) · `hosp_guest_relations` · `hosp_property_compliance` · `hosp_group_events` | CX + channels, consent/AI-disclosure floor, `monte-carlo-sensitivity`. |
| **Capital Markets / Asset Mgmt** (`cap_`) | The biggest honest gap: finance covers corporate buy-side treasury; sell-side / asset-management is absent. | `cap_research_analyst` · `cap_portfolio_analytics` (execution refused) · `cap_compliance_surveillance` (MNPI watch) · `cap_client_reporting` · `cap_regulatory_filing_prep` (ADV/PF) | Treasury + IBKR, MNPI **information barriers via `quarantine` seals**, AML, model-risk. **Hard floor: trade-propose-not-execute.** |

---

## Part 5 — Anti-recommendations / honesty check (consolidated)

Every seat was required to name where the roster is already saturated. With 1,022
packs shipped, the default failure mode is additive over-proposing. **Do not add
here:**

1. **Generic `X-analytics / X-reporting / X-audit / X-inventory` packs.** The
   audit/inventory/reporting pattern already exists in *every* family. Grep the
   target family before proposing — the CLAUDE.md "grep before assuming a name"
   rule applies. This is the #1 dedup risk and it is structural.
2. **The AI/ML governance cluster.** model-card, bias-eval, ai-inventory,
   prompt-red-team, eval-harness, MLOps **all ship** (verified on disk). The only
   net-new meta-seats operate Lightwork's *own* evolve/skills/fleet machinery
   (Part 2 `plat_*`), not customer ML governance.
3. **Per-statute / per-jurisdiction clone packs.** 17 HR employment packs, ~15
   legal privacy-law packs, country-VAT/GST packs already exist. These are
   `knowledge_sources` + assessment-template variations on a strictest-wins dial,
   not new seats. Add knowledge packs, not packs.
4. **Indirect tax / e-invoicing, AML/BSA + sanctions, close-orchestration/variance,
   internal-audit/SOX.** All at capacity in finance/banking. A new close
   accelerator or transaction-monitoring seat duplicates shipped packs — and a
   "controls remediation" assurance seat would **violate the read-only
   independence floor**.
5. **SEO/content, support tier-1/KB, pipeline/forecast/quota/commission, and
   brand/claims** in GTM. The `cx` support suite (41 packs) is at saturation; more
   micro-agents fragment routing without adding capability.
6. **Per-domain "continuous monitoring / streaming / anomaly" packs and per-vertical
   carrier/quality micro-packs.** The monitoring pattern (`data_anomaly`,
   `pipeline_monitor`, `quality_sentinel`, SIEM/SOC triage…) and the manufacturing
   QMS / logistics-freight families are already richly sliced. New entrants here are
   a **connector + an existing seat's trigger**, or a *skill* — not pack #N.

**The meta-point:** new capability should default to **a skill or a connector**. A
new *pack* must clear the "grep the family first, and is this really net-new?" bar
that most instinctive proposals fail.

---

## Part 6 — Recommended first builds (prioritized)

Synthesizing the council's own priority calls:

1. **The 20 cross-cutting skills (Part 1) + the three skills-lifecycle platform
   seats** (`plat_skill_distiller`, `plat_skill_curator`,
   `plat_skill_marketplace_reviewer`). Highest leverage, lowest risk, purely
   additive — fills a library that is empty today and makes 1,022 existing packs
   measurably better. The platform seats keep it self-sustaining instead of a
   one-time dump.
2. **The zero-coverage white spaces.** Insurance financial reporting
   (`ins_stat_reporting` + `ins_actuarial_reserving` + `ins_reins_recoverable` —
   the single largest functional white space), post-quantum
   (`itgrc_pqc_readiness`), and the agentic-AI control plane (`itgrc_nhi_governance`,
   `itgrc_agent_identity`, `itgrc_mcp_runtime_gov`, `itgrc_model_provenance`,
   `data_corpus_integrity`, `itgrc_ai_agent_audit`).
3. **The highest-liability / deadline-driven event seats.** `hr_aedt_audit` and
   `hr_rif_warn` (top HR litigation), `hr_pay_transparency_report` (EU directive
   transposition deadline mid-2026), `finance_going_concern`, `gtm_trust_center`
   and `gtm_consent_ledger_ops` (the cardinal outbound control made operational).
4. **The dogfood + reliability seats.** `pe_llmops_observability` and
   `pe_sre_incident_commander` (Lightwork is itself an AI product running a fleet),
   then `ops_control_tower`.
5. **New verticals — start with `cap_` (capital markets/asset-management)**, the
   biggest honest functional gap, riding the proven MNPI information-barrier seals.

Build order aside, the council's consensus is unambiguous: **author the skills
first.** It is the one move that is additive, reversible, low-risk, and improves
the entire existing fleet at once.

---

## Appendix — control invariants every proposal preserves

- **Agents draft; humans approve, post, pay, file, certify.** No proposed seat
  moves money, files with a regulator, or certifies its own work.
- **Independence is structural.** Assurance/audit/validation seats
  (`itgrc_ai_agent_audit`, `plat_capability_sod_linter`, `finance_*` audit,
  `ins_actuarial_reserving` vs `ins_stat_reporting`) are read-only over what they
  review and cannot remediate it.
- **Hard floors are un-lowerable** `require_human`: money movement, bank-detail
  changes, period close/posting, tax/regulatory filing, SAR/regulator/subject
  notification, privileged-access grants, safety-critical actuation,
  trade execution, model/skill/pack promotion.
- **Confidentiality via compartment seals** — sealed matters (legal litigation),
  MNPI/deal rooms (`cap_`), medical/ER (`hr_investigations`), pre-decisional RIF
  lists.
- **Refusal, not gate, where the law prohibits** — `hr_workforce_monitoring_governance`
  (Art-5 emotion inference), Ops safety-critical actuation, `cap_`/treasury trade
  execution.
- **Never hard-code models** (`get_role_model`); **budget caps mandatory**; the
  self-extending factory does **genetic** extension (synthesize → human promotion
  gate), never self-modification (`self_edit` stays off).
