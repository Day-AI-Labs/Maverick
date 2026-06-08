# The agent-to-agent protocol — identity, handoffs, authorization, verification

**Status:** design / roadmap — a load-bearing differentiator. Companion to the
[self-extending agent factory](self-extending-agent-factory.md) and the eight agent
suites ([`agent-suites-overview.md`](agent-suites-overview.md)). Builds on
[`../enterprise/architecture.md`](../enterprise/architecture.md).

> **The thesis, from first principles.** A business *is* its handoffs — sales hands a
> closed deal to finance, engineering hands a build to QA, a deal team hands terms to the
> deal desk. An agent business needs the same nervous system, but with three things human
> orgs only approximate: **machine-verifiable identity** (you can't impersonate a
> colleague), **least-privilege handoffs** (you get exactly the authority for the task and
> not one bit more), and a **non-repudiable record** (every handoff is signed and
> replayable). Trust is *structural* — built from signed capabilities and compartment
> seals — not assumed because a message arrived.

Today Maverick agents are **hub-and-spoke**: "specialists never talk to each other
directly — they post to the blackboard; the orchestrator reads it" (`blackboard.py`). That
is safe but limited. This protocol is the deliberate evolution to an **authorized,
identity-verified agent society**, keeping the orchestrator/supervisor as the trust root.

---

## Contents

