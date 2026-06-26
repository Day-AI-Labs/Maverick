# Lightwork — Novel Feature Research: Fleet Memory/Interop & Provable Learning

> Deep-research report. Date: 2026-06-21. Repo: `Day-AI-Labs/Maverick`.
> Method: 6 parallel agents — 1 codebase audit + 5 external angles (enterprise
> competitor teardown, agent-interop standards, agent-memory research frontier,
> verifiable-learning frontier, AI-governance regulatory drivers) — followed by a
> cross-corroboration / adversarial verification pass and re-grounding against
> Lightwork source and the three pending invention disclosures (`docs/patents/`).
> Deliverable scope (as requested): research + ranked ideas, two tiers
> (near-term shippable + moonshot). No code. Focus weighted to **fleet
> memory/interop** and **provable/verifiable learning**, with a wide scan for
> higher-leverage adjacencies.

---

## Bottom line (four verdicts)

1. **The white space Lightwork already aims at is real, and the standards bodies
   have *actively walled it off*.** The two dominant interop standards refuse to
   touch durable memory: A2A makes shared memory an *explicit non-goal* (its
   "opacity" principle is "collaborate without sharing internal memory"), and
   MCP's 2026 roadmap moves it *more* stateless, not less. No IETF/W3C/Linux
   Foundation/AGNTCY track owns portable, governed, cross-vendor memory or an
   "operating record." That layer is unclaimed — and Lightwork is already sitting
   on it.

2. **Every enterprise incumbent conflates "governance" with action-audit +
   guardrails + identity. None proves *learning*.** Across Agentforce, Copilot,
   Gemini Enterprise, ServiceNow, Bedrock AgentCore, Glean, Writer, and Cohere,
   "governance" means *who did what* (audit), *stop the bad thing* (guardrails),
   and *who is this agent* (identity). **Not one ships a verifiable, signed record
   that an agent genuinely got better.** That is precisely Lightwork's stated
   moat — and it is undefended by the field.

3. **The decisive technical insight: integrity is provable *today*; "it actually
   got better" is *not*.** Artifact signing + transparency logs (Sigstore,
   in-toto, SLSA) and TEE attestation (NVIDIA H100 Confidential Computing, Intel
   TDX) are GA and composable. But NVIDIA states attestation proves device
   integrity, *not* "whether a model successfully learned or improved"; Sigstore
   signs the file, *not* the training/eval; Proof-of-Learning is spoofable (its
   authors: robustness "reduces to open problems in learning theory"); and zkML
   proves *correct execution of a stated computation*, not that the computation
   was the *right* one. **The semantic "it improved, and the gain is real
   (not contaminated/overfit/cherry-picked)" claim is solved by no single
   system** — and regulation is creating direct demand for it.

4. **Regulation has converged on the *same five primitives* Lightwork largely
   already has** — tamper-evident audit, provenance/lineage, attested
   evaluations, versioned point-in-time reconstruction, governed change — across
   EU AI Act, NIST AI RMF, ISO 42001, revised bank model-risk guidance (SR 26-2),
   and FDA PCCP. The defensible gaps the regulation implies but commodity LLMOps
   leaves open are: **memory governance / verifiable right-to-be-forgotten,
   human-oversight evidence, cross-agent interaction provenance, and provable-
   improvement attestation.** These are buying triggers, not nice-to-haves.

**Net:** Lightwork is not looking for a moat — it is *standing on one that the
market has not yet named*. The highest-leverage work is to (a) convert the
already-built primitives into *externally verifiable proofs* that map 1:1 to
compliance triggers, and (b) own the *portable governed memory + operating
record* layer that A2A/MCP refuse to fill — without violating the
no-cross-customer-hivemind principle.

---

## Part 1 — What the market actually ships (and lacks)

### 1.1 Enterprise competitors

