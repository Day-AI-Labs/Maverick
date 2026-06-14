# Moonshot Bets — the "$50M, buy-don't-build" theses

Working doc. Each bet is a capability a model vendor (Anthropic / Google /
Microsoft) is *structurally disqualified* from building themselves — because it
requires vendor neutrality — and that becomes a standard or a data-gravity moat.
Grounded in modules that already exist in this repo, so each is a build-path, not
vaporware.

---

## Bet 1 — The Trust Layer: third-party-verifiable behavioral attestation

**Thesis.** We are not an agent company; we are the neutral, cryptographically
provable *control plane* above the agents. The three buyers are walled gardens
and cannot credibly be the Switzerland that governs an enterprise running Claude
*and* GPT *and* Gemini agents at once. That neutrality is the one moat they can't
clone — they must buy it.

**The one feature.** Promote `proof/run_proof.py` + the Operating Record capsule
into a **portable, regulator/insurer/acquirer-grade proof bundle** that a party
trusting *neither the operator nor the model vendor* can verify with one command.
It proves three things no one else can prove today:

1. Every action stayed inside a declared policy envelope (capability + governance,
   enforced at `agent._run_tool`).
2. **The self-improvement loop never escaped that envelope** — the agent got
   smarter without ever granting itself new authority. The unique claim. Already
   *enforced* (`maverick-evolve/adopt.py` whitelist, `calibration.py` freeze);
   now *proved*.
3. The decision history is authentic and reproducible from the signed trajectory
   (`audit/signing.py` chain + cross-file anchors).

**Bleeding edge.** Make the attestation work *without revealing the underlying
data*: TEE-attested (`confidential_compute.py` already detects SEV-SNP/TDX) plus
zero-knowledge-style proofs of policy compliance. A bank proves "every agent
action satisfied policy P" without exposing the trades. Does not exist anywhere.

**Why $50M pre-ARR.** Standard capture (be the Sigstore/SBOM of agents) →
buy-the-standard-and-team. Makes agentic AI *insurable* (the underwriting
substrate). Regulatory tailwind = free distribution (EU AI Act Art. 12/15,
SR 11-7, AI-liability wave; artifacts already scaffolded in `ai_act_package.py`,
`dpia.py`, `ropa.py`).

**Per-buyer wow.** Anthropic: a verifiable claim that self-improvement stays
bounded is their north star. Microsoft: Copilot's enterprise blocker is
governance/system-of-record; we are it, cross-vendor. Google: Vertex/Agentforce
can't offer neutral cross-vendor attestation; acquiring is the only path.

**Build path (~1 quarter to demo).**
1. `run_proof.py` → continuously-emitted attestation bundle signed into the
   Operating Record capsule (~60% there).
2. Add the "self-improvement stayed in-envelope" proof by chaining
   `adopt.py`/`calibration.py`/`hindsight.py` evidence into the signed bundle.
3. Ship a standalone verifier (`maverick attest verify capsule.mvk`) needing zero
   access to our infra or the model vendor — the "hand a regulator a USB stick"
   demo.
4. Moonshot: TEE-attested + ZK policy proof for the confidential case.

**Centerpiece demo.** Regulated firm runs a swarm, hands an outside auditor a
sealed capsule, auditor runs one command, it cryptographically confirms *what the
AI did, what it learned, and that it never gave itself more power than it was
granted* — without ever seeing the data.

---

## Bet 2 — The Institutional Memory: a vendor-neutral plane that compounds and ports

**Thesis.** Bet 1 proves the *past* was safe. Bet 2 owns the accumulating
*future*. The deepest enterprise moat isn't the model — models commoditize — it's
the firm's accumulated operational judgment. Whoever owns the enterprise's
agent memory owns the account, forever. Build the **neutral, governed,
compounding system of record for everything every agent learns**, regardless of
model vendor. This is data gravity: the longer it runs, the more irreplaceable it
becomes, and switching cost approaches infinity. This is the literal answer to
"hit the milestone and the ARR will come" — it is the stickiest possible asset.

