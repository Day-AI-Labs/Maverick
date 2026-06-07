# Maverick for Enterprise — the governed agent control plane

> Status: architecture + roadmap (the blueprint for the enterprise pivot). This
> is the master plan the layered build follows; it doubles as the technical
> narrative for enterprise buyers (CISO / Head of Compliance / COO).

## 1. The thesis

Enterprises want **fleets of agents doing real work** — every employee backed by
5–10 specialist agents — but they cannot deploy them without two things:

1. **Oversight.** A way to see, govern, and intervene in what the agents do — a
   supervisor over the swarm, not a black box.
2. **Provable compliance.** Evidence that the agents operate within the law —
   the EU AI Act *and* the US patchwork (NIST AI RMF, Colorado, NYC LL144,
   sectoral HIPAA/GLBA/FCRA), across jurisdictions, simultaneously.

Maverick's wedge is the **control plane** that makes agent fleets *governable and
audit-ready by construction*. We already own the hardest primitives — a signed,
tamper-evident audit chain, attenuating capabilities, sandboxed execution,
human-in-the-loop consent, tenancy, and egress control. The pivot turns those
from features into the product.

The recurring failure mode in 2026 enterprise AI (per practitioner guidance):
teams implement logging, access control, and human oversight **separately for
each framework**, producing redundant controls and *gaps at the intersections*.
Maverick's answer is a **single control plane** every agent action flows through,
with each legal regime expressed as a **pluggable policy pack** mapped onto one
set of enforceable primitives.

## 2. The product in one picture

```
  Employee
    └─ Fleet (5–10 named, role-scoped agents: researcher, coder, ops, analyst…)
         every action ─▶ ┌──────────────────────────────────────────────┐
                         │        OVERSIGHT CONTROL PLANE                │
                         │  policy engine: allow / deny / require-human  │
                         │  + supervisor (agent + human operator)        │
                         │  + signed record of every decision (Art 12)   │
                         └──────────────────────────────────────────────┘
                                        ▲ policy = union of
                         ┌──────────────┴───────────────┐
                    Compliance regime packs (pluggable):
                    EU AI Act · NIST AI RMF · Colorado ADMT ·
                    NYC LL144 · HIPAA/GLBA/FCRA · GDPR residency
```

## 3. Architecture — three layers

### Layer A — Oversight control plane (the keystone / "hive mind")

A **persistent supervisor + org-policy engine** that every agent action consults
before it executes: returns **allow / deny / require-human / log**, and records
the decision to the audit chain. This is the hive-mind: one governing layer with
authority over the whole fleet, plus a human operator who can monitor and
intervene live.

- **Builds on (already shipped):** attenuating capabilities (`capability.py`),
  consent/HITL (`safety/consent.py`), signed audit (`audit/signing.py`),
  blackboard + agent-bus coordination, the recursive swarm.
- **The gap:** today governance is *per-goal and in-process*. We need to elevate
  it to a **persistent, cross-fleet control plane** — a policy engine consulted
  on every action, a supervisor role with read/intervene authority over many
  running agents, and live operator controls (approve / deny / pause / kill).

### Layer B — Compliance-regime engine (EU + US, pluggable)

The unifying insight: **don't implement controls per-law.** Define one set of
enforceable primitives and map every framework onto them. Each regime is a
**policy pack** an operator turns on per deployment; the active policy is their
union (strictest-wins).

This is also the hedge against a volatile landscape (the Dec 2025 federal
preemption EO vs. still-enforceable state laws): regimes are configuration, so a
deployment enables exactly the packs its jurisdiction + sector require.

### Layer C — Per-employee agent fleets

The unit of sale: a user **owns N persistent, named, role-scoped agents** running
ongoing and scheduled work, governed by the supervisor and bounded by their
role's capability.

- **Builds on (already shipped):** tenancy (`paths.py`), per-principal
  capabilities + RBAC roles, the scheduler/worker, `maverick ps`.
- **The gap:** a first-class `Fleet` abstraction (owner + roster + role bindings
  + policy binding), agent lifecycle (create / pause / retire), and the
  per-employee operator UX.

## 4. Compliance mapping — frameworks → primitives we already own

Each obligation below maps to a Maverick control. **Bold** = already shipped and,
in several cases, exceeding the baseline; *italic* = the gap this roadmap closes.

