# Governance v2 — elected TSC charter (draft)

**Roadmap ref:** 2028-H2 "governance v2 launch (elected TSC)" (+
"foundation hand-off"). **Status: draft charter, contingent.** Whether an
elected Technical Steering Committee launches at all depends on the
foundation-exploration decision
([programs/foundation-exploration.md](../programs/foundation-exploration.md))
and on the licensing position: Maverick is proprietary (LICENSE), so what a
TSC can govern is **the open surfaces** — the plugin/skill/channel
ecosystem, the public specs and docs, community programs — not the
proprietary core's commercial direction, which remains the company's. The
honest version of "governance v2" is written down here so the launch (a
founder act, post-decision) is an execution step, not a design project.
The foundation kit's own warning applies: the 2028 "hand-off" wording
over-promises what actually transfers.

## Scope — what the TSC governs

1. **Ecosystem standards:** the plugin API surfaces (manifests, TS/gRPC
   host contracts), the channel SDK contract, the certification bars
   ([programs/certification.md](../programs/certification.md)) and their
   evolution.
2. **Community programs:** meetups, hackathons, localized communities,
   ambassadors, the awards — the program kits under `docs/programs/` and
   their budgets once the company delegates them.
3. **Public docs + specs:** `docs/specs/` decision stewardship for
   ecosystem-facing decisions, the public roadmap-voting triage
   ([programs/roadmap-voting.md](../programs/roadmap-voting.md)).

### Explicitly out of TSC scope

The proprietary core's roadmap and licensing; release engineering of the
commercial product; the Safety Steering Group's remit
([safety-steering-group.md](./safety-steering-group.md)) — safety gating is
not subject to election; and anything LICENSE reserves.

## Composition + elections

- **5 seats:** 3 community-elected + 1 company-appointed + the Safety
  Steering Group chair ex-officio (non-voting on program budgets, voting on
  standards).
- **Electorate:** contributors with a merged ecosystem contribution
  (skill/channel/plugin/doc translation/program work) in the trailing 18
  months — a contribution roll published before each election; objections
  window of 2 weeks.
- **Method:** annual, single transferable vote over a public candidate
  thread; 18-month terms staggered so the committee never fully turns over
  at once; two-consecutive-term limit per seat.
- **Quorum/decisions:** 3 of 5; standards changes need 4 of 5 (they break
  other people's code).

## Launch gates (what must be true before elections run)

1. The foundation decision is made (any of the kit's three postures can
   host a TSC; the posture changes who signs the checks, not this charter).
2. The contribution roll exists and is ≥ 25 eligible voters — an election
   among a dozen people is a committee appointment wearing a costume; run
   the interim model below instead until the bar is met.
3. A company delegation letter naming exactly which program budgets and
   standards the TSC owns (scope above), signed before, not after, the
   first vote.

## Interim model (now → launch)

Maintainer-of-record governance with the Safety Steering Group charter's
"decisions recorded" discipline. Each program kit names its operating
owner; community input flows through roadmap voting. This is governance
v1.5, stated plainly — no elections are implied until the gates pass.
