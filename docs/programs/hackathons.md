# Hackathon series — kit

**Roadmap ref:** 2028-H2 "hackathon series". A repeatable format, not one
event; running each instance is a maintainer/ambassador act. Everything a
participant touches below is shipped and verified.

## Format (one instance)

- **Length:** 48h online, or 1-day in-person riding a meetup
  ([meetups.md](./meetups.md)) or the conference lab.
- **Track prompts (pick 2-3):** build a skill (`maverick skill validate`
  as the entry bar), build a channel adapter (the certification contract
  suite as the bar — see [certification.md](./certification.md)), build a
  TS/gRPC plugin (`sdks/plugin-ts`, `grpc_api/plugin_host.proto`), or the
  open data track (dashboards over a run's audit/spend exports).
- **Starting line:** the demo-cluster blueprint
  (`deploy/reference-architectures/demo-cluster/`) + starter goals
  (`docs/starter-goals.md`) + the scaffold generators (`template_generator`
  tool) so hour one is building, not installing.
- **Judging = the gates + a demo.** Submissions must pass their track's
  mechanical bar (validator / contract suite / moderation scan); judges
  rank only what passed, on a 3-minute demo. Rubric: works (40), useful
  (30), honest scope in the README (20), polish (10).

## Licensing rule (read before announcing)

Maverick is proprietary (LICENSE). Participants build **on top of** the
platform (skills, adapters, plugins they own) — the event grants no
license to the platform source beyond what participants already have, and
submissions must not vendor Maverick code. Put this in the event terms
verbatim; the university-outreach kit's educational-license language
applies for student events.

## Prizes + follow-through

Founder-set prize pool (zero is acceptable: certification + a showcase
wall entry + Skill-of-the-Year nomination are real prizes here —
[skill-of-the-year.md](./skill-of-the-year.md)). Every passing submission
gets: a showcase entry offer, a certification run, and a 30-day follow-up
ping (the survey kit's template) — the series' success metric is
**submissions still maintained at +90 days**, not weekend headcount.

## Series cadence

Quarterly online + opportunistic in-person. After each: a retro thread
(what track prompts produced maintained work?) feeding the next instance's
prompt selection.