| Regime | Key obligation | Maverick control |
|---|---|---|
| **EU AI Act Art 12** (record-keeping) | append-only logs, hash-chained, ≥6-month retention | **Ed25519 *Merkle*-chained audit (`audit/signing.py`) — exceeds the SHA-256 append-only baseline**; *+ retention policy enforcement* |
| **EU AI Act Art 14** (human oversight) | monitor / intervene / override; explicit automation boundary | **consent/HITL + capability risk-ceilings**; *+ control-plane `require-human` gate + operator console* |
| **EU AI Act Art 50** (transparency, due Dec 2026) | disclose AI; mark AI-generated content | *agent-identity disclosure + output marking pack* |
| **EU AI Act risk-tiering** | classify the system's risk tier | *per-fleet/agent risk classification on the policy pack* |
| **NIST AI RMF** (US de-facto anchor) | Govern / Map / Measure / Manage | **audit + capabilities + budget/quotas + eval harness** map to all four; *+ RMF evidence report* |
| **Colorado SB 26-189 / NYC LL144 / EEOC** | consequential-decision logging, human review, bias audit | *employment/consequential-decision pack: decision records + mandatory human review + bias-audit export* |
| **HIPAA / GLBA / FCRA** (sectoral) | restrict + log sensitive-data handling | **capability path/host scopes + egress lock + tenancy**; *+ sector data-class tags* |
| **GDPR** | data residency + erasure (Art 17) | **egress lock to EU/local providers + DSAR erasure (`audit/erase.py`) + tenancy** |

**Honest read on timing.** EU high-risk (Annex III) duties were deferred to **Dec
2027** by the May 2026 Digital Omnibus, but **transparency (Dec 2026)** and
**GPAI rules (live since Aug 2025)** bite sooner — and US state laws are
enforceable now. The control plane should ship before the obligations land so
customers adopt ahead of the deadline, not under it.

## 5. What we already own (the moat)

- **Signed, tamper-evident audit** (Ed25519 Merkle chain + offline verify) —
  stronger than the Art 12 standard, and the evidentiary backbone for *every*
  regime.
- **Attenuating capabilities** — least privilege that can only narrow as it
  propagates to sub-agents; the access-control primitive every framework wants.
- **Consent / HITL** — the Art 14 intervention substrate.
- **Seven execution sandboxes, egress lock, tenancy, quotas, OIDC/proxy SSO,
  RBAC, SIEM export** — the enterprise-ops surface.
- **The recursive swarm** — the multi-agent substrate the fleet and supervisor
  are built from.

The pivot is not a rebuild; it is **promoting these from per-run features to a
persistent, multi-tenant control plane**, plus the regime packs and the fleet
model on top.

## 6. Build sequence

1. **Keystone — oversight control plane.** A `governance` policy engine:
   org policy → per-action decision (`allow` / `deny` / `require_human` / `log`),
   consulted by the agent on every tool call, recording each decision to the
   audit chain. A supervisor read/intervene API. Offline-unit-testable on the
   decision logic. *(This PR's successor.)*
2. **Compliance-regime packs.** A `ComplianceRegime` abstraction + the first
   packs (EU AI Act, NIST AI RMF) as policy + evidence mappings; a
   `maverick compliance status --regime <id>` posture report (generalizes the
   existing `soc2` command).
3. **Fleet model.** A `Fleet` / roster abstraction + lifecycle + supervisor
   binding + the per-employee unit.
4. **Operator console.** A dashboard view of the fleet with **live human
   oversight** — approve / deny / pause / kill — the Art 14 UI surface.

## 7. Honest caveats

- **"Compliant" = "provides the technical controls and evidence that compliance
  requires" — not legal certification.** The mapping of *your* obligations to
  *your* risk tier needs counsel; Maverick supplies the enforceable controls and
  the audit evidence, and makes the posture auditable.
- **The US federal picture is volatile.** The pluggable-pack design is the hedge:
  enable the regimes a deployment is actually subject to; the strictest-wins
  union keeps multi-jurisdiction deployments safe by default.

## 8. Sources (legal grounding, June 2026)

- EU AI Act timeline & Digital Omnibus deferral — [EU AI Act implementation timeline](https://artificialintelligenceact.eu/implementation-timeline/); [Digital Omnibus update](https://www.insideprivacy.com/artificial-intelligence/eu-ai-act-update-timeline-relief-targeted-simplification-and-new-prohibitions/)
- Art 12 logging & Art 14 oversight for agents — [Help Net Security: EU AI Act agent logging](https://www.helpnetsecurity.com/2026/04/16/eu-ai-act-logging-requirements/); [AI-agent EU AI Act checklist](https://thebrightbyte.com/playbook/expertise/eu-ai-act-compliance-ai-agents)
- US landscape (NIST RMF anchor, state patchwork, Dec 2025 EO) — [Baker Botts US AI Law Update](https://www.bakerbotts.com/thought-leadership/publications/2026/january/us-ai-law-update); [US state AI laws tracker](https://www.glacis.io/guide-state-ai-laws)
