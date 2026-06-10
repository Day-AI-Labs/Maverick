# Maverick Summit v1 (virtual) — run-of-show kit

**Roadmap ref:** 2027-H1 Distribution — "Maverick Summit v1 (virtual)".
**Status:** kit complete; running the event is the remaining operational work.
**Date, platform, and registration cap are founder decisions** — every such
slot below is marked.

A half-day virtual event: talks, live demos, and office hours, run by a small
team (2-4 people is enough). The goal is not reach for its own sake — it's to
put the runtime in front of evaluating teams, capture honest questions, and
produce reusable artifacts (recordings, demo traces, an FAQ). No invented
attendance targets; measure what happens and publish it.

## Event parameters (founder-set)

| Parameter | Value |
|---|---|
| Date | _founder decision — pick a date ≥8 weeks out for speaker lead time_ |
| Duration | 3.5 hours recommended (see agenda); founder may extend |
| Platform | _founder decision — any platform meeting the tech checklist below_ |
| Registration | Free recommended (this is a distribution program, not revenue) |
| Capacity cap | _founder decision; platform-dependent_ |
| Recording policy | Record everything except office hours; publish within 2 weeks |

## Agenda template (half-day, single track)

Times are offsets from the start; shift freely. Every demo block names the
real feature it shows — do not demo anything that isn't in
[`FEATURES.md`](../FEATURES.md).

| Offset | Block | Content |
|---|---|---|
| −0:30 | Tech rehearsal | All speakers join, screen-share check, demo dry run |
| 0:00 (15 min) | Welcome + state of Maverick | What shipped since the last public update — sourced from `FEATURES.md` and `CHANGELOG.md`, nothing aspirational |
| 0:15 (25 min) | Keynote: the governed agent runtime | The [`architecture.md`](../architecture.md) story: swarm + budget + sandbox + shield + audit; why governance is the differentiator |
| 0:40 (20 min) | **Live demo 1 — long-horizon swarm** | `maverick start "<multi-step goal>"` in one terminal, `maverick monitor` (Rich plan-tree TUI) in another; show sub-agent spawn, the live cost meter, and `maverick status --cost` |
| 1:00 (20 min) | **Live demo 2 — governance** | The dashboard oversight console (`maverick dashboard` → `/oversight`): approval queue, "why this action" drill-down; then `maverick halt` killing a live run and `maverick audit verify` proving the log chain |
| 1:20 (10 min) | Break | Pre-recorded demo loop or holding slide |
| 1:30 (20 min) | **Live demo 3 — safety floor** | A prompt-injection attempt caught at a shield chokepoint (the chokepoint model: [`docs/safety.md`](../safety.md)); show the red-team gate (`python -m maverick_shield.redteam`) and its `--calibrate` operating-curve sweep |
| 1:50 (20 min) | Talk: extending Maverick | Skills (`maverick skill install`), plugins ([plugin API v2](../plugin-api-v2.md), TS SDK `sdks/plugin-ts/`), MCP (`maverick mcp`), channels — the extension surface from the [handbook](../handbook.md) |
| 2:10 (20 min) | Guest / community talk | A real deployment story (showcase-wall standard of evidence: a replayable trace or run export, see [`showcase.md`](../showcase.md)). If no qualifying guest exists yet, run a second internal deep-dive instead — do not stage a fake customer story |
| 2:30 (10 min) | Roadmap, honestly | What's planned vs. built, straight from [`ROADMAP.md`](../ROADMAP.md), including what was declined and why (e.g. the Redis world-model decision) |
| 2:40 (40 min) | **Office hours / open Q&A** | Unrecorded. Triage live; park deep questions into GitHub issues in front of the audience |
| 3:20 (10 min) | Close | Where everything lives: repo, docs, getting-started, how to request an evaluation license |

## Speaker brief (send ≥4 weeks before)

One page per speaker, containing:

1. **Slot, length, and hard stop.** Talks end on time; the schedule has no
   slack for overruns.
