# The self-extending agent factory — agent & skill genesis

> **Status (June 2026):** counts and plans in this document are historical. The shipped catalog is 1,019 lint-clean agents across 26 suites with a full learning lifecycle — see [`docs/FEATURES.md`](../FEATURES.md).


**Status:** design / roadmap — a load-bearing differentiator. Companion to the eight
agent suites ([`agent-suites-overview.md`](agent-suites-overview.md)) and the
[agent-to-agent protocol](agent-to-agent-protocol.md). Builds on
[`../enterprise/architecture.md`](../enterprise/architecture.md).

> **The thesis, from first principles.** Every other "agent platform" ships a *fixed*
> roster — a human writes each agent by hand, forever. That doesn't scale to "every
> business function for every customer," and it isn't of the future. Maverick's
> difference: **the platform engineers its own agents and skills.** It studies a
> customer, *synthesizes* the agents and skills that customer needs, *proves* they're
> safe, and routes them to a human to **promote to production** — then watches them in
> the wild and **evolves** them. Humans approve; the platform authors. The one bright
> line: the factory may author new *agents*, but it never authors its own *kernel,
> safety, or governance* — self-extension, never self-modification.

This is the "genetic engineering" layer: **variation** (synthesize candidates) +
**selection** (eval + live performance) + **inheritance** (attenuated capability from a
parent template), with a hard human gate between the lab and production.

---

## Contents

