# Agent compartments: per-agent threat isolation + swarm immunity

**Status:** Rung 0 (swarm immunity) **IMPLEMENTED** behind `[safety] compartments`
(off by default). Rungs 1–2 (containment + triage) **DESIGNED** here, not yet
built. The containment half is architecturally significant (it's the safety
foundation of the multi-domain "agent factory"), so per CLAUDE.md it is written
up for sign-off before coding.

## Vision

Maverick is becoming an *agent factory*: domain agents (finance, legal, …) spun
up from one kernel. The safety goal, in the user's words: when one agent finds
something, we "close it off like a door on a submarine," and the rest of the
agents become immune to the attack.

That is two distinct mechanisms — and they are almost opposites:

1. **Immunity** — share a caught threat so every other agent is inoculated.
2. **Containment** — cut links so a compromised agent can't spread.

## Where this lives today

- One **shared `Shield`** per run (`SwarmContext.shield`), built by
  `orchestrator._build_shield()`, used at three chokepoints: goal input
  (`orchestrator.py`), every tool call, and every tool output
  (`agent.py:_run_tool`).
- The base shield is **stateless** — every scan is a pure function, so nothing
  carries "I caught this" across agents.
- **Capabilities** (`capability.py`) already attenuate down the spawn tree — the
  natural primitive for revoking a compromised agent's reach.
- The **blackboard** (`blackboard.py`) is shared + append-only — the real leak
  path: a poisoned finding reaches every sibling unless quarantined.

The shared context cuts both ways. One shield + one blackboard for everyone is
*why immunity is trivial* (a single ledger everybody sees) and *why containment
is hard* (the agents aren't separate processes — you neutralize influence
logically; you can't kill a sandbox).

## The containment ladder (triage-driven)

A single fixed granularity is wrong. A **triage step** reads the verdict and
picks how far to climb:

| Rung | Trigger | Action |
|------|---------|--------|
| **0 — Block + immunize** (default) | any block | base shield blocks the one call; record its signature so every sibling is immune. **No agent killed.** Most shield hits are *deflected probes*, not compromise — killing on every block would self-DoS the swarm. |
| **1 — Quarantine + seal sub-tree** | signs of *actual* compromise (poisoned content landed in the agent's context; repeated trips) | revoke the agent's capability (attenuate to deny-all), quarantine its blackboard posts so siblings/orchestrator stop reading them, halt its sub-tree. |
| **2 — Seal the sector** (latched) | critical severity, or the *same signature hitting multiple agents* (coordinated/structural) | seal the whole domain compartment; keep it sealed until the orchestrator or a human explicitly clears it. |

**Trust invariant (non-negotiable):** detection is *local* (a worker's
chokepoint raises a flag); *promotion* to swarm-wide immunity or containment is
*privileged* (shield/orchestrator). Otherwise a compromised worker weaponizes
the immunity channel itself — inject false signatures, make every sibling refuse
legitimate work. The channel is one-directional and authenticated.

## What's implemented (Rung 0)

`maverick_shield/compartment.py`:

- **`ThreatLedger`** — run-scoped, in-memory, swarm-shared, bounded
  (FIFO-evicted) registry of blocked-payload fingerprints. A fingerprint is the
  SHA-256 of a normalized payload (NFKC + invisible/tag strip + casefold +
  whitespace-collapse), so trivial obfuscation variants share one fingerprint.
  Payloads under 12 normalized chars are ignored to avoid false immunity on
  common short strings.
- **`ImmunizingShield`** — wraps the base `Shield` exactly like `CascadedShield`:
  the same `scan_*` surface. Each scan consults the ledger first (known signature
  → instant block), always runs the base scan (the security floor), and records
  new blocks. Never weaker than the base; fail-open on any ledger error.
- Wired in `_build_shield()`: when `compartments_enabled()`, the single shared
  shield is wrapped — so immunity is automatically swarm-wide and run-scoped,
  with **zero changes to the hot-path chokepoints**.

Enable: `[safety] compartments = true` (or `MAVERICK_COMPARTMENTS=1`), surfaced
in the installer's advanced safety step. Off by default (back-compat, kernel
rule 1).

## Decisions locked

- **Run-scoped immunity first.** The ledger dies with the run.
- **Triage-driven ladder**, not a fixed containment granularity.

## Open decisions (need sign-off before building Rungs 1–2)

1. **Persistence.** Run-scoped today. A cross-run ledger (via the world model)
   would *permanently harden* the factory — but the immunity channel then
   becomes a long-lived poisoning surface (a bad signature outlives the run and
   silently over-blocks). Needs authenticated promotion + TTL/expiry + a clear
   path before it persists.
2. **Fingerprint fuzziness.** Today: exact match on the normalized form (zero
   false positives, catches obfuscation variants, misses rewrites). Phase 2:
   simhash/shingle similarity to catch paraphrases — at a measured
   false-positive cost.
3. **Domain tagging.** Rung 2 ("seal all finance agents") needs a `compartment`
   tag on agents. Roles are free strings today; add a compartment attribute on
   the capability/identity.
4. **Unseal policy.** Who clears a latched Rung-2 seal — orchestrator policy,
   a human, or a TTL?

## Verification

- Implemented: `packages/maverick-shield/tests/test_compartment.py` — fingerprint
  folding, ledger record/check/evict/hits, immunity short-circuit (base not
  re-run on a repeat), obfuscation-variant immunity, tool-call immunity,
  fail-open on a broken ledger, backend label, and the enable flag.
- Rungs 1–2 (when built): a fake swarm asserting a compromised agent's
  capability is revoked, its blackboard posts are withheld from siblings, and a
  domain seal latches until cleared — without touching other domains.
