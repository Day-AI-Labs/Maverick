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

**Thesis.** Bet 1 proves the *past* was safe. Bet 2 compounds the accumulating
*future*. The deepest enterprise moat isn't the model — models commoditize — it's
the firm's accumulated operational judgment. The firm that accumulates that
judgment in a governed, portable memory can't be cheaply displaced — and the
judgment is *theirs*: isolated to their boundary, owned, and exportable. Build the
**neutral, governed, compounding system of record for everything the customer's
own agents learn**, regardless of model vendor. The longer it runs, the more
valuable and bespoke *their* instance becomes — never pooled with another
customer's, never training ours, never leaving their walls. This is the literal
answer to "hit the milestone and the ARR will come" — stickiness earned through
customer-owned value, not data we harvest.

**The one feature.** Make institutional memory **cross-vendor, compounding, and
provably improving — inside a single customer's isolated boundary.** Within one
customer's deployment, every agent interaction — a Claude swarm, a Copilot agent,
an Agentforce flow — deposits and retrieves reusable, department-scoped,
capability-bounded knowledge through ONE governed plane; one customer's memory
never reaches another's. We already have the
substrate: `fleet_memory.py` (external Agentforce/Copilot/custom agents ingest +
recall through a fail-closed governed surface), `operating_record.py` (signed
portable capsule of the firm's decisions + learned state), `dreaming.py`
(consolidation), `hindsight.py` (proof it's improving), `semantic_recall.py`,
learned skills, reflexions. Today they're internal; productize them as **the
memory API beneath all of an enterprise's own agents.**

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
   (RAG-poisoning defense), per-tenant KMS. Memory that's safe to **share across a
   customer's own agents and vendors — without one tenant's data ever reaching
   another's** is the hard part, and we already enforce it (learned stores resolve
   under each tenant's data dir; one tenant's memory never feeds another's runs).

**Why $50M pre-ARR.** A firm with two years of accumulated, department-scoped,
provably-improving judgment has something it can't quickly rebuild elsewhere — and
it *owns* that judgment as a signed, vendor-neutral, portable capsule. That earned
value — not lock-in over data we hold — is what makes the platform sticky.
Vendor-neutral = the same Switzerland logic as Bet 1 (buyers can't build it
neutrally). Microsoft/Anthropic/Google would pay to make their agent the front-end
to the customer's *own* governed memory rather than cede the neutral substrate to a
rival.

**Per-buyer wow.** Microsoft: Copilot becomes the UI on top of an enterprise's
*own* institutional memory — the thing Copilot conspicuously lacks. Anthropic:
Claude agents that visibly compound inside each customer's own isolated instance
(their agentic deployment story gets a flywheel). Google: the cross-vendor memory
plane Vertex can't offer because it's a walled garden.

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

**Centerpiece demo.** Within one customer's deployment, two agents from two
different model vendors share one governed, isolated memory plane. Agent B solves
in 30 seconds and $0.02 a task that cost Agent A ten minutes and $2 last week —
because the customer's own fleet already taught it that lesson. Then export the
whole thing as a signed capsule the customer owns. "Your AI workforce gets smarter
every day on your data, across every vendor you run — and it never leaves your
walls. You can prove it, and take it with you."

---

## Bet 3 — Safe Recursive Self-Improvement: the alignment-frontier "wow"

**Thesis.** The most important — and most feared — capability in AI is an agent
that improves *itself*. Every frontier lab wants it and is terrified to ship it
ungoverned, because ungoverned self-improvement reward-hacks, escapes its
envelope, and can't be rolled back. Lightwork is the only platform that already
ships a *bounded, auditable, reversible* self-improvement loop. Productize that
into the credentialed path to recursive self-improvement: **agents that
provably get better without ever escaping their capability envelope.** This is
the bet that makes *Anthropic specifically* go wow — it's their deepest research
interest, de-risked and made shippable.

**The one feature.** Turn the existing loop into a demonstrable, certified
**"safe self-improvement" engine** and then climb one rung past everyone else.
Pieces already in the repo: `maverick-evolve` (config-only evolution; code
mutation deliberately deferred), `adopt.py` (adoption can never widen a
capability scope — `ADOPTABLE_KEYS` excludes `allow_*`/`max_risk`),
`calibration.py` (freezes learning the moment the verifier drifts —
anti-reward-hacking interlock), `hindsight.py` (proves it improved, or regressed),
the signed learning audit (`dreaming._audit_cycle`, snapshot + rollback). Three
properties that make it singular:

1. **Bounded.** Self-improvement runs inside a capability envelope it can never
   widen — proven, not asserted (`adopt.py` + capability attenuation).
2. **Non-reward-hacking.** The calibration interlock freezes evolution when the
   judge stops discriminating, so the system can't learn to game its own grader.
3. **Reversible + audited.** Every learning cycle is snapshotted, rollback-able,
   and written to the signed audit chain — you can undo what the AI taught
   itself and prove what changed.

**Bleeding edge.** Ship the rung the labs deferred: **bounded code
self-modification** — the agent proposes changes to its *own* tools/policies, but
only inside an out-of-process sandbox, under capability bounds, with
human-gated promotion (the Darwin-Gödel step `maverick-evolve` explicitly
parked). Done *with* the governance rails, not without them. That is the frontier
capability every lab wants and no one dares ship raw.

**Why $50M pre-ARR.** This is the safety-credentialed path to RSI. Whoever owns a
*demonstrably bounded* self-improvement loop owns the most valuable and most
dangerous capability in AI, done in the one way regulators and boards will
tolerate. It is also un-buildable in a hurry: the moat is the *interlocks*
(calibration freeze, capability-never-widens, signed rollback), which took this
codebase years of safety-first design to assemble correctly.

**Per-buyer wow.** Anthropic: bounded RSI is their north-star research problem,
arriving pre-governed and demoable. Google/Microsoft: a self-improving workforce
they can put in front of a board without the liability — the thing their own legal
teams won't let them ship ungoverned.

**Build path (~1 quarter to demo).**
1. Wire `maverick-evolve` continuous loop → live "improvement certificate":
   each round emits a signed proof that capabilities never widened and
   calibration never unfroze (chains into the Bet 1 capsule).
2. Dashboard the cold-vs-warm improvement curve per department with the rollback
   button visible — "undo what it learned" is the trust unlock.
3. Moonshot: the sandboxed, human-gated code-self-mod rung, with every proposal
   diffed, capability-checked, and promotion-gated.

**Centerpiece demo.** An agent system measurably rewrites its own playbooks over a
week and gets cheaper and more reliable — then you show, cryptographically, that
it never granted itself a single new permission and never gamed its grader, and
you roll one bad lesson back with one click. "Self-improving AI you can actually
sleep next to."

---

## Bet 4 — The Agent Security Plane: "CrowdStrike for AI agents"

**Thesis.** Bet 1 *proves* compliance after the fact; Bet 4 *actively defends* in
real time. The number-one reason enterprises won't deploy autonomous agents is
fear of compromise: prompt injection, tool abuse, data exfiltration, poisoned
RAG, malicious MCP servers and plugins, runaway swarms. Lightwork already contains
the most complete agent-runtime defense stack in existence — but it's buried as
internal plumbing. Surface it as a standalone, vendor-neutral **runtime security
product** for agent fleets: detection, containment, and continuous adversarial
evaluation. This bet also *diversifies the acquirer pool* beyond the three —
Microsoft Security/Defender, Google Mandiant/Chronicle, CrowdStrike, Palo Alto.

**The one feature.** A live **agent detection-and-response (agent-EDR) plane**
that watches every agent — yours or any vendor's, via MCP — and detects, contains,
and proves compromise in flight. Pieces already in the repo: the shield (3
chokepoints, ~35 de-obfuscating rules, cross-family lockstep-jailbreak defense),
capability attenuation + revocation, `honeytokens.py` + `canaries.py` (exfil/
escape tripwires), `quarantine.py`/compartments (seal a compromised agent
mid-run, withhold its output from the swarm), `leak_quarantine.py`, the SSRF
guards, Shield-scanning of untrusted MCP/plugin schemas, `threat_hunt.py` over the
audit trail, `ebpf_monitor.py`, and the offensive side — the red-team corpus +
calibration runner + `capability_leak_fuzzer`. Productize as:

1. **Detect.** Continuous adversarial evaluation (red-team corpus as a live
   regression gate) + runtime injection/exfil detection across the fleet.
2. **Respond.** Mid-run containment — quarantine-seal a compromised agent, revoke
   its capability subtree, black-hole its egress — without killing the swarm.
3. **Prove.** Every detection + response written to the signed audit chain (the
   forensic record insurers and IR teams need; ties to Bet 1).

**Bleeding edge.** Make it the neutral "agent-EDR telemetry standard" — any
vendor's agent emits Lightwork-format security telemetry over MCP, and the plane
scores/contains across all of them. Own the format, own the category.

**Why $50M pre-ARR.** Security is the highest-willingness-to-pay budget in the
enterprise, with its own buyer and its own acquirer set — so this bet is both a
moat and a hedge: if the model vendors don't move, the security platforms will.
And the assets (a coherent, tested, fail-closed agent-defense stack with offense +
defense + forensics) cannot be assembled quickly; it took this codebase's
safety-first posture to build correctly.

**Per-buyer wow.** Microsoft: Defender for AI agents, cross-vendor, day one.
Google: Mandiant/Chronicle gain an agent-runtime sensor + IR capability. Anthropic:
a runtime that can *prove* it defeated an attack class (cross-family verifier vs
lockstep jailbreak) — a verifiable security claim.

**Build path (~1 quarter to demo).**
1. Expose the defense stack as a **security telemetry + control API** over MCP
   (detections, seals, revocations) — fleet-wide, vendor-neutral.
2. Ship the **containment demo**: inject a compromised tool/MCP server, watch the
   honeytoken trip, the agent get sealed mid-run, its capability subtree revoked,
   and the whole incident land in the signed audit trail.
3. Wrap the red-team corpus + capability fuzzer as a **continuous adversarial
   eval** product (CI gate + scheduled fleet scans).

**Centerpiece demo.** A malicious MCP server tries to exfiltrate secrets through a
compromised agent. The honeytoken trips, the agent is quarantine-sealed mid-run,
its output is withheld from the swarm, its capability subtree is revoked, egress is
black-holed — and the analyst gets a signed forensic timeline. "Your agents get
attacked. Ours fight back and prove it — no matter whose model they run."

---

### Build log — the moat spine (shipped)

The council's verdict: none of the four bets is a moat on its own; the moat is
**safe, governed, deployable self-improvement** — the interlocks that make
self-modification shippable into a regulated buyer. Step one of that is built:

- **`maverick.self_improvement`** — the Self-Improvement Controller: a governed
  promotion ladder (`config → prompt → tool → policy → code → weights`). A
  proposed self-change is promoted only if it (a) beats its own baseline by a
  margin with enough evidence, (b) **never widens the capability envelope**
  (declared, or proven via a before/after grant probe), (c) is human-approved at
  `code`/`weights` and above the `max_auto_rung` ceiling, (d) is reversible, and
  (e) is refused while `calibration.learning_frozen()` (the verifier-drift
  interlock). Every promotion is signed into the audit chain
  (`EventKind.LEARNING_UPDATE`) and recorded in a reversible ledger. OFF by
  default, fail-open while off, fail-**closed** when deciding. 20 deterministic
  tests, ruff/vulture clean. Config: `[self_improvement]` (`config.get_self_improvement`).

This is the spine every rung hangs on. Remaining work to reach *real* (not
config-only) self-improvement, in order — each rung plugs into the controller as
an opaque candidate payload and inherits the gates above:

1. **Phase 0 capture** — governed raw-trajectory store; wire `prm.py` into the
   agent loop (today it's observability-only); auto-collect calibration samples;
   live cold→warm compounding metric.
2. **Phase 1 judgment** — train the verifier/PRM (`training/prm_train.py`) on
   labeled outcomes.
3. **Phase 2 policy** — stand up real `training/rlaif.py` (per-tenant LoRA/DPO).
4. **Phase 3 action space** — close the loop on `self_learning.write_generated_tool`
   (measure/promote/retire by outcome).
5. **Phase 4 strategy** — expand `maverick-evolve` beyond 5 config knobs to
   prompts/playbooks/policies.
6. **Phase 5 code** — sandboxed, human-gated code self-modification (Darwin-Gödel).
7. **Phase 6 weights** — periodic per-tenant fine-tune on accumulated trajectories.

Phases 2/5/6 require GPUs / real model training / safety review and cannot be
validated in a keyless CI sandbox — they land behind the controller's gates as
the deployment matures.

### Build log — update 2 (all phases wired to the controller)

Every phase now flows through the merged controller's gates. Status:

- **Phase 0 capture — BUILT & TESTED.** `maverick.trajectory_store` (governed,
  per-tenant, secret-redacted, consent-gated raw-trajectory store, off by
  default); `maverick.prm_guidance` + a default-off `agent.py` hook that lets the
  process-reward model *steer* the loop (it was observe-only); and
  `maverick.compounding_metric` — the live cold→warm cost/quality signal (the
  un-fakeable moat proof).
- **Phase 3 action space — BUILT & TESTED.** `si_producers.ToolOutcomeTracker`
  measures whether a synthesized tool actually helps; `propose_tool` promotes it
  only when its success rate beats baseline and it doesn't widen capability.
- **Phase 4 strategy — BUILT & TESTED.** `propose_prompt`/`propose_policy` route
  prompt/playbook/policy changes through the gate.
- **Phases 1, 2, 6 — pipeline + seam BUILT & TESTED; training is the seam.**
  `propose_verifier` (adopt a retrained head only if it discriminates better),
  `propose_policy` (an RL/DPO adapter), `propose_weights` (a fine-tuned
  checkpoint, human-gated). The governance/adoption path is real and tested; the
  GPU training that *produces* the artifact is an injected callable — never
  faked — and lands when a GPU/model is available.
- **Phase 5 code self-mod — safe pipeline BUILT & TESTED; generation gated.**
  `propose_code` runs an out-of-process `validate` seam *before* the gate, which
  then forces human approval + non-escalation + reversibility. The diff
  *generation* stays behind a hard flag + human gate.

~67 new deterministic tests across the tranche; ruff + vulture clean; full core
suite collects (8,289 tests, no errors). Everything off by default.

### Build log — update 3 (model-agnostic completion + the OS-model decision)

**Decision (consistent with prior guidance and the council): no open-weights
base model.** The default reasoning brain stays a frontier closed model and is
swappable per role (kernel rule 2: `ROLE_MODELS` defaults are last-resort,
overridable across 13 providers within the admin allow-list). The moat is
governance + per-customer compounding *on top of* the best model — not owning
one. So real self-improvement is the **model-agnostic** rungs; weight-level
fine-tuning (Phases 2/6) is demoted to an *optional, sovereign-/air-gap-only*
seam, never the default and never the strategy.

Model-agnostic completion glue shipped (`self_improvement_runner.py`,
`trajectory_store` wired into `agent._score_step`, `maverick compounding` CLI):

- **Capture is live** — the agent now writes governed, redacted trajectory steps
  (off by default).
- **Judgment** — `build_prm_examples` turns trajectories into training rows for
  the small reward *head* (an MLP, not an LLM — no open-weights model implied).
- **Tools** — `review_generated_tools` promotes a synthesized tool that earns it
  and retires one that doesn't (the FORGET half).
- **Strategy** — `emit_strategy_candidate` routes prompt/skill/policy changes
  through the gate.
- **Calibration** — `collect_calibration` arms the verifier-drift interlock from
  any ground-truth source.
- **Proof** — `maverick compounding` reports the live cold→warm cost/reliability
  delta per task class.

What remains for full *training* completion is infra/business, not code: a real
workload (design partner) for the eval signal + data, GPU/compute, and a raw-text
capture consent decision — the same four moves the council said convert the
platform into a $50M asset. The deterministic half of every rung is now built,
tested (~130 self-improvement tests total), and off by default.

## Bet 5 — Consequence-Proven Autonomy → "Earned Autonomy" (the breakthrough)

**Thesis.** The biggest blocker to enterprise agents isn't quality, it's **trust
to take irreversible action** (move money, change prod, file, send). Everyone
ships agents that draft/suggest; almost no one ships agents that *act*, because
the downside is catastrophic and unprovable. Bet 5 is the layer that makes
autonomous high-stakes action safe — and it's the synthesis of everything
Lightwork already has (sandbox, connectors' single egress chokepoint, verifier,
governance, audit chain, autonomy slider, the self-improvement controller), not
a fifth silo.

**The capability — the Consequence Engine.** Every high-stakes plan is run
through a preview + reversible-execution layer: (a) **dry-run** the irreversible
action types (the ~10 high-risk tools in `tool_risk`: wire_transfer,
post_journal_entry, run_payroll, deploy, send, file_*, ...) via the connector
chokepoint; (b) where dry-run is impossible, a **compensating-action** layer —
every action ships its inverse and executes inside a saga that rolls back on any
failure or human rejection; (c) emit a **signed consequence card** ("this would
move $240k, close these 3 tickets, change this config"); (d) gate real execution
on policy/human approval of the *simulated* outcome; (e) sign the whole
sim → approve → execute chain into the audit record.

**One engine, three moats:**
1. **Trust to act** — clients let agents *do* the work, not just suggest it
   (where the real dollars are).
2. **The safe RL environment** — you can't RL on real money movement; you *can*
   against dry-run/compensating execution. The shadow layer is the practice
   ground that makes high-stakes self-improvement possible. The
   **predicted-vs-actual gap is the training signal** that improves the predictor.
3. **Compounding trust** — every real outcome makes the predictor more faithful,
   which unlocks more autonomy, which generates more data.

**The 10x reframe — Earned Autonomy.** Trust is the product and it compounds. As
the consequence-predictor proves accurate (measured: predicted vs actual, per
action type, per customer), the system **progressively earns autonomy**: an
action type predicted correctly N times graduates from "human approves" to
"policy auto-approves." Not a scary binary switch — an **autonomy dial driven by
evidence**, wired to the existing `autonomy.py` slider + `calibration`. One line:
*"your agents earn the right to act, action type by action type, by proving they
predict consequences correctly, with a guaranteed undo until they have."*

**3-round council evolution (how it got here):**
- **R1 (attack):** a faithful full-system digital twin is research-grade; a wrong
  sim trusted is worse than no agent; per-tool what-if already exists; Musk: just
  build a perfect undo. → Drop "simulate everything"; do dry-run of the
  irreversible action types + a compensating-rollback saga (undo fused with
  preview).
- **R2 (moat):** novelty = a *uniform, cross-tool, governed, signed*
  consequence+rollback layer over every connector (per-tool what-if isn't that).
  Karpathy: it's also the safe RL environment; predicted-vs-actual is the
  learning signal. Underwriter: signed preview + guaranteed rollback = insurable.
  → MVP: "Shadow Mode for the ~10 irreversible action types."
- **R3 (10x):** trust compounds → Earned Autonomy: agents measurably graduate
  from human-approved to policy-auto-approved per action type. The autonomy dial
  is driven by proven prediction accuracy.

**Why the named buyers beg.** ServiceNow: their platform is execution; this is the
only safe way to turn their workflows autonomous — they can't ship it without
this layer. Clients: "show me what it'll do, let me approve, guarantee the undo,
and let it earn more trust over time" is a painkiller. Anthropic: a verifiable
safety story for autonomous action.

**Defensibility.** Requires governance + connectors + sandbox + verifier + audit +
the self-improvement loop + the autonomy slider — Lightwork has all of them; a
competitor must build the entire stack. The earned-autonomy ledger + the
per-customer consequence-predictor are non-portable. Multi-year moat.

**Honest critique (kept in view).** A faithful twin of arbitrary systems is hard —
so don't build one; dry-run only the irreversible action types through the
connector chokepoint and lean on the compensating-rollback saga for the
sim-to-real gap (the gap is itself a learnable signal). Start narrow (the
high-risk tool list), expand. And it still needs a design partner to be real.

**Karpathy on the self-improvement architecture (recorded):** approves the
*shape* — thin governed spine, model-agnostic verifier head, freeze-on-drift
anti-reward-hacking interlock, cheap rungs first, reversibility. Two caveats:
(1) it's "an empty gym" until real trajectories + a calibrated reward model run
through it — prove the verifier-head rung end-to-end on one real workload before
declaring victory; (2) make the calibrated verifier central (not optional) and
**decouple capture from PRM-enabled** (capture should be unconditional/cheap).
Bet 5's shadow layer is also his answer to "you can't RL high-stakes actions on
production" — it's the safe environment that makes the architecture trainable.

### How the four bets relate

| Bet | One-liner | Tense | Primary buyer pull |
|---|---|---|---|
| 1 — Trust Layer | prove the past was safe | past | regulated entry wedge; insurability |
| 2 — Institutional Memory | compound the customer's own accumulating judgment | future | customer-owned, portable judgment; earned stickiness |
| 3 — Safe Self-Improvement | the AI improves itself, safely | forward | alignment-frontier / Anthropic wow |
| 4 — Agent Security Plane | defend agents in real time | present | security budget; widens acquirer pool |

All four ride the **same signed Operating Record / capsule format** as connective
tissue — build that once and every bet attaches to it. They also share the one
moat the model vendors structurally can't clone: **neutrality.** Sequencing
instinct: Bet 1 is the wedge (gets you in the door), Bet 2 is the lock (makes them
stay), Bet 3 is the halo (makes the labs covet you), Bet 4 is the hedge (a second
buyer universe if the labs stall). Pick the wedge first; the capsule format is the
shared spine that keeps all four optionalities open.