| Vendor | Memory | Governance posture | Cross-agent shared memory | Proves *learning*? |
|---|---|---|---|---|
| **Salesforce Agentforce** | Dual-layer; long-term anchored to a per-*user* profile graph; confidence-gated. Deep version reads as **R&D, not GA** (shipped primitive = "Variables"). | Write/read gates on memory; session tracing | No — anchored to user profile | No |
| **Microsoft Copilot Studio** | "Copilot Memory" GA for M365 — **but not available for agents**; agent memory scattered/preview | Strongest action-audit (Purview, Entra Agent ID, on-by-default) | No | No (audits actions, not improvement) |
| **Google Gemini Enterprise** | Memory Bank + Profiles **GA** (per-user/agent) | Strongest agent-*identity* (cryptographic Agent ID, Agent Gateway/Registry, Model Armor) | No documented cross-vendor/fleet sharing | No (ID ≠ proof of learning) |
| **ServiceNow AI Agents** | **No memory product** | Governance-first: AI Control Tower (NIST/EU-aligned), Traceloop observability, Veza identity/kill-switch | No | No |
| **AWS Bedrock AgentCore** | GA-ish; short-term immutable events + async long-term; **hierarchical namespaces** = closest to a shared primitive | Policy + eval suites at action time; KMS; IAM least-privilege | Only as namespace *convention* within one AWS tenant | No |
| **Glean** | Thinly documented working+persistent memory | Strong permissions-aware (ACL inheritance, oversharing remediation) | No | No |
| **Writer** | **[UNVERIFIED]** — no primary source retrieved | **[UNVERIFIED]** | — | No |
| **Cohere North** | **No documented memory architecture** | Sovereign/air-gapped; SOC2/ISO 27001/GDPR | No (private by design) | No |

> Verification caveats: Writer and Cohere memory/interop claims are **[UNVERIFIED]**
> (no authoritative product/trust page retrieved — a dedicated follow-up fetch is
> warranted before any external competitive claim). Salesforce's deep agentic
> memory GA status is **[partially UNVERIFIED]**. Much incumbent memory tech is
> preview/R&D, not GA; marketing runs ahead of shipped.

