# The five-year vision (2026 → 2031)

**Roadmap ref:** 2028-H2 ""5-year vision" essay". Written June 2026,
deliberately early: the 2027-2028 build waves cleared the backlog years
ahead of schedule, so the honest move is to say where this goes *now*,
while the claims can still be checked against the tree that exists. Every
backward-looking statement below is grounded in
[FEATURES.md](../FEATURES.md); the forward half is planning intent in the
[2029-2031 roadmap](../ROADMAP-2029-2031.md)'s frame, not prophecy.

## Where we stand (the part you can verify)

Lightwork set out to be a recursive multi-agent swarm for long-horizon
work. What's in the tree today is that, plus the thing we didn't fully
appreciate we were building: a **governed agent platform** — oversight,
compliance regimes, per-employee fleets, tenant walls, capability grants
with boot negotiation, an audit chain you can cryptographically verify,
a safety shield with explainable verdicts, and a kill switch that means
it. The agent is the engine; the governance is why an enterprise can turn
the key.

Three design positions did the most work, and they are the positions we
keep:

1. **The operator owns the blast radius.** Model choice, sandbox backend,
   network egress, capability grants, budgets — all operator-set, all
   enforced, none of it our call to override. The corollary is honesty
   about defaults: a default-local sandbox with the shield off is host
   execution, and our own docs say so in bold.
2. **Fail open on assistance, fail closed on trust.** Compaction,
   suggestions, retrieval — degrade gracefully. Signatures, capability
   checks, consent gates, federation envelopes — reject on doubt. Five
   years from now this sentence should still describe every module.
3. **Decline in writing.** The `docs/specs/*-decision.md` trail (anti-bot
   evasion, Redis primary store, JIT, plugin API v3…) is the cultural
   artifact we're proudest of: "no, and here's why, and here's what would
   change our mind" — scaled to a company.

## 2031: what "winning" looks like

**The boring kind of indispensable.** Five years out, the win condition is
not a demo that goes viral; it's that a regulated team's auditor asks for
evidence and the operator runs three commands. It's a fleet of agents per
employee where the interesting question moved from "can it?" to "what did
we delegate this quarter, at what cost, under which controls?" — questions
our retrospective generators already answer in miniature.

Concretely, by 2031:

- **Agents as governed infrastructure.** Procurement treats an agent
  runtime like a database: SLAs (we publish ours), attested supply chains
  (signing + SBOM machinery shipped), confidential-compute deployment when
  the hardware is there (the posture checks already are), third-party
  audits on a cadence (the readiness docs are the standing scope).
- **An ecosystem with a real economy.** Skills/channels/plugins certified
  by mechanical gates, federated across instances with fail-closed
  provenance, donate-direct supporting authors — the marketplace machinery
  exists; the five-year work is the community that fills it (the
  `docs/programs/` kits are the playbook, run year over year).
- **Multi-agent as the default shape.** The single-assistant era ends on
  its own. The bet we made early — recursion, budgets, blackboards,
  federation between *organizations'* swarms — is the part of the stack
  hardest to retrofit, and by 2031 it's the part everyone needs. A2A for
  identity, signed envelopes between instances, reciprocity proven by
  audit: inter-company delegation with receipts.
- **The lite-edition question answered deliberately.** Proprietary core,
  possible open lite edition: by 2031 that decision is long made — on the
  foundation kit's criteria and the licensing realities, not on a
  competitor's news cycle. Either answer is fine; an accidental answer is
  not.

## What we refuse to become

The five-year anti-vision, recorded with the same force: not an
evasion-kit vendor (the decision doc stands), not a "trust us" black box
(verifiable audit or it didn't happen), not a platform that quietly
re-licenses community work (program kits carry the license terms
up front), and not a system whose safety story is a marketing page —
the Shield's misses go in the safety report, including the embarrassing
ones.

## The cadence that gets us there

Annual: safety report + benchmark retrospective + UX retrospective (the
generators ship; running them is the ritual). Biennial: the survey +
program reset. At the 3-year mark (2029): the retrospective this roadmap
already gates, and the 2029-2031 plan graduates from frame to backlog. At
five (2031): whoever writes the next one of these starts by diffing it
against this file. That's the test we set ourselves: **the 2031 essay
should be a changelog, not a retraction.**