1. [The five questions, answered](#1-the-five-questions-answered)
2. [What's already shipped — the reuse map](#2-whats-already-shipped--the-reuse-map)
3. [Identity — who an agent *is*](#3-identity--who-an-agent-is)
4. [Communication — how agents talk](#4-communication--how-agents-talk)
5. [Handoff — delegating work as attenuated authority](#5-handoff--delegating-work-as-attenuated-authority)
6. [Authorization — who may hand what to whom](#6-authorization--who-may-hand-what-to-whom)
7. [Verification & anti-impersonation](#7-verification--anti-impersonation)
8. [Containment — when an agent goes bad](#8-containment--when-an-agent-goes-bad)
9. [The envelope (concrete schema)](#9-the-envelope-concrete-schema)
10. [Build sequence](#10-build-sequence)
11. [Honest caveats](#11-honest-caveats)

---

## 1. The five questions, answered

The exact questions to settle, each answered from a shipped primitive:

| Question | Answer | Primitive |
|---|---|---|
| **How do agents communicate?** | Typed, schema'd messages on a bus that evolves from the blackboard; the supervisor is router + trust root. Every message is an audit entry. | `blackboard.py` → message bus; audit chain |
| **What are the handoffs?** | A handoff = delegating a scoped sub-task by **minting an attenuated capability** for the receiver, carried in a signed envelope. | `capability.attenuate()` |
| **How do we authorize it?** | `governance.evaluate` on the handoff (who may delegate what to whom); cross-seal handoffs are denied or `REQUIRE_HUMAN`. | `governance.py`, `quarantine.py` |
| **How do we verify identity?** | Each agent is a **principal with an Ed25519-signed capability** issued by the supervisor; envelopes are signed and provenance-checked. | `capability.sign/verify`, principal lineage |
| **How do we stop a bad actor?** | Quarantine-seal the principal (messages rejected fleet-wide), revoke its capability, killswitch. | `quarantine.py`, `killswitch.py` |

---

## 2. What's already shipped — the reuse map

| Capability | Module | Status | Role in the protocol |
|---|---|---|---|
| **Principal identity + signed grant** | `capability.py` (`sign_capability`/`verify_capability`) | **Shipped** | An agent's identity *is* its signed capability |
| **Attenuating delegation** | `capability.attenuate()` (narrow-only, expiry inherited) | **Shipped** | The handoff mechanic — authority only shrinks |
| **The authorization gate** | `governance.evaluate` (ALLOW/DENY/REQUIRE_HUMAN) | **Shipped** | Authorizes (or human-gates) a handoff |
| **Compartment seals** | `quarantine.py` (Rung-2) | **Shipped** | Cross-seal handoff control; bad-actor containment |
| **Current comms substrate** | `blackboard.py` (append-only, compartment-aware) | **Shipped** | Hub-and-spoke today; the bus evolves from it |
| **Non-repudiable record** | the signed Merkle audit chain | **Shipped** | Every handoff is signed + replayable |
| **Fleet identity / oversight** | `fleet.py`, `oidc.py`, the supervisor (Layer A) | **Shipped/partial** | The issuing authority + router |
| **Egress lock / kill** | `enterprise.py`, `killswitch.py` | **Shipped** | Blast-radius limits |

**The genuine build:** the **addressed message bus + envelope schema**, the
**provenance/lineage verifier**, the **cross-compartment handoff policy**, and the
**revocation list**. The trust primitives (signed capabilities, the gate, seals, the
chain) are shipped.

---

## 3. Identity — who an agent *is*

An agent is not a name string — names are forgeable. **An agent's identity is its
Ed25519-signed `Capability`**, issued by the supervisor that spawned it:

- the **principal** (`agent:<role>-<depth>` today, hardened to include a per-spawn
  nonce/lineage id),
- the **grant** it runs under (tools/paths/hosts/risk/expiry), and
- the **issuer signature** (`sign_capability`) verifiable against the supervisor's public
  key (`verify_capability`).

"Verify this is who they say they are" = verify the signature against the issuing
authority's pubkey **and** that the principal's lineage chains back to a supervisor the
recipient trusts. Identity is cryptographic, so impersonation requires forging Ed25519 —
infeasible — not just claiming a name.

---

## 4. Communication — how agents talk

**Today (hub-and-spoke, shipped):** agents post `Entry`s to the `Blackboard`; the
orchestrator reads and routes. Sealed agents' posts are already withheld so a poisoned
finding can't steer the swarm. This stays the default and the floor.

**Evolution (the society):** an **addressed message bus** with three patterns —
*request/response* (a direct handoff), *broadcast* (status to a tower), *subscribe* (a
supervisor watching a topic). Properties:

- **The supervisor is the router and trust root.** Direct peer messages are still
  mediated/observable by the Layer-A plane — no dark side channels around the gate.
- **Typed, schema'd payloads** (not free text) so a handoff is machine-checkable.
- **Every message is an audit entry** — the bus *is* an extension of the signed chain.
- **Compartment-aware by construction** — a sealed (MNPI/board/privileged) agent cannot
  broadcast outside its wall; the existing blackboard withholding generalizes to the bus.

---

## 5. Handoff — delegating work as attenuated authority

A handoff is the heart of it, and the mechanic is already in the kernel: **delegation =
`capability.attenuate()`.** When agent A hands a sub-task to agent B:

1. A mints a **child capability** scoped to *exactly* the task — the specific tools,
   path/host globs, a risk ceiling, and a **short expiry** — by attenuating its own grant.
   By construction the child is ≤ A's grant; A cannot delegate authority it lacks.
2. The grant is signed and carried in the handoff envelope (§9).
3. B runs the sub-task **under that grant and nothing more** — no ambient authority. This
   is the **confused-deputy defense**: B acts with the *originator's attenuated* authority
   for this task, never B's broader standing authority.
4. On completion the child grant expires; the result is posted back as a signed message.

**Business handoffs map directly.** GTM Commissions → Finance Payroll for a payout: GTM
hands Finance a **read-only, expiring** grant for the *specific* commission records — and
the payout itself remains a `REQUIRE_HUMAN` floor. Deal-desk, legal redline routing, and
PMI cross-functional handoffs are the same shape: scoped, expiring, signed, audited.

---

## 6. Authorization — who may hand what to whom

Two layers decide whether a handoff is allowed:

1. **Attenuation (automatic, can't escalate).** The child grant is provably ≤ the
   delegator's — a handoff can never *raise* privilege. This is free from `attenuate()`.
2. **Policy (`governance.evaluate`).** The handoff action is evaluated against org policy:
   - a handoff that crosses into/out of a **sealed compartment** (MNPI deal room, board,
     privileged investigation) is `DENY` or `REQUIRE_HUMAN` by policy — the ethical wall
     is structural;
   - a handoff that would let the receiver perform a **gated action** (move money, send
     externally, deploy to prod) carries the gate with it — the receiver still hits
     `REQUIRE_HUMAN` for that action;
   - role policy (`[roles]`/`[role_assignments]`) bounds which seats may delegate which
     scopes (segregation of duties: close ≠ forecast ≠ commission).

The verdict (rule + reason) lands on the audit chain, so *why* a handoff was allowed,
denied, or escalated is always answerable.

---

## 7. Verification & anti-impersonation

The receiver of a handoff runs a fixed check before acting:

1. **Signature** — `verify_capability(grant, sig, issuer_pubkey)` against a **trusted
   issuer** (the supervisor's key, per the `trusted_pubkeys` trust-anchor model already
   used for signed skills). A self-asserted key with no anchor is *integrity, not
   authenticity* — and is rejected where authenticity is required.
2. **Provenance / lineage** — the principal's spawn chain resolves back to a supervisor
   the receiver trusts (the parent→child grant chain). A grant with no resolvable lineage
   is refused.
3. **Freshness** — a nonce + timestamp inside the signed envelope (replay defense); the
   bus rejects a re-sent envelope.
4. **Scope sanity** — the carried grant actually `permits` the requested task; a mismatch
   (asking for more than the grant covers) is refused and audited.

Fail any check → the message is dropped and logged. Impersonation requires forging an
Ed25519 signature *and* a lineage chain — not guessing a principal name.

---

## 8. Containment — when an agent goes bad

A compromised or misbehaving agent is contained without taking down the fleet:

- **Quarantine seal** (`quarantine.py`, Rung-2): the principal (and its sub-tree) is
  sealed; its posts/messages are withheld and rejected fleet-wide (the blackboard already
  does this for sealed agents; the bus generalizes it).
- **Revocation list:** its capability is revoked; in-flight handoffs carrying it fail
  verification (§7). This is the mid-session revocation sweep the capability layer flags
  as its real gap — the protocol is its first consumer.
- **Killswitch** (`killswitch.py`): the fleet-level stop for a confirmed incident.

---

## 9. The envelope (concrete schema)

A handoff message, signed end-to-end and recorded on the chain:

```jsonc
{
  "from":   "agent:gtm_commissions-2",      // sender principal (lineage-resolvable)
  "to":     "agent:finance_payroll-1",      // recipient principal | role | topic
  "intent": "handoff",                       // handoff | request | response | broadcast
  "task":   "reconcile Q2 commission accruals for payout batch 4471",
  "grant": {                                 // the attenuated child capability
    "principal":  "agent:finance_payroll-1",
    "allow_tools":["read_file","knowledge_search"],
    "max_risk":   "low",
    "allow_paths":["/data/comp/2026Q2/*"],
    "expires_at": 1751900000
  },
  "grant_sig":   "ed25519:…",               // issuer (supervisor) signature over the grant
  "issuer_pub":  "…",                        // anchored in trusted_pubkeys
  "nonce":   "9f2c…",                         // replay defense
  "ts":      1751890000,
  "body":    { … },                          // typed payload
  "sig":     "ed25519:…"                      // signature over the whole envelope
}
```

Everything outside `body` is the *trust frame*; `body` is the work. The whole envelope is
appended to the signed Merkle audit chain — non-repudiation by default.

---

## 10. Build sequence

1. **Harden principal identity** — per-spawn lineage id + sign every spawned capability
   (`sign_capability` on `agent_from_profile`); store the issuer pubkey.
2. **The envelope + verifier** (§7, §9) as a library — signature + lineage + freshness +
   scope, with the audit append. Pure and unit-testable, like `governance`.
3. **The message bus** evolving from `blackboard` — addressed request/response first,
   supervisor-mediated, compartment-aware; broadcast/subscribe next.
4. **Handoff = attenuated grant** wired through the bus; `governance` authorization +
   cross-seal policy on the handoff action.
5. **Revocation list + sweep**, consumed by the verifier and `quarantine`.
6. **Console** (rule 6): the live handoff graph + the authorization/revocation queue.

---

## 11. Honest caveats

- **The bus must not become a side channel around capabilities.** If a peer message can
  do what the capability forbids, the whole model is theater. Messages carry grants; they
  never *are* grants. The supervisor stays in the path.
- **Key management is real work.** Per-agent signing means per-supervisor issuing keys and
  rotation; reuse the audit-signing key infra, don't invent new crypto.
- **Lineage depth vs performance.** Verifying a deep provenance chain on every message has
  a cost; cache verified lineages per run, re-check on revocation events.
- **The orchestrator remains the trust root.** This is a *mediated* society, not a flat
  mesh — direct peer messaging is an optimization over the hub, not an escape from it.
- **Compatible in spirit, grounded in our own primitive.** Where this rhymes with emerging
  cross-vendor agent-messaging ideas, good — but the authority model is *our* signed,
  attenuating capability, not a name-based "agent address book." That is the part that is
  actually safe.