2. **Claims policy.** Every capability claim must be grounded in
   `FEATURES.md`. Forward-looking statements must be labeled as roadmap and
   match `ROADMAP.md`. No invented benchmark numbers — measured rows in
   `benchmarks/RESULTS.md` are quotable; anything else is not.
3. **License framing.** Maverick is proprietary, commercially licensed
   software ([`LICENSE`](../../LICENSE)). Do not describe it as open source
   or imply open-source terms. The "lite" edition is a stated possibility on
   the roadmap, not a commitment — say exactly that if asked.
4. **Demo rules.** Live demos run against a real install with a hard budget
   cap set (`--max-dollars`), a pre-recorded fallback ready, and no secrets
   on screen (use a scratch `~/.maverick/` profile; check `config.toml` and
   terminal scrollback before sharing).
5. **Logistics.** Platform link, rehearsal time, slide template (if any),
   recording consent, and the contact for day-of problems.
6. **Bio + headshot request** for the event page.

## Tech checklist

### Streaming

- [ ] Platform supports: screen share, ≥2 simultaneous presenters, audience
      Q&A or chat, registration export. (_Platform choice: founder._)
- [ ] Wired connection for every presenter; phone-hotspot fallback tested.
- [ ] One person is **producer** (not a speaker): admits speakers, runs the
      holding slides, watches chat, cuts a frozen screen share.
- [ ] Backup presenter machine with the demo environment cloned.
- [ ] Demo environment: a clean install (`pipx install 'maverick-agent[installer]'`,
      `maverick init`), `maverick doctor` green, API keys with low spend
      limits, budget caps configured.

### Recording

- [ ] Local recording on the presenter machine **and** platform-side
      recording (two copies of every talk).
- [ ] Office hours not recorded; say so at the start of the block.
- [ ] Post-production owner named before the event (trims, chapter markers,
      captions).

### Q&A

- [ ] Question intake: platform Q&A or a pinned form; one person triages.
- [ ] Parking lot: questions that need code-level answers become GitHub
      issues, filed live, links posted in chat.
- [ ] A prepared FAQ for the predictable questions: licensing terms, the
      lite edition, self-hosting/air-gap, model choice, pricing
      ("per engagement — contact us", per [`docs/index.md`](../index.md)).

## Success metrics

Define the measures now; set targets only after a baseline exists. **No
targets are published for v1** — v1 *establishes* the baseline that v2
(2028-H1, hybrid) is measured against.

| Metric | Source | Notes |
|---|---|---|
| Registrations / attendance / peak concurrent | platform export | |
| Watch-through rate per talk | platform analytics | identifies which content carries |
| Questions asked + issues filed from Q&A | producer tally + GitHub | quality signal, not vanity |
| Evaluation-license inquiries within 30 days | licensor inbox | the metric that matters commercially |
| Recording views at 30/90 days | hosting analytics | the long tail is usually larger than the live event |
| Survey: "was this worth your time" + free text | post-event form | 3 questions max; reuse the [community survey](./community-survey.md) tooling |

## Post-event artifact plan

Within 2 weeks of the event:

1. **Recordings published** with chapters and captions; linked from the docs
   site and README.
2. **Demo traces released** — each live demo's run captured via
   `MAVERICK_TRACE_DIR` and published (secret-scrubbed) so viewers can
   inspect it with `maverick diag replay`; the long-horizon demo additionally
   exported as a step-by-step tutorial (the dashboard's
   `GET /api/v1/goals/{id}/tutorial.md` export).
3. **FAQ updated** from the actual Q&A; answers that belong in docs become
   doc PRs instead of a standalone FAQ page where possible.
4. **Metrics memo** (internal, one page): the table above filled in, plus
   what to change for v2. This memo is the v2 planning input.
5. **Thank-you + follow-up email** to registrants: recordings link, docs
   entry points, evaluation-license contact. One email. No drip campaign.

## Budget

All costs founder-approved before commitment. Expected line items: platform
license, captioning, speaker thank-yous (see [`swag.md`](./swag.md)), and
optional paid promotion (see the boundaries in
[`github-stars-campaign.md`](./github-stars-campaign.md) — the same honesty
rules apply to event promotion). **Amounts: maintainer-set.**