**The one feature.** Make institutional memory **cross-vendor, compounding, and
provably improving.** Every agent interaction — a Claude swarm, a Copilot agent,
an Agentforce flow — deposits and retrieves reusable, department-scoped,
capability-bounded knowledge through ONE governed plane. We already have the
substrate: `fleet_memory.py` (external Agentforce/Copilot/custom agents ingest +
recall through a fail-closed governed surface), `operating_record.py` (signed
portable capsule of the firm's decisions + learned state), `dreaming.py`
(consolidation), `hindsight.py` (proof it's improving), `semantic_recall.py`,
learned skills, reflexions. Today they're internal; productize them as **the
memory API beneath all of an enterprise's agents.**

Three properties make it a moat, not a feature:
1. **Cross-vendor.** A Copilot agent benefits from a lesson a Claude agent learned
   last week — through `fleet_memory` over MCP. We are the substrate; the model
   vendors become interchangeable front-ends.
2. **Compounding & provable.** Cost-per-task drops with use (the cold-vs-warm
   `benchmarks/moat.py` curve), and we can *prove* it's getting better
   (`hindsight.py`) without it reward-hacking (`calibration.py` freeze). The
   Operating Record becomes a portable, appreciating asset — judgment on the
   balance sheet.
3. **Governed & private.** Department bulkheads (`compartment`), per-user notes
   never cross channel/user boundaries, scope tagging, shield-scan-on-ingest
   (RAG-poisoning defense), per-tenant KMS. Memory that's safe to pool is the
   hard part — and we already enforce it.

**Why $50M pre-ARR.** Data gravity = the highest switching cost in software; a
firm with two years of accumulated, department-scoped, provably-improving judgment
in Maverick cannot leave. Vendor-neutral = the same Switzerland logic as Bet 1
(buyers can't build it neutrally). It makes *their* models stickier inside the
account, which is exactly why Microsoft/Anthropic/Google would pay to make their
agent the front-end to *our* memory rather than cede the substrate to a rival.

**Per-buyer wow.** Microsoft: Copilot becomes the UI on top of an enterprise's
real institutional memory — the thing Copilot conspicuously lacks. Anthropic:
Claude agents that visibly compound per-customer (their agentic deployment story
gets a flywheel). Google: the cross-vendor memory plane Vertex can't offer because
it's a walled garden.

**Build path (~1 quarter to demo).**
1. Harden `fleet_memory.py` into a stable public **Memory API** (ingest/recall/
   attest) over MCP + REST, with governance + provenance on every read/write
   (mostly there).
2. Ship the **cross-vendor proof demo**: connect a non-Claude agent (Copilot/
   LangChain) and a Claude swarm to one memory plane; show the second agent using
   the first's lesson.
3. Wire the **compounding dashboard**: live cold-vs-warm cost curve per department
   (`benchmarks/moat.py` + `role_stats.py` + `hindsight.py`), exportable as a
   signed Operating Record capsule (ties back to Bet 1).
4. Moonshot: a "memory portability" standard — the firm's judgment exports as a
   signed, vendor-neutral capsule it owns and can carry between platforms. Owning
   that format is owning the category.

**Centerpiece demo.** Two agents from two different model vendors, one governed
memory plane. Agent B solves in 30 seconds and $0.02 a task that cost Agent A ten
minutes and $2 last week — because it inherited A's distilled skill. Then export
the whole thing as a signed capsule the customer owns. "Your AI workforce gets
smarter every day, across every vendor, and you can prove it and take it with you."

---

### How the two bets relate

Bet 1 = *prove the past was safe* (trust / attestation / insurability).
Bet 2 = *own the accumulating future* (memory / compounding / data gravity).
They share the same neutral-Switzerland moat and the same signed Operating Record
capsule as the connective tissue — ship the capsule format once and both bets
ride it. Bet 1 is the wedge that gets you in the door of regulated buyers; Bet 2
is the thing that makes them unable to leave.