**Cross-vendor white space (corroborated by ≥2 agents):**
- **Managed shared memory across a *fleet of heterogeneous* agents does not exist.** Every incumbent anchors memory to a user/actor inside its own platform. ([Salesforce Engineering](https://engineering.salesforce.com/how-agentic-memory-enables-durable-reliable-ai-agents-across-millions-of-enterprise-users/); [AWS AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/))
- **Zero memory portability between vendors** — the "interoperability wall"; only startups (Mem0, MemoryLake) attempt it. ([Conectia](https://conectia.pro/en/blog/ai-agents-mcp-interoperability-wall-2026))
- **Governance ≠ provable learning** — the single biggest gap; named the "verifiability constraint" in the literature. ([ASG-SI, arXiv:2512.23760](https://arxiv.org/abs/2512.23760))

### 1.2 Interop standards (consume these — don't reinvent)

| Layer | Standard(s) | Maturity | Memory? | Reputation / operating record? |
|---|---|---|---|---|
| Tool access | MCP (spec 2025-11-25; RC 2026-07-28 *more stateless*) | High | **No (deliberately)** | No (audit only "on horizon") |
| Inter-agent comms | A2A v1.0.1 (Linux Foundation, 150+ orgs) | High | **No — explicit non-goal** | No |
| Discovery + identity | AGNTCY (OASF/Directory/Identity), W3C DID/VC | Medium | No (out of scope) | Identity only |
| Workload/agent identity | IETF WIMSE-arch-07, AIMS, SPIFFE | Drafting fast | No | Audit *context*, not record |
| Memory portability | Mem0, MemoryLake "memory passport", arXiv proposals | **No standard** | Vendor-siloed | No |

- **A2A** ([GitHub](https://github.com/a2aproject/A2A)): "agents collaborate without needing to share internal memory." Strongest single confirmation that memory is white space.
- **MCP** ([2026 roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)): priorities are transport/scalability, Tasks, governance, enterprise readiness; **identity, memory, statefulness, multi-agent coordination, trust frameworks are not prioritized.**
- **Identity is converging fast and stops at "who/what," never "how it behaved."** WIMSE/SPIFFE/AIMS/DID give an attestable identifier and propagate audit *context* — but nobody standardizes the durable, portable behavioral *record*. ([IETF WIMSE](https://datatracker.ietf.org/doc/draft-ietf-wimse-arch/); [DIF](https://blog.identity.foundation/building-the-agentic-economy/))
- **AGNTCY is the closest competitive venue** (directory + identity + capability badges) and the likeliest place anyone would try to standardize a reputation/operating-record layer — watch it.

> **Competitor motion to take seriously:** an arXiv preprint, **"Portable Agent
> Memory" (2605.11032)**, independently proposes a working protocol —
> Merkle-DAG + BLAKE3 content addressing, **Ed25519** root signing,
> object-capability tokens, selective disclosure for cross-org export, and an
> injection-resistant rehydration pipeline. This is *strikingly close to
> Lightwork's existing signed-capsule design*. It is validation **and** a
> move-now signal. (Pilot-scale, no peer review yet — **[2026 preprint]**.)

### 1.3 Research frontier — where to compete vs. where it's commoditizing

- **Do not compete on recall quality/latency.** Zep/Graphiti (temporal KG) and Mem0 already lead LOCOMO/LongMemEval/DMR; that layer is commoditizing. ([Zep, arXiv:2501.13956](https://arxiv.org/abs/2501.13956); [Mem0, arXiv:2504.19413](https://arxiv.org/html/2504.19413v1))
- **Do compete on what the literature itself flags as unsolved and valuable:**
  1. **Multi-agent memory consistency / conflict resolution** — *no standard*; a 2026 position paper imports cache-coherence theory but it's purely conceptual. ([arXiv:2603.10062](https://arxiv.org/html/2603.10062v1))
  2. **Verifiable forgetting across substrates** — named highest-value, **no peer-reviewed solution**; "information backflow" defeats naive deletion; **post-deletion verification is a universal blind spot.** ([Mnemonic Sovereignty, arXiv:2604.16548](https://arxiv.org/html/2604.16548v1); [Agentic Unlearning, arXiv:2602.17692](https://arxiv.org/pdf/2602.17692))
  3. **Provenance-based *trust-weighting* to resolve contradictions** — nascent; no demonstrated trust calculus. ([Collaborative Memory, arXiv:2505.18279](https://arxiv.org/html/2505.18279v1))
- A research vocabulary is forming around exactly Lightwork's position — **"mnemonic sovereignty," SSGM, Collaborative Memory, Portable Agent Memory** — none shipped complete/scaled. Naming ammunition.

**Verifiable learning, precisely scoped:**

| Capability | State of the art | Provable today? |
|---|---|---|
| Artifact integrity / signing / transparency log | **GA** — Sigstore, in-toto, SLSA | **Yes** |
| Attested execution environment (it ran in a genuine enclave) | **GA** — H100 CC, Intel TDX | **Yes (device-level)** |
| Correct execution of a *stated* computation (ZK) | Prototype — EZKL/zkLLM (inference); zkPoT (small DNN training) | Partial; doesn't scale to frontier |
| Trajectory authenticity (Proof-of-Learning) | Prototype, **spoofable** | No |
| Eval gain is *real* (not contaminated/overfit) | Prototype — contamination-resistant benchmarks (LiveBench, GSM1k) | **No standard for attested eval runs** |
| Agent *improved without regression*, tamper-evidently | Prototype — certified CL (narrow properties) | No |

The composable pieces for *integrity/provenance* are deployable. The **intersection** — attested, contamination-resistant eval over an attested execution, transparency-logged with non-regression evidence — **is solved by no existing system.** ([zkML survey, arXiv:2502.18535](https://arxiv.org/abs/2502.18535); [NVIDIA CC](https://developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/); [Sigstore model-transparency](https://github.com/sigstore/model-transparency); [contamination, arXiv:2507.19219](https://arxiv.org/pdf/2507.19219))

### 1.4 Regulatory buying triggers (the demand engine)

| Regime | Status | Key obligation | Maps to feature |
|---|---|---|---|
| **EU AI Act** (Reg. 2024/1689) | Hard law; high-risk **Annex III → 2 Dec 2027**, Annex I → 2 Aug 2028 (postponed by Omnibus, binds on OJ publication) | Art. 12/18 lifetime tamper-evident logs incl. *substantial modifications*; Art. 14 human oversight (override/stop); Art. 72 post-market monitoring incl. *interaction with other AI systems*; Arts. 17/43+Annex IV conformity evidence | Tamper-evident change ledger; **human-oversight records**; continuous monitoring; **attested evals**; data lineage |
| **NIST AI RMF + GenAI Profile** | Voluntary; de facto US baseline | Measure (attested evals + red-team); provenance (151× in GenAI Profile); **improvement-action ledger**; continuous monitoring | Attested eval harness; provenance; **provable improvement** |
| **ISO/IEC 42001** | Certifiable; becoming table-stakes | Lifecycle traceability incl. *retirement*; data provenance; continual improvement; documented evidence | Lifecycle provenance; **emit evidence automatically** |
| **SR 26-2 / OCC 2026-13** (replaced SR 11-7, Apr 2026) | Mandatory (banks); GenAI/agentic out of scope but applied *by analogy* | "One system of record, not reconstructed after the fact"; reproducibility; versioned effective challenge; continuous monitoring | Immutable audit; **point-in-time reconstruction**; versioned validation |
| **FDA PCCP** (final Dec 2024) | Mandatory (devices) | Change allowed *only when executed exactly as the authorized plan* | **Provable improvement** + change-conformance attestation |

The recurring principle across all of them: **"evidence must be produced as a
byproduct of operation, not reconstructed after the fact."** That is a product
spec for a governed agent platform — and a positioning wedge.

---

## Part 2 — Where Lightwork already stands (so we don't re-invent)

**Already shipped (verified in source):** governed fleet memory (`fleet_memory.py`
— symmetric write-side scope gating, hard retrieval isolation, provenance tags,
tenant isolation, audited reads/writes); deterministic LLM-free **dreaming**;
**hindsight** snapshot-replay coverage-regression detection (no agent re-run);
atomic **snapshot/rollback**; **Ed25519 hash-chained signed audit** with anchor
ledger and a **Rust cross-language verifier** (`rust/maverick-verify-audit`);
**staged learning rollouts** (`learning_rollout.py`); **Memory Guard** (trust
tiers, injection tripwire); **Operating Record** + signed portable **capsule
export**; GDPR erasure; tool-level RBAC; budget caps; egress lock.

**Already claimed as IP (pending provisionals — `docs/patents/`):**
1. Tamper-evident, **cross-language-verifiable** audit of **staged learning
   rollouts** (cohort fraction per stage).
2. **Calibration-gated** self-modifying agent + **snapshot-replay** regression
   detection.
3. **Governed shared-memory plane** for heterogeneous third-party agents
   (write-side-first scope gating, hard retrieval isolation, cross-vendor
   provenance into one consolidation loop).

**Confirmed gaps / seams (the ground for *new* novelty):**
- Federation is **audit-only** — no live bidirectional cross-fleet learning/memory plane.
- Hindsight proves **coverage**, not **causal effect** — "did the lesson actually help?" is unproven by default (a `promotion_effect.py` ATE exists but is opt-in).
- The proof bundle (`proof_pack.py`) is honest that **learning-curve/benchmark proofs are `NOT_RUN`** — there is no externally verifiable "we got better" artifact.
- Learned skills are **not auto-signed** (Sigstore integration exists, unwired).
- No **verifiable-forgetting certificate** (erasure happens; *proof* of erasure does not).
- Operating Record **merge/split (M&A)** deferred; capsule exists but is **not an open, portable cross-vendor format/standard**.
- No trust **calculus** for resolving *contradictory* memories (scope gating exists; adjudication does not).

> **The strategic seam:** Lightwork's three pending patents prove *integrity and
> provenance of learning* (the chain is honest, the memory is governed). They do
> **not** yet prove *the learning was genuinely good* (semantic improvement,
> contamination-resistant), nor *that forgetting truly happened*, nor *how
> contradictions are adjudicated*. Those are the new, distinct, patentable
> inventions below — each clears both the incumbents and Lightwork's own filed IP.

---

## Part 3 — Ranked novel feature ideas

**Scoring** (1–5; higher is better except Effort where higher = more work):

| # | Idea | Moat | Defensibility / IP novelty | Compliance pull | Builds on existing | Effort | Tier |
|---|---|---|---|---|---|---|---|
| **1** | **Proof-of-Improvement (PoI) Certificate** | Provable learning | 5 (new filing; beyond patents #1/#2) | 5 | 5 | 3 | Near-term |
| **2** | **Verifiable Forgetting Certificate** | Memory governance | 5 (new filing; no peer-reviewed art) | 5 | 4 | 3 | Near-term |
| **3** | **Mnemonic Adjudication (trust-weighted conflict resolution)** | Fleet memory | 4 (extends patent #3) | 3 | 4 | 2 | Near-term |
| **4** | **Human-Oversight & Decision Evidence Ledger** | Governance | 3 (feature > IP) | 5 | 5 | 1 | Near-term |
| **5** | **Agent Operating Record — open, customer-owned, cross-vendor format** | Fleet memory/interop | 5 (category-defining; move-now) | 4 | 4 | 4 | Moonshot |
| **6** | **Attested Federated Learning Exchange** (PoI-carrying, no-hivemind) | Both | 5 (combinatorial moat + network effect) | 4 | 3 | 5 | Moonshot |
| **7** | **TEE-Attested Learning** (hardware-rooted PoI) | Provable learning | 4 (new filing; highest assurance) | 5 | 3 | 5 | Moonshot |

---

### TIER 1 — Near-term, shippable on the current architecture

#### Idea 1 — Proof-of-Improvement (PoI) Certificate  ★ flagship

**Thesis.** Every incumbent's "governance" stops at action-audit; the literature
and NVIDIA/Sigstore explicitly *cannot* prove improvement. Turn Lightwork's
honest `NOT_RUN` learning-curve section into a **signed, externally verifiable
certificate that a workforce genuinely improved — and the gain is not
contaminated, overfit, or cherry-picked.**

**What it is.** A new artifact that binds five things into one Ed25519-signed,
cross-language-verifiable record (reusing the existing Rust verifier):
1. **Committed, held-out, contamination-resistant eval set** — content-addressed
   hash committed *before* the learning cycle (LiveBench/GSM1k-style design so
   memorization can't inflate the score).
2. **Attested execution** of the eval (initially software attestation; Idea 7
   upgrades to TEE).
3. **Before/after scores** on the *same committed set*, plus the existing
   **hindsight non-regression** gate (no covered skill regressed).
4. The existing **calibration-gate / causal ATE** (`promotion_effect.py`) result,
   so "improved" means *measured effect with a confidence interval*, not a vibe.
5. A **transparency-log entry** (Sigstore/Rekor-style) so a third party can
   confirm the certificate existed at time T and was never altered.

**Why novel (clears incumbents *and* Lightwork's own IP).** Patent #1 signs
*that* staged learning rolled out; #2 gates promotion and detects coverage
regression. **Neither proves the improvement is *real and uncontaminated* to an
external auditor.** The inventive core here is the **binding of a pre-committed
contamination-resistant eval + attested run + non-regression + causal effect into
one externally verifiable certificate** — an "evals-as-proof" primitive that no
vendor and no paper ships end-to-end.

**Builds on.** `proof_pack.py`, `hindsight.py`, `promotion_effect.py`,
`learning_rollout.py`, `audit/signing.py`, `rust/maverick-verify-audit`.

**Compliance trigger.** NIST improvement-action ledger; ISO 42001 continual
improvement; EU Art. 72 post-market monitoring; **FDA PCCP** ("executed exactly
as authorized"); SR 26-2 versioned effective challenge. This is the rare feature
that is *simultaneously* a marquee differentiator and a direct regulatory answer.

**Effort/risk.** Medium / low — most pieces exist; the new work is the eval-commit
scheme, contamination-resistant set design, and the certificate format. Risk:
designing evals that are genuinely contamination-resistant per domain.

**IP.** New provisional (#4). Distinct from #1/#2; strongest §101 footing
(cryptographic verification = concrete technical improvement).

---

#### Idea 2 — Verifiable Forgetting Certificate (Right-to-be-Erased attestation)

**Thesis.** GDPR erasure + EU AI Act data governance + ISO 42001 provenance all
demand that what an agent *learned/remembered* be deletable — and the research
names **post-deletion verification a universal blind spot with no peer-reviewed
solution.** Lightwork already *does* erasure; nobody can *prove* it.

**What it is.** On an erasure request, scope-delete across **all** memory
substrates (world model, reflexions, dream insights, learned skills, vector
store) and emit a **signed certificate** that proves the deletion: (a) the set of
records removed (by commitment, not content), (b) a **post-deletion recall
attestation** — re-run the deterministic recall machinery and attest *zero
coverage* of the erased subject, defeating "information backflow," and (c) a chain
entry tying the erasure to the request. Verifiable offline by the Rust verifier.

**Why novel.** The literature ([Mnemonic Sovereignty](https://arxiv.org/html/2604.16548v1),
[Agentic Unlearning](https://arxiv.org/pdf/2602.17692)) states outright that
verifiable forgetting across substrates and post-deletion verification are
unsolved. Lightwork's deterministic, LLM-free recall is the *enabling trick*:
because recall is reproducible, a "the lesson is provably gone" attestation is
actually computable — something gradient-based memories cannot offer.

**Builds on.** `memory_guard.py`, `fleet_memory.py`, `semantic_recall.py`,
existing GDPR erasure, `audit/signing.py`.

**Compliance trigger.** GDPR Art. 17 (RTBF); EU AI Act data governance; ISO 42001
data lifecycle; sector privacy rules. Direct, named buyer ask.

**Effort/risk.** Medium / medium — substrate coverage (esp. vector store) and the
backflow argument need care. Risk: proving *completeness* across substrates.

**IP.** New provisional (#5). No close art; high novelty.

---

#### Idea 3 — Mnemonic Adjudication (provenance-based trust-weighted conflict resolution)

**Thesis.** Multi-agent shared memory's #1 unsolved problem is *conflicting
memories*; today everyone uses ad-hoc locks/versioning. Lightwork already has
trust tiers and temporal facts — extend them into an auditable **adjudication
calculus.**

**What it is.** When two memory entries contradict, resolve deterministically by a
recorded function of **provenance trust tier × source reliability × temporal
validity (`valid_from`/`valid_to`) × evidence count**, persist the *losing* entry
as superseded (not deleted), and emit an audit row explaining the verdict — so
contradictions are resolved *and the resolution is provable*.

**Why novel (vs. Lightwork patent #3).** #3 covers scope gating + provenance
tagging to *prevent poisoning*. It does **not** adjudicate *contradictions* among
already-admitted memories. The inventive core is the **recorded, auditable
trust-calculus for resolving conflicting entries** — which the memory literature
flags as having no demonstrated solution.

**Builds on.** `memory_guard.py` (trust tiers), `world_model.py` (temporal facts),
`agent_trust.py`, dreaming consolidation.

**Compliance trigger.** EU Art. 72 (cross-agent interaction integrity); model-risk
reproducibility. Moderate.

**Effort/risk.** Low / low — additive to existing structures.

**IP.** Continuation/dependent of #3, or a narrow new filing.

---

#### Idea 4 — Human-Oversight & Decision Evidence Ledger  ★ fastest compliance win

**Thesis.** EU AI Act **Art. 14 mandates** override/stop capability but **does not
mandate logging it** — yet Art. 12 + post-market monitoring make oversight-event
logging necessary, and **no vendor tool captures it as first-class evidence.** A
genuine, named gap with near-zero competitor coverage.

**What it is.** Promote every human-in-the-loop action — approve / override /
reject / interrupt ("stop button") — to a **first-class signed audit event** with
*who, when, what action, what rationale, what the agent proposed*, queryable in
the Operating Record and exportable as an Art. 14/Art. 12 conformity packet.

**Why valuable.** Smallest effort, largest *immediate* compliance pull; turns an
existing approval flow into audit-grade regulatory evidence. More feature than
patent, but a fast sales unlock and a natural companion to Idea 1.

**Builds on.** `governance.py` (`REQUIRE_HUMAN`), approval gates, `audit/events.py`
(`APPROVAL_DECISION`, `CONSENT_*`), Operating Record.

**Compliance trigger.** EU AI Act Art. 14 + Art. 12; ISO 42001 accountability;
SR 26-2 effective challenge. Direct.

**Effort/risk.** Very low / very low.

---

### TIER 2 — Moonshot / category-defining

#### Idea 5 — The Agent Operating Record: an open, customer-owned, cross-vendor format

**Thesis.** A2A and MCP *refuse* to own durable memory + behavioral record; no
standards body has chartered it; competitor motion (Mem0, MemoryLake "memory
passport," arXiv Portable Agent Memory) is circling. **Own the layer by publishing
the format** — anchored to the identity standards everyone else is consuming.

**What it is.** Evolve the existing signed capsule into a **published, portable,
governed Operating Record format**: the customer's agents *and the third-party
agents they run* read/write a behavioral + memory record that is provenance-tagged,
trust-tiered, signed, and **anchored to a WIMSE/DID agent identifier** (consume,
don't reinvent identity) and **carried over A2A/MCP** (consume, don't reinvent the
wire). The differentiator is **governance + provable behavior**, not portability
alone — exactly where the startups are weak.

**No-hivemind guardrail (non-negotiable).** This is about the **customer's own
portable, sticky, owned instance** and the external agents *they* operate — never
cross-customer pooling. It strengthens the existing "portable instance you own"
principle; it does not create a data network effect across tenants.

**Why moonshot.** Defining a format others adopt is category ownership and a
durable standards-position moat (the AGNTCY-adjacent venue is the place to lead or
deliberately stay proprietary). Risk is adoption, not feasibility — the capsule
already exists.

**Builds on.** `operating_record.py` (`export_capsule`), `fleet_memory.py`,
`audit/signing.py`, Rust verifier; plus the deferred merge/split for M&A.

**Compliance trigger.** EU Art. 12 lifetime record + portability; vendor-lock-in /
exit-clause procurement asks; ISO 42001 lifecycle.

**Effort/risk.** High / high (adoption). **Move-now** given the arXiv preprint.

**IP.** Spec can be open *while* the governed-enforcement mechanism stays patented
(extends #1/#3). Classic "open format, proprietary engine."

---

#### Idea 6 — Attested Federated Learning Exchange (PoI-carrying, no-hivemind)

**Thesis.** Federation today is audit-only. Make it a **live, opt-in,
operator-run exchange** where lessons/skills move between *customer-owned*
instances — each contribution carrying a **Proof-of-Improvement (Idea 1)**,
**provenance + trust-weighting (Idea 3)**, and conflict adjudication, so a
receiving fleet can *verify a foreign lesson is genuinely good before adopting it.*

**What it is.** The combinatorial payoff of Ideas 1+3+5: a signed, governed
exchange protocol where "here is a lesson, and here is cryptographic proof it
improved outcomes without regression" travels between instances — **lessons only,
signed, opt-in, operator-run**, strictly honoring the no-cross-customer-data
principle (no raw data, no automatic pooling, no hivemind).

**Why moonshot.** This is the network-effect moat *that respects the
non-negotiable* — value compounds across opt-in participants without a shared
brain, and "verify before you trust a foreign lesson" is something no federated-
learning system offers. Hardest to build; highest ceiling.

**Builds on.** `federation.py` (currently audit-only), `agent_trust.py`,
`fleet_memory.py`, dreaming, + Ideas 1/3/5.

**Compliance trigger.** Cross-agent provenance (EU Art. 72); supply-chain trust.

**Effort/risk.** Very high / high. Sequence *after* Ideas 1, 3, 5.

**IP.** New filing on "verifiable-improvement-gated federated lesson exchange."

---

#### Idea 7 — TEE-Attested Learning (hardware-rooted Proof-of-Improvement)

**Thesis.** Idea 1's certificate says "*we* signed it." For the most regulated
buyers (banks, health, gov), upgrade to "**a neutral hardware root attests the
learning/eval ran honestly in a genuine enclave.**" TEEs are GA; nobody binds them
to a *learning-improvement* claim.

**What it is.** Run the dreaming/eval pipeline inside a TEE (NVIDIA H100
Confidential Computing / Intel TDX, both GA) and fold the **enclave attestation**
into the PoI certificate — closing the "garbage-in, attested-garbage-out" gap by
attesting *both* that the honest eval code ran *and* (via Idea 1) that the eval was
contamination-resistant and showed real, non-regressing gain.

**Why moonshot.** Highest-assurance "provable learning" on the market; turns the
moat into something a competitor cannot replicate without both the eval-binding IP
*and* confidential-compute integration. NVIDIA's own disclaimer ("attestation does
not prove the model improved") is the gap this closes.

**Builds on.** Idea 1 + sandbox backends (Firecracker/K8s already present) + GPU
confidential-compute.

**Compliance trigger.** SR 26-2 / FDA PCCP / EU high-risk — strongest where
third-party verifiability is demanded.

**Effort/risk.** Very high / medium-high (infra + GPU-TEE dependency). Vendor
trust-root (NVIDIA/Intel CA) is a procurement nuance to disclose.

**IP.** New filing: "hardware-attested contamination-resistant proof of agent
improvement."

---

## Part 4 — What NOT to build (avoid the commoditizing layers)

- **Don't reinvent agent identity.** SPIFFE/WIMSE/DID are converging fast and
  should be *consumed* as the anchor for the Operating Record. (Caveat: SSO/
  identity *integration* remains Lightwork's real enterprise table-stakes gap —
  close it as integration, not as a new standard.)
- **Don't compete on memory recall quality/latency.** Zep/Mem0 own that bench;
  it's commoditizing. Compete on *governed, attributable, forgettable, provable*
  memory.
- **Don't build a new comms/discovery protocol.** A2A/MCP are the wire; consume
  them.
- **Don't rebrand around "Agentic OS."** The term is saturating; own the
  primitives others skip instead (per the prior research report).
- **Don't pursue zkML proof-of-training as the learning proof.** It doesn't scale
  to frontier and proves *execution*, not *value*. The contamination-resistant
  attested-eval path (Ideas 1/7) is the pragmatic, defensible route.

---

## Part 5 — Recommended sequencing

1. **Now (weeks):** Idea 4 (oversight ledger — trivial, immediate compliance) and
   Idea 1 (Proof-of-Improvement — flagship). File provisional #4.
2. **Next (1–2 quarters):** Idea 2 (verifiable forgetting — file provisional #5)
   and Idea 3 (mnemonic adjudication — continuation of #3).
3. **Then (2–4 quarters):** Idea 5 (publish the Operating Record format —
   move-now on adoption while the window is open), then Idea 6, then Idea 7.

This order front-loads the two strongest *and* most-shippable wedges (provable
improvement + verifiable forgetting), banks IP early (the public-repo disclosure
clock is already running — see `docs/patents/00-...`), and defers the
adoption/infra-heavy moonshots until their prerequisites exist.

---

## Part 6 — Confidence & sources

**High confidence (≥2 independent agents corroborated):** A2A excludes memory by
design; MCP trending stateless; incumbents prove actions not learning; integrity
provable today / improvement not; post-deletion verification unsolved; regulatory
convergence on the five primitives.

**Flagged / lower confidence:** Writer & Cohere memory/interop **[UNVERIFIED]**;
Salesforce deep agentic-memory GA **[partial]**; many cited 2026 arXiv items are
**preprints, not peer-reviewed**; vendor TEE overhead figures are vendor-stated;
EU high-risk dates bind only on Omnibus OJ publication (expected before
2 Aug 2026); SR 11-7 replaced by SR 26-2/OCC 2026-13 (Apr 2026), which excludes
agentic AI but is applied by analogy.

**Key external sources:** EU AI Act ([Art. 12](https://artificialintelligenceact.eu/article/12/),
[Art. 14](https://artificialintelligenceact.eu/article/14/),
[Art. 72](https://artificialintelligenceact.eu/article/72/));
[NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework);
[ISO 42001](https://www.iso.org/standard/42001);
[A2A](https://github.com/a2aproject/A2A); [MCP roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/);
[AGNTCY Identity](https://docs.agntcy.org/identity/identity/);
[IETF WIMSE](https://datatracker.ietf.org/doc/draft-ietf-wimse-arch/);
[Sigstore model-transparency](https://github.com/sigstore/model-transparency);
[NVIDIA Confidential Computing](https://developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/);
[zkML survey 2502.18535](https://arxiv.org/abs/2502.18535);
[Proof-of-Learning broken 2208.03567](https://arxiv.org/abs/2208.03567);
[Mnemonic Sovereignty 2604.16548](https://arxiv.org/html/2604.16548v1);
[Portable Agent Memory 2605.11032](https://arxiv.org/html/2605.11032v1);
[Collaborative Memory 2505.18279](https://arxiv.org/html/2505.18279v1);
[Salesforce agentic memory](https://engineering.salesforce.com/how-agentic-memory-enables-durable-reliable-ai-agents-across-millions-of-enterprise-users/);
[AWS AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/);
[Databricks MRM 2026 / SR 26-2](https://www.databricks.com/blog/model-risk-management-2026-bankers-guide-revised-interagency-guidance).

**Internal grounding:** `fleet_memory.py`, `dreaming.py`, `hindsight.py`,
`proof_pack.py`, `promotion_effect.py`, `learning_rollout.py`, `memory_guard.py`,
`operating_record.py`, `audit/signing.py`, `rust/maverick-verify-audit/`,
`docs/patents/01..03`, `docs/product-portfolio.md`.
