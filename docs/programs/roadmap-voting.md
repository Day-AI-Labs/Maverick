# Public roadmap voting

**Roadmap ref:** 2028-H2 "public roadmap voting". The mechanism rides
GitHub (no new infrastructure, identities are real accounts, history is
public); operating the quarterly triage is a maintainer act.

## Mechanism

1. **One Discussion category: "Roadmap proposals."** One proposal per
   thread, template-enforced: *what*, *who needs it* (a real use, not a
   vibe), *which roadmap concern* (capabilities / UX / distribution /
   performance / safety / ecosystem).
2. **Voting = 👍 on the top post.** Comments argue; only the top-post
   reaction counts (cheap to tally, hard to brigade quietly — sock-puppet
   bursts are visible in the account list and discounted in triage).
3. **Quarterly triage (maintainer act, public outcome).** Every proposal
   ≥10 votes gets a written verdict in-thread: **accepted** (lands in
   `ROADMAP.md` with the half-year it targets), **declined** (rationale +
   revisit trigger — the `docs/specs/*-decision.md` discipline applies to
   anything safety-significant), or **needs-shaping** (what's missing).
   No proposal sits unanswered past two triages.
4. **The roadmap stays the source of truth.** Votes inform; they don't
   command. Two standing constraints outrank any vote count: the safety
   posture (a capability the Safety Steering Group declined does not ship
   because it polled well — see
   [governance/safety-steering-group.md](../governance/safety-steering-group.md)),
   and the proprietary licensing position (LICENSE).

## Why not a separate voting site

A standalone portal adds an identity system, a moderation surface, and an
ops burden to produce the same signal GitHub reactions already give —
declined for the same simplicity-first reason the repo declines parallel
process everywhere else.

## Bootstrapping

Seed the category with 3-5 genuinely open questions from the current
roadmap tail (e.g. which localized community to charter first, which
editor integration deepens next) so the first visitors find real decisions
to influence, not an empty room.