1. [Why this is the differentiator](#1-why-this-is-the-differentiator)
2. [What's already shipped — the reuse map](#2-whats-already-shipped--the-reuse-map)
3. [The genesis pipeline](#3-the-genesis-pipeline)
4. [The two meta-agents](#4-the-two-meta-agents)
5. [The control model — why it's safe to let run "by itself"](#5-the-control-model--why-its-safe-to-let-run-by-itself)
6. [Per-customer customization — the genome](#6-per-customer-customization--the-genome)
7. [Build sequence](#7-build-sequence)
8. [Honest caveats](#8-honest-caveats)

---

## 1. Why this is the differentiator

A company is not a fixed org chart — it grows roles, retires them, and invents new ones
as the business changes. A platform that claims to run "every business function" must do
the same **without a human hand-authoring each of the ~346 agents per customer**. The
manual roster (the eight suites) is the *seed stock*; the factory is what turns a seed
into a living, customer-specific org that adapts.

The head-turning claim is narrow and defensible: **Maverick writes, tests, and proposes
its own workforce, and improves it from its own track record — under a human's signature.**
Not an "AI-native OS," not a chatbot that "has agents." A self-extending system with the
safety rails built into the substrate.

---

## 2. What's already shipped — the reuse map

The factory is mostly *assembly* of primitives that already exist — which is exactly why
it's credible rather than vaporware.

| Capability | Module / surface | Status | Role in the factory |
|---|---|---|---|
| **Generated-profile authoring** | `domain.py` — `DomainProfile(authoring="generated")`, `agent_from_profile`, `load_domains` | **Shipped** | The output format: a synthesized agent *is* a generated pack |
| **Customer intake** | `assessment.py` (`start`→`answer`→`finalize`) | **Shipped** | Produces the customer's Operating Profile (§6) |
| **Skill distillation** | `skills.py` — `distill(trajectory)→SKILL.md`, `validate_skill_file`, `install`, Ed25519 `sig` + `trusted_pubkeys` | **Shipped** | The skill side of synthesis: author/validate/sign new skills |
| **Performance signal (selection)** | `skill_stats.decay_weights`, `skill_embeddings` | **Shipped** | The fitness function — what's earning its keep vs decaying |
| **Capability envelope** | `capability.py` — signed, **attenuating**, principal-bound | **Shipped** | A generated agent is born ≤ its template's grant; signed provenance |
| **The approval gate** | `governance.py` — `REQUIRE_HUMAN` (Art 14) | **Shipped** | "Send it for approval to go into production" |
| **Compartment seals** | `quarantine.py` (Rung-2) | **Shipped** | Candidates are born quarantined; a bad one is sealed instantly |
| **Sandbox** | `sandbox.exec()` (7 backends + egress policy) | **Shipped** | Synthesis + eval run sandboxed, never on the host SoR |
| **The record** | the signed Merkle audit chain | **Shipped** | Provenance: who synthesized what, from which template, approved by whom |
| **Suite toggles** | `[suites]` + `enabled_domains()` | **Shipped** | The factory only synthesizes within the customer's enabled functions |

**The genuine build:** the **orchestration** — the genesis pipeline (§3), the two
meta-agents (§4), the candidate→production promotion workflow, and the revocation list.
The *controls* (capability, gate, seal, audit, sandbox) are shipped.

---

## 3. The genesis pipeline

Each stage maps to a shipped primitive; the arrows that cross into production are
human-gated.

```
  ┌─────────┐   ┌────────────┐   ┌────────┐   ┌────────┐   ╔═════════╗   ┌─────────┐   ┌─────────┐
  │ INTAKE  │──▶│ SYNTHESIZE │──▶│ VERIFY │──▶│ STAGE  │──▶║ APPROVE ║──▶│ PROMOTE │──▶│ OBSERVE │
  │ profile │   │ (variation)│   │ (fit)  │   │(sealed)│   ║ (human) ║   │ (signed)│   │(AgentOps)│
  └─────────┘   └────────────┘   └────────┘   └────────┘   ╚═════════╝   └─────────┘   └────┬────┘
       ▲                                                                                     │
       └──────────────────────────── EVOLVE (selection) ◀────────── RETIRE ◀────────────────┘
```

1. **Intake → Operating Profile.** `assessment.py` interviews the business (functions,
   systems, data sensitivity, risk posture, automation dials) and emits the signed,
   versioned **Operating Profile** (§6) — the genome the factory builds within.

2. **Synthesize (variation).** The **Agent-Engineer** (§4) emits *candidate* artifacts:
   `DomainProfile` packs (`authoring="generated"`) and `SKILL.md` files scoped to the
   customer's actual systems and roles. Runs entirely in the sandbox. Output is data
   (TOML + markdown), not running agents.

3. **Verify (fitness).** Two gates, both shipped-primitive-backed:
   - *Static:* schema-load, the `test_suite_domains` invariants (read-only/safe or
     builder + `self_edit` floor), `validate_skill_file`, and a **Shield scan of every
     persona/skill body** (synthesized text is untrusted — prompt-injection defense).
   - *Dynamic:* the eval/benchmark harness + `assessment` templates run the candidate
     against scenarios → a **fitness score**. No score, no promotion.

4. **Stage (sealed).** Candidates are Ed25519-signed, born **read-only and attenuated**,
   and quarantined into a `candidate` compartment. They can be inspected but **cannot
   touch production data or systems of record**.

5. **Approve (human — the bright line).** `governance.evaluate` returns `REQUIRE_HUMAN`
   for the `promote_agent`/`publish_skill` actions. A human reviews the **diff** —
   persona, capability envelope, skills, fitness, provenance — and signs. This is the
   "send it for approval" step the product is built around. **Nothing self-promotes.**

6. **Promote (signed).** On approval the pack/skill moves from `candidate` into the
   active domains/skills set (the tenant's `user_dir` / signed catalog), capability
   enforcement on, provenance written to the audit chain.

7. **Observe (AgentOps).** Per generated agent, AgentOps (§4) tracks live signals:
   `skill_stats` outcomes, `governance` verdicts, Shield blocks, budget burn, escalation
   rate.

8. **Evolve (selection + inheritance) / Retire.** Underperformers **decay in ranking**
   (`skill_stats`) and are flagged; the Agent-Engineer proposes **mutations** — revised
   candidates distilled from the observed failures (reflexion) — which re-enter at stage 2.
   Inheritance is structural: a child's capability is `attenuate()`d from its template, so
   a mutation can never escalate. AgentOps deprecates and **revokes** a retired agent
   fleet-wide.

The loop is the "genetic" part: a customer's workforce is continuously varied, selected
on real performance, and promoted only through a human — a population that gets fitter,
not a static install.

---

## 4. The two meta-agents

These are the new seats this layer adds (they belong in the **Product & Engineering** and
**IT/GRC AI-Governance** suites, spawned at the Layer-A altitude).

### 4.1 Agent-Engineer (the genetic engineer)
- **Job:** Synthesize and revise `DomainProfile` packs + `SKILL.md` skills for a customer
  from the Operating Profile and observed performance. Builder-class (sandbox-mediated).
- **Hard floor:** may author **new agents/skills only** — **never** the kernel, the
  safety layer (`safety/*`, the Shield), `capability.py`/`governance.py`/`quarantine.py`,
  or its own pack. `self_edit` is denied; it has no write access to `maverick/` runtime
  code. This is the same self-modification floor the P&E builders carry, applied to the
  most powerful seat in the system. **Self-extension, not self-modification.**
- **Bound:** every artifact it emits is `attenuate()`d to ≤ the customer's
  Operating-Profile ceiling and Ed25519-signed; it cannot grant a child more than the
  template holds.

### 4.2 AgentOps (the fleet SRE)
- **Job:** Lifecycle for the synthesized fleet — health, versioning, the
  candidate→production promotion workflow, rollback, drift/decay watch, retirement, and
  the **revocation list**. The operational arm of the Layer-A oversight plane (`fleet.py`
  + the supervisor).
- **Authority:** proposes promote/rollback/retire; the *production* transitions are
  `REQUIRE_HUMAN`. It can **quarantine** a misbehaving generated agent immediately
  (containment is allowed; promotion is gated).

---

## 5. The control model — why it's safe to let run "by itself"

The whole point is autonomy *up to* the gate. Five rails make that safe:

1. **Sandboxed synthesis.** The Agent-Engineer runs in the sandbox; candidates are data,
   quarantined, read-only — they touch no system of record before promotion.
2. **The human promotion gate is absolute.** `REQUIRE_HUMAN` on `promote_agent` /
   `publish_skill`. No path promotes an agent without a human signature. (The product
   *is* "it builds it and sends it for approval.")
3. **Capability ceiling by attenuation.** A generated agent's grant is provably ≤ the
   customer's Operating-Profile ceiling; a synthesized agent can never out-scope what the
   customer authorized.
4. **The self-modification floor.** The factory never authors/edits the kernel, safety,
   capability, or governance. This single line is what separates Maverick's
   self-extension from the unsafe kind; it is enforced as a denied tool surface, not a
   policy promise.
5. **Signed provenance + instant containment.** Every synthesis and promotion is signed
   and on the audit chain (which engineer, from which template, under which grant,
   approved by whom). A bad generated agent is `quarantine`-sealable and **revocable**
   fleet-wide in one action.

---

## 6. Per-customer customization — the genome

The **Operating Profile** (intake-produced, wizard-editable, signed + versioned — CLAUDE.md
rule 6) is the genome. It compiles to:

- the **enabled suites/functions** (`[suites]`),
- the **capability ceiling** (the deployment ACL / RBAC roles the factory attenuates from),
- the **automation dials + hard floors** (per the suite docs' L0–L4 ladders), and
- the **system inventory** (which connectors exist → which `[C]` skills are real vs to build).

The factory synthesizes *within* the genome. Two customers in the same industry get
different live workforces because their genomes differ — without a fork, and without a
human writing 346 packs twice.

---

## 7. Build sequence

1. **Promotion gate + provenance first.** Wire `promote_agent`/`publish_skill` as
   `REQUIRE_HUMAN` governance actions writing signed provenance — the safety spine before
   any autosynthesis exists.
2. **The candidate compartment + staging** (quarantined, read-only, signed) on
   `quarantine` + `capability`.
3. **The verify harness** — schema/invariant/`validate_skill_file`/Shield static gate +
   the eval/assessment dynamic gate → a fitness score.
4. **Agent-Engineer (synthesis)** from an Operating Profile → candidates (start with
   skills via the shipped `distill`, then packs).
5. **AgentOps (observe/evolve/retire)** on `skill_stats` + `fleet` + the revocation list.
6. **Wizard + console** (rule 6): the Operating-Profile editor and the human
   promotion/rollback queue.

---

## 8. Honest caveats

- **The human gate is load-bearing — never auto-promote.** The autonomy is in the lab;
  production is a signature. Removing that gate is the failure mode that makes this
  dangerous instead of differentiating.
- **Selection is only as good as the eval.** Garbage fitness → garbage evolution. The
  eval/assessment harness quality bounds the whole loop; invest there.
- **Synthesized text is untrusted.** Generated personas/skill bodies are concatenated
  into system prompts; they MUST pass the Shield scan (a synthesized "ignore previous
  instructions" is a real risk — same defense as `skills.install`).
- **The self-modification floor is the bright line.** The instant the factory can edit
  its own safety/governance, every other control is theoretical. Keep it denied, keep it
  greppable, test it.
- **Provenance or it didn't happen.** If a promotion isn't signed and on the chain, it
  can't be audited or revoked cleanly. No silent promotions.
